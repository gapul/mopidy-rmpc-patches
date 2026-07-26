# mopidy-mpd 3.3.0 の `outputs`/`enableoutput`/`disableoutput`/`toggleoutput`
# (audio_output.py) は mpdpartition-patch.py が追加した translator の
# パーティション所属ストア (_output_partition, "Mute" の所属先) を一切参照せず、
# どのパーティションから呼んでも常に同じ応答 (plugin: "mopidy", 実際のmute状態) を
# 返す。TODO 全項目消化済みのため自走エージェントが rmpc 本体 (mierak/rmpc) を
# 実際にcloneして調査したところ、rmpc/src/shared/mpd_client_ext.rs の
# `list_partitioned_outputs()` が「default パーティションの `outputs` 応答で
# `plugin == "dummy"` の出力は他パーティション所属 (PartitionedOutputKind::
# OtherPartition)、それ以外は自パーティション所属 (CurrentPartition)」という
# 実MPD仕様の契約 (コメント: "MPD lists all outputs only on the default
# partition ... We also have to list outputs on the current partition to
# find out which output is actually enabled on the current partition") を
# 前提にしており、rmpc/src/ui/modals/outputs.rs の Outputs モーダル
# (`GlobalAction::ShowOutputs`、実キーバインド可能) がこの分類で
# move_output (OtherPartition行) / toggle_output (CurrentPartition行) を
# 出し分けている実害のあるギャップと判明。
#
# 実害: `newpartition`→`moveoutput` で "Mute" を別パーティションへ移した後、
# 元のパーティション (default 含む) から Outputs モーダルを開いても
# `outputs` が常に plugin: "mopidy" (dummyでない) を返すため、実際には
# 所属していないパーティションでも "Mute" が CurrentPartition (自分のものとして
# 有効/無効操作可能) のまま表示され続け、rmpc の「別パーティションへ移動する」
# UI (OtherPartition行のみ move_output を送る) が機能しない。
#
# 実装: mpdpartition-patch.py の translator.output_partition_get("Mute") と
# translator.partition_get(id(context.session)) を突き合わせ、現在のセッションの
# パーティションが "Mute" の所属パーティションと一致しない場合は
# plugin: "dummy" / outputenabled: 0 を返す (実MPDの他パーティション所属出力の
# 表現を模す)。enableoutput/disableoutput/toggleoutput も同様に不一致なら
# 実MPD同様 "No such audio output" とする (自パーティションに属さない出力は
# 操作不可)。mpdpartition-patch.py 未適用 (partition機能そのものが無い) 状態は
# 想定しない (mopidy-env.nix で常に先に適用される)。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

MARKER = "_mpdoutputpartition_owned"
if MARKER in s:
    print("audio_output.py already patched for partition-aware outputs, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "from mopidy_mpd import exceptions, protocol, translator\n"
        "\n"
        "\n"
        "def _mpdoutputpartition_owned(context):\n"
        '    return translator.output_partition_get("Mute") == translator.partition_get(\n'
        "        id(context.session)\n"
        "    )\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_disable = (
        "    if outputid == 0:\n"
        "        success = context.core.mixer.set_mute(False).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems disabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_disable) == 1, f"old_disable count={s.count(old_disable)}"
    new_disable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        success = context.core.mixer.set_mute(False).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems disabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_disable, new_disable, 1)

    old_enable = (
        "    if outputid == 0:\n"
        "        success = context.core.mixer.set_mute(True).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems enabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_enable) == 1, f"old_enable count={s.count(old_enable)}"
    new_enable = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        success = context.core.mixer.set_mute(True).get()\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems enabling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_enable, new_enable, 1)

    old_toggle = (
        "    if outputid == 0:\n"
        "        mute_status = context.core.mixer.get_mute().get()\n"
        "        success = context.core.mixer.set_mute(not mute_status)\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems toggling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    assert s.count(old_toggle) == 1, f"old_toggle count={s.count(old_toggle)}"
    new_toggle = (
        "    if outputid == 0 and _mpdoutputpartition_owned(context):\n"
        "        mute_status = context.core.mixer.get_mute().get()\n"
        "        success = context.core.mixer.set_mute(not mute_status)\n"
        "        if not success:\n"
        '            raise exceptions.MpdSystemError("problems toggling output")\n'
        "    else:\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
    )
    s = s.replace(old_toggle, new_toggle, 1)

    old_outputs = (
        "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
        "    return [\n"
        '        ("outputid", 0),\n'
        '        ("outputname", "Mute"),\n'
        '        ("plugin", "mopidy"),\n'
        '        ("outputenabled", muted),\n'
        "    ]\n"
    )
    assert s.count(old_outputs) == 1, f"old_outputs count={s.count(old_outputs)}"
    new_outputs = (
        "    if not _mpdoutputpartition_owned(context):\n"
        "        return [\n"
        '            ("outputid", 0),\n'
        '            ("outputname", "Mute"),\n'
        '            ("plugin", "dummy"),\n'
        '            ("outputenabled", 0),\n'
        "        ]\n"
        "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
        "    return [\n"
        '        ("outputid", 0),\n'
        '        ("outputname", "Mute"),\n'
        '        ("plugin", "mopidy"),\n'
        '        ("outputenabled", muted),\n'
        "    ]\n"
    )
    s = s.replace(old_outputs, new_outputs, 1)

    open(p, "w").write(s)
    print(
        "patched audio_output.py: outputs/enableoutput/disableoutput/toggleoutput を"
        " パーティション所属 (translator.output_partition_get) を考慮するよう修正"
    )
