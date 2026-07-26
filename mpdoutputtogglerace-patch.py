# mopidy_mpd/protocol/audio_output.py の toggleoutput() が
# `context.core.mixer.get_mute()` (読み取り) と `context.core.mixer.set_mute(not
# mute_status)` (書き込み) という2回の**別々の** pykka actor 呼び出しを、その間を
# 保護する仕組み無しに実行している TOCTOU レース。TODO 全項目消化済みのため
# 自走エージェントが mopidy_mpd のコード品質を再調査して新規発見・追加した項目
# (mpdtogglemuterace-patch.py が同じ関数の「set_mute()の.get()未呼び出し」という
# 別種の不具合を既に修正済みだが、この read-modify-write 自体の非原子性には
# 手を入れていなかった)。
#
# 実害: mopidy_mpd は各クライアント接続を別OSスレッドの pykka.ThreadingActor
# (MpdSession) として実行する。rmpc の Outputs モーダル (`rmpc/src/ui/modals/
# outputs.rs::toggle_selected_output()` → `rmpc-mpd/src/mpd_client.rs`
# `send_toggle_output` 経由で `toggleoutput {ID}` を送信) からの toggle 操作は
# ごくありふれた単純操作で、同一 mopidy サーバへ複数クライアント接続(2台目の
# rmpc、他の MPD クライアント等)が張られるのも通常運用の範囲内。2本の接続が
# ほぼ同時に `toggleoutput 0` を送ると、両方が同じ古い `mute_status` を読んだ後に
# 両方が同じ `not mute_status` を書き込んでしまい (lost update)、本来2回の
# トグルは元の状態に戻るはずが1回分の変化しか反映されない。両クライアントとも
# `OK` を受け取るため、サイレントに mute 状態が食い違ったまま `outputs` の
# `outputenabled` に反映され続ける。同じ mute 状態を書き換える
# enableoutput/disableoutput もこの読み取りウィンドウに割り込めるため、
# 合わせて直列化する。
#
# 修正: mpdurimaprace-patch.py/mpdchannelrace-patch.py 等と同じ流儀で、
# audio_output.py にモジュールレベルの `threading.Lock()` を追加し、
# disableoutput/enableoutput の `set_mute()` 呼び出しと toggleoutput の
# `get_mute()`→`set_mute()` の複合操作を `with` ブロックで直列化する。
# いずれも SoftwareMixer への軽量な in-process actor 呼び出しのみで
# バックエンドへの長時間ネットワーク呼び出しを含まないため、
# mpdurimaprace-patch.py が警戒した「listall事案のような長時間ブロック」の
# 懸念は無い。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

MARKER = "_output_mixer_lock"
if MARKER in s:
    print("mpdoutputtogglerace already applied to audio_output.py, skip")
else:
    # 1) import threading
    old_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "import threading\n\nfrom mopidy_mpd import exceptions, protocol, translator\n"
    )
    s = s.replace(old_import, new_import, 1)

    # 2) モジュールレベルLock定義 (disableoutputハンドラの直前に挿入)
    old_helper = (
        "def _mpdoutputpartition_owned(context):\n"
        '    return translator.output_partition_get("Mute") == translator.partition_get(\n'
        "        id(context.session)\n"
        "    )\n"
        "\n"
        "\n"
        '@protocol.commands.add("disableoutput", outputid=protocol.UINT)\n'
    )
    assert s.count(old_helper) == 1, f"old_helper count={s.count(old_helper)}"
    new_helper = (
        "def _mpdoutputpartition_owned(context):\n"
        '    return translator.output_partition_get("Mute") == translator.partition_get(\n'
        "        id(context.session)\n"
        "    )\n"
        "\n"
        "\n"
        "# enableoutput/disableoutput/toggleoutputの3ハンドラは全クライアント接続間で\n"
        "# 共有されるcontext.core.mixerのmute状態に対しget→set(toggleoutputのみ)/set\n"
        "# という複合操作を行うため、Lockで直列化する(mpdoutputtogglerace-patch.py)。\n"
        "_output_mixer_lock = threading.Lock()\n"
        "\n"
        "\n"
        '@protocol.commands.add("disableoutput", outputid=protocol.UINT)\n'
    )
    s = s.replace(old_helper, new_helper, 1)

    # 3) disableoutput() 本体
    old_disable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        success = context.core.mixer.set_mute(False).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems disabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_disable) == 1, f"old_disable count={s.count(old_disable)}"
    new_disable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        with _output_mixer_lock:\n"
        "            success = context.core.mixer.set_mute(False).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems disabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_disable, new_disable, 1)

    # 4) enableoutput() 本体
    old_enable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        success = context.core.mixer.set_mute(True).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems enabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_enable) == 1, f"old_enable count={s.count(old_enable)}"
    new_enable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        with _output_mixer_lock:\n"
        "            success = context.core.mixer.set_mute(True).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems enabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_enable, new_enable, 1)

    # 5) toggleoutput() 本体 (get_mute -> set_mute の複合操作を丸ごとLock区間に)
    old_toggle = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        mute_status = context.core.mixer.get_mute().get()\n"
        "        success = context.core.mixer.set_mute(not mute_status).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems toggling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_toggle) == 1, f"old_toggle count={s.count(old_toggle)}"
    new_toggle = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        with _output_mixer_lock:\n"
        "            mute_status = context.core.mixer.get_mute().get()\n"
        "            success = context.core.mixer.set_mute(not mute_status).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems toggling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_toggle, new_toggle, 1)

    open(p, "w").write(s)
    print(
        "patched audio_output.py: toggleoutput()のget_mute()->set_mute()複合操作が"
        "別接続の同時toggleoutput/enableoutput/disableoutputとの間でTOCTOUレース"
        "(lost update)を起こしmute状態がサイレントに食い違う不具合を修正 "
        "(threading.Lockで3ハンドラのmixer書き込み区間を直列化)"
    )
