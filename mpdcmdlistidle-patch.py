# mopidy_mpd/protocol/command_list.py の command_list_end() が、mpdcmdlistnest-patch.py で
# command_list_begin/command_list_ok_begin をネスト再実行しないようにした後も、
# idle/noidle を list 内の1コマンドとして本物のハンドラで再実行してしまう不具合。
# TODO 全項目消化済みのため自走エージェントが command_list.py/dispatcher.py/status.py を
# 再監査して発見した項目。
#
# musicpd.org protocol (command list section) は明記している:
#   "Only synchronous commands can be used in a command list. idle and noidle
#   are not allowed." にも関わらず mopidy_mpd はこれを一切ガードしていない。
#
# 発火条件: クライアントが
#   command_list_begin / idle / command_list_end
# を送る (rmpc 等は通常送らないが、他のMPDクライアント/自作スクリプトが誤って
# 送るとこの経路に入る)。
#
# 実害 (セッションが以後無応答になり、次のコマンドで問答無用切断):
#   1. command_list_end() のリプレイループが command_list_end() 自身とは別の、
#      command_list_index=0 を伴う入れ子の handle_request("idle", ...) を呼ぶ。
#      dispatcher.py の self.command_list_index はディスパッチャインスタンスの
#      単一の属性であり、この入れ子呼び出しが 0 を書き込んだままループ終了後も
#      元の None に戻らない (mpdcmdlistnest-patch.py が修正した
#      command_list_receiving の書き戻り問題と同型の「入れ子 handle_request が
#      呼び出し元の状態を汚染する」構造的欠陥)。
#   2. status.py の idle() は (SUBSYSTEMS 未指定なので) context.subscriptions へ
#      全サブシステムを登録して None を返す。dispatcher.py の _idle_filter は
#      ハンドラ実行後 `if self._is_currently_idle(): return []` により応答を
#      黙って握り潰す (「idle待ち」の間は何も返さないのが正しい実装だが、list内
#      では本来 idle 自体を拒否すべきところ実行されてしまっている)。
#   3. リプレイループを抜けた後、外側の command_list_end 自身の handle_request
#      呼び出しが _idle_filter を通過する際にも同じ
#      `_is_currently_idle()` (context.subscriptions が populate 済み) が True の
#      ため、command_list_end に対する "OK" 応答までもが黙って握り潰される。
#      クライアントは command_list_end に対し一切の応答を受け取れない。
#   4. さらに悪いことに、接続は「idle 中」のまま固着する。クライアントが次に
#      何を送っても (例: status) _idle_filter の
#      `if self._is_currently_idle() and not noidle: ... session.close()` に
#      より ACK エラーすら返さずいきなり TCP 接続を切断してしまう。
#
# 修正: mpdcmdlistnest-patch.py が command_list_begin/command_list_ok_begin に
# 行ったのと同じ手法 (ハンドラ本体を呼ばずリプレイループ内で直接 ACK を返す) を
# idle/noidle にも適用。実MPD (src/client/Process.cxx) が list 内の
# idle/noidle を ACK_ERROR_NOT_LIST (1) で拒否するのに倣い、同じエラーコードで
# 即座に list 処理を打ち切る。ハンドラを一切呼ばないため
# context.subscriptions/self.command_list_index の汚染も起こり得ない。

p = "mopidy_mpd/protocol/command_list.py"
s = open(p).read()

NEW = (
    "    command_list_response = []\n"
    "    for index, command in enumerate(command_list):\n"
    '        command_name = command.split(" ", 1)[0]\n'
    '        if command_name in ("command_list_begin", "command_list_ok_begin"):\n'
    "            response = [\n"
    "                exceptions.MpdUnknownCommand(\n"
    "                    command=command_name, index=index\n"
    "                ).get_mpd_ack()\n"
    "            ]\n"
    '        elif command_name in ("idle", "noidle"):\n'
    "            response = [\n"
    '                f"ACK [{exceptions.MpdAckError.ACK_ERROR_NOT_LIST}@{index}] "\n'
    '                f"{{{command_name}}} not allowed in a command list"\n'
    "            ]\n"
    "        else:\n"
    "            response = context.dispatcher.handle_request(\n"
    "                command, current_command_list_index=index\n"
    "            )\n"
)

if NEW in s:
    print("command_list_end() idle/noidle guard already patched, skip")
else:
    OLD = (
        "    command_list_response = []\n"
        "    for index, command in enumerate(command_list):\n"
        '        command_name = command.split(" ", 1)[0]\n'
        '        if command_name in ("command_list_begin", "command_list_ok_begin"):\n'
        "            response = [\n"
        "                exceptions.MpdUnknownCommand(\n"
        "                    command=command_name, index=index\n"
        "                ).get_mpd_ack()\n"
        "            ]\n"
        "        else:\n"
        "            response = context.dispatcher.handle_request(\n"
        "                command, current_command_list_index=index\n"
        "            )\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched command_list.py: command_list_end()のリプレイループがidle/noidleを"
        "本物のハンドラで再実行しcontext.subscriptions/command_list_indexを汚染して"
        "以後のOK応答喪失+次コマンドでの無条件切断を招く不具合を修正 "
        "(実MPDと同じACK_ERROR_NOT_LISTで即座に打ち切り)"
    )
