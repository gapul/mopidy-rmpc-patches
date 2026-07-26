# mopidy_mpd/protocol/playback.py の volume() が `context.core.mixer.get_volume()`
# (読み取り) と `context.core.mixer.set_volume(new_volume)` (書き込み) という2回の
# **別々の** pykka actor 呼び出しを、その間を保護する仕組み無しに実行している
# TOCTOU レース (read-modify-write, lost update)。TODO/既知の軽微な残課題を全項目
# 消化済みのため自走エージェントが mopidy_mpd のコード品質を再調査して新規発見・
# 追加した項目 (mpdoutputtogglerace-patch.py が audio_output.py の toggleoutput()
# について全く同じ構造のバグ (get_mute()->set_mute()) を既に修正済みだが、
# 同じ context.core.mixer actor に対して構造的に同一の read-modify-write を行う
# playback.py の volume() には対応する保護が一切無く、setvol/getvol は既に
# 対応済みなのに相対指定の volume {CHANGE} だけが取りこぼされている非対称な状態
# だった)。
#
# 実害: mopidy_mpd は各クライアント接続を別OSスレッドの pykka.ThreadingActor
# (MpdSession) として実行する。2本の接続がほぼ同時に `volume +10` を送ると、
# 両方が同じ古い old_volume (例:50) を読んだ後に両方が old_volume+10=60 を
# 書き込んでしまい (lost update)、本来2回の +10 で70になるはずが1回分の変化
# しか反映されない。同じ volume 値を書き換える setvol もこの読み取りウィンドウに
# 割り込めるため、合わせて直列化する必要がある。両クライアントとも OK を受け取る
# ため、サイレントに音量がクライアントの意図と食い違ったまま status の
# volume: フィールドに反映され続ける。
#
# 修正: mpdoutputtogglerace-patch.py と同じ流儀で、playback.py にモジュールレベル
# の threading.Lock() を追加し、volume() の get_volume()->set_volume() の複合操作と
# setvol() の set_volume() 呼び出しを with ブロックで直列化する。いずれも
# SoftwareMixer への軽量な in-process actor 呼び出しのみでバックエンドへの
# 長時間ネットワーク呼び出しを含まないため、mpdurimaprace-patch.py が警戒した
# 「listall事案のような長時間ブロック」の懸念は無い。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

MARKER = "_mixer_volume_lock"
if MARKER in s:
    print("mpdvolumerace already applied to playback.py, skip")
else:
    # 1) import threading
    old_import = "from mopidy.core import PlaybackState\nfrom mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "import threading\n\n"
        "from mopidy.core import PlaybackState\n"
        "from mopidy_mpd import exceptions, protocol, translator\n"
    )
    s = s.replace(old_import, new_import, 1)

    # 2) モジュールレベルLock定義 (getvolハンドラの直前に挿入)
    old_helper = (
        '@protocol.commands.add("getvol")\n'
        "def getvol(context):\n"
    )
    assert s.count(old_helper) == 1, f"old_helper count={s.count(old_helper)}"
    new_helper = (
        "# setvol/volumeの2ハンドラは全クライアント接続間で共有される\n"
        "# context.core.mixerの音量値に対しset(setvolのみ)/get->set(volumeのみ)\n"
        "# という複合操作を行うため、Lockで直列化する(mpdvolumerace-patch.py)。\n"
        "_mixer_volume_lock = threading.Lock()\n"
        "\n"
        "\n"
        '@protocol.commands.add("getvol")\n'
        "def getvol(context):\n"
    )
    s = s.replace(old_helper, new_helper, 1)

    # 3) setvol() 本体
    old_setvol = (
        "    # NOTE: we use INT as clients can pass in +N etc.\n"
        "    value = min(max(0, volume), 100)\n"
        "    success = context.core.mixer.set_volume(value).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    assert s.count(old_setvol) == 1, f"old_setvol count={s.count(old_setvol)}"
    new_setvol = (
        "    # NOTE: we use INT as clients can pass in +N etc.\n"
        "    value = min(max(0, volume), 100)\n"
        "    with _mixer_volume_lock:\n"
        "        success = context.core.mixer.set_volume(value).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    s = s.replace(old_setvol, new_setvol, 1)

    # 4) volume() 本体 (get_volume -> set_volume の複合操作を丸ごとLock区間に)
    old_volume = (
        "    old_volume = context.core.mixer.get_volume().get()\n"
        "    if old_volume is None:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
        "\n"
        "    new_volume = min(max(0, old_volume + change), 100)\n"
        "    success = context.core.mixer.set_volume(new_volume).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    assert s.count(old_volume) == 1, f"old_volume count={s.count(old_volume)}"
    new_volume = (
        "    with _mixer_volume_lock:\n"
        "        old_volume = context.core.mixer.get_volume().get()\n"
        "        if old_volume is None:\n"
        '            raise exceptions.MpdSystemError("problems setting volume")\n'
        "\n"
        "        new_volume = min(max(0, old_volume + change), 100)\n"
        "        success = context.core.mixer.set_volume(new_volume).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    s = s.replace(old_volume, new_volume, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: volume()のget_volume()->set_volume()複合操作が"
        "別接続の同時volume/setvolとの間でTOCTOUレース(lost update)を起こし"
        "音量がサイレントに食い違う不具合を修正 "
        "(threading.Lockでsetvol/volumeのmixer書き込み区間を直列化)"
    )
