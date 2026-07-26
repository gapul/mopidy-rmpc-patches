# mopidy_mpd/protocol/command_list.py の command_list_end() が、command_list_begin()
# ハンドラを実MPDのように一般コマンドテーブルから除外しておらず、ネストされた
# command_list_begin/command_list_ok_begin をキュー内の1コマンドとしてそのまま
# handle_request() 経由で再実行してしまう不具合。TODO 全項目消化済みのため
# 自走エージェントが command_list.py/dispatcher.py を再調査して発見した項目。
#
# 発火条件: クライアントが
#   command_list_begin / command_list_begin / ping / command_list_end
# のように command_list_begin (または command_list_ok_begin) を list 受信中に
# もう一度送る。実MPD (src/client/Process.cxx ProcessCommandList, AllCommands.cxx)
# では command_list_begin は一般コマンドテーブルに存在せず list 実行時は
# 「unknown command」ACKで即座に打ち切られ状態破壊は起きないが、mopidy_mpd は
# `protocol.commands.add("command_list_begin", ...)` で通常コマンドと同じ
# ディスパッチテーブルに登録しているため、command_list_end() のリプレイループが
# `context.dispatcher.handle_request("command_list_begin", ...)` を再帰的に呼ぶと
# 本物のハンドラが実行され `command_list_receiving=True`/`command_list=[]` が
# list 処理の**途中**で書き戻ってしまう。
#
# 実害: dispatcher.py の `_command_list_filter` は `command_list_receiving` が
# True の間、以後のリクエストを一切実行せず黙って `self.command_list` へ
# キューし続ける (`return []`)。command_list_end() 自身はループ開始前に一度
# `command_list_receiving=False` へ戻すだけでループ後に再確認しないため、
# 上記の再実行で True に戻った状態がループ終了後もそのまま残る。結果、
# クライアントには `command_list_end` に対し (エラー無く) "OK" が一つ返るだけで、
# list 内の "ping" 等それ以降のコマンドは実行されず、かつ以後そのTCP接続上で
# 送信するどんなコマンドも `session.py` の `if not response: return` によって
# 一切応答が返らなくなる (静かにハングしたまま固着する。クライアントが
# 偶然もう一度 command_list_end を送らない限り復旧しない)。
#
# 修正: 実MPDと同じ挙動 (list実行中の command_list_begin/command_list_ok_begin は
# 「unknown command」ACKで即座に list 処理を打ち切る) を、command_list_end() の
# リプレイループ内でトークンを見て handle_request() へ渡す前に弾くことで再現する。
# ハンドラ自体を呼ばないため command_list_receiving の書き戻りが起こり得ない。

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
    "        else:\n"
    "            response = context.dispatcher.handle_request(\n"
    "                command, current_command_list_index=index\n"
    "            )\n"
)

if NEW in s:
    print("command_list_end() nested command_list_begin guard already patched, skip")
else:
    OLD = (
        "    command_list_response = []\n"
        "    for index, command in enumerate(command_list):\n"
        "        response = context.dispatcher.handle_request(\n"
        "            command, current_command_list_index=index\n"
        "        )\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched command_list.py: command_list_end()のリプレイループが"
        "ネストされたcommand_list_begin/command_list_ok_beginを本物のハンドラで"
        "再実行しcommand_list_receivingが途中で書き戻ってセッションが無応答に"
        "固着する不具合を修正 (実MPDと同じunknown command ACKで即座に打ち切り)"
    )
