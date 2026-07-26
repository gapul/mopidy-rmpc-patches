# `outputset {ID} {NAME} {VALUE}` (MPD 0.24+の出力ランタイム属性設定コマンド)が
# mopidy_mpd 3.3.0に丸ごと欠落しており常に `ACK unknown command "outputset"` に
# なっていた不具合を修正。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見・再検討。
#
# mpdplaylistlength-patch.py の調査時(mpd.readthedocs.io protocol リファレンス
# 全文照合)で見つかった未実装6件のうち、outputsetは「mopidyのaudio output抽象に
# runtime attributeの概念が無い」という理由で見送られていた。しかしこの理由は
# 実MPD本体側でも同じ結論(属性を持たない出力プラグインは常に拒否)であり、
# コマンド自体を未実装のままにする理由にはならないと判明:
# gh rawでsrc/command/OutputCommands.cxx handle_outputset()を確認すると、
# `CheckPartitionOutput(partition, i)`でID有効性/パーティション所属を検証した後
# `IsValidAttributeName(name)`(英数字と`_`のみ、空文字不可)を検証し、
# 最後に`ao.SetAttribute(name, value)`を呼ぶ。src/output/Interface.cxxの基底
# 実装(属性を一切持たないプラグインが継承するデフォルト)は
# `throw std::invalid_argument("Unsupported attribute")`のみで、これは
# CommandError.cxxのToAck()でACK_ERROR_ARG(2)にマップされる(std::invalid_argument
# →2は既にmpdstickersongvalidate-patch.py/mpdstickersongnoexist-patch.py等で
# 確認済みの変換規則)。つまり実MPDの「属性を持たない出力」に対する
# `outputset`の正しい応答は「常にACK 2 Unsupported attribute」であり、
# mopidy_mpdの単一仮想出力("Mute", id 0)でも同じ応答形を再現できる。
# ID/パーティション検証はsrc/output/OutputCommand.cxxのCheckPartitionOutput()
# 実装を確認: idx>=出力数はACK_ERROR_NO_EXIST(50)"No such audio output"、
# 所属パーティション不一致もACK_ERROR_NO_EXIST(50)(メッセージは実MPDでは
# "Audio output not in this partition"と別だが、mpdoutputpartition-patch.py
# が導入した既存のenableoutput/disableoutput/toggleoutputも両ケースを
# 同一メッセージ"No such audio output"に統合済みのため、本パッチもその
# 既存の簡略化方針を踏襲し新たな不整合を持ち込まない)。
#
# 実装: audio_output.pyに`outputset(context, outputid, name, value)`ハンドラを
# 新規追加。既存の`_mpdoutputpartition_owned(context)`(mpdoutputpartition-patch.py
# 導入)をそのまま再利用してID/所属チェックとし、有効なら
# `IsValidAttributeName`相当(`^[A-Za-z0-9_]+$`)で属性名を検証してから
# 常に`MpdArgError("Unsupported attribute")`を送出する(実際には何も
# 変更しない、mpdcrossfade-patch.py等が確立済みの
# "プロトコル層のみ・機能的効果ゼロ"パターンと同種)。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): `outputset 0 foo bar` ->
# 修正前 `ACK [5@0] {} unknown command "outputset"` -> 修正後
# `ACK [2@0] {outputset} Unsupported attribute`。`outputset 1 foo bar`(存在しない
# ID) -> `ACK [50@0] {outputset} No such audio output`。`outputset 0 "bad!" bar`
# (不正な属性名) -> `ACK [2@0] {outputset} Illegal attribute name`。引数不足
# (`outputset 0 foo`) -> `ACK [2@0] {outputset} wrong number of arguments for
# "outputset"`(既存の汎用arg-count検証が自動対応、追加コード不要)。回帰確認:
# `outputs`/`enableoutput 0`/`disableoutput 0`/`toggleoutput 0`/`status`は
# 修正前後で無変更。mopidy.logに新規ERROR/Traceback 0件。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

MARKER = 'protocol.commands.add("outputset"'
if MARKER in s:
    print("audio_output.py already has outputset, skip")
else:
    anchor = (
        '@protocol.commands.add("outputs")\n'
        "def outputs(context):\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    new_handler = (
        "_MPDOUTPUTSET_NAME_RE = re.compile(r\"^[A-Za-z0-9_]+$\")\n"
        "\n"
        "\n"
        '@protocol.commands.add("outputset", outputid=protocol.UINT)\n'
        "def outputset(context, outputid, name, value):\n"
        '    """\n'
        "    *musicpd.org, audio output section:*\n"
        "\n"
        "        ``outputset {ID} {NAME} {VALUE}``\n"
        "\n"
        "        Set a runtime attribute. These are specific to the output\n"
        "        plugin, and supported values are usually printed in the\n"
        "        outputs response.\n"
        "\n"
        "    .. versionadded:: 0.24\n"
        "        New in MPD protocol version 0.24\n"
        '    """\n'
        "    if not (outputid == 0 and _mpdoutputpartition_owned(context)):\n"
        '        raise exceptions.MpdNoExistError("No such audio output")\n'
        "    if not _MPDOUTPUTSET_NAME_RE.match(name):\n"
        '        raise exceptions.MpdArgError("Illegal attribute name")\n'
        '    raise exceptions.MpdArgError("Unsupported attribute")\n'
        "\n"
        "\n"
        + anchor
    )
    s = s.replace(anchor, new_handler, 1)

    old_import = "import threading\n\nfrom mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = "import re\nimport threading\n\nfrom mopidy_mpd import exceptions, protocol, translator\n"
    s = s.replace(old_import, new_import, 1)

    open(p, "w").write(s)
    print("patched audio_output.py: outputset ハンドラを追加(常にUnsupported attribute)")
