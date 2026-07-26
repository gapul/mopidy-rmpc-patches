# mopidy_mpd/protocol/connection.py の albumart/readpicture (mpd-patch.py) が
# command_list 内で実行されると、レスポンスの並び順が壊れてしまう不具合。TODO
# 全項目消化済みのため自走エージェントが command_list.py/connection.py を
# 再監査して発見した項目。
#
# 実 MPD (musicpd.org, command list section) は
#   "Only synchronous commands can be used in a command list."
# と明記するのみで albumart/readpicture への直接の言及は無いが、mopidy_mpd の
# command_list_end() (mopidy_mpd/protocol/command_list.py) の実装は各コマンドの
# テキスト応答行を command_list_response という Python list に一旦蓄積し、
# リスト全体の処理が終わった後にまとめてソケットへ書き出す (「レスポンスは
# 全コマンド分をまとめて返す」という仕様通りの実装)。
#
# ところが _mpdart_send() (connection.py, mpd-patch.py が追加) は
# `context.session.connection.queue_send(...)` でバイナリチャンクを
# **その場でソケットへ直接書き込む** ため、この蓄積の仕組みを完全にバイパスする。
# 発火条件・実害 (実際に dev mopidy(6601) へ生ソケットで確認済み):
#   command_list_begin
#   status
#   albumart "ytmusic:track:<id>" 0
#   command_list_end
# を送ると、albumart のバイナリチャンクが command_list_end() 内の実行順で
# status より後に処理されるにも関わらず、status の応答行はまだ
# command_list_response に溜まったまま未送信 (ループ終了後にまとめて送信予定)
# である一方、albumart のバイナリだけは queue_send() により即座にソケットへ
# 書き込まれる。結果、クライアントに届くバイト列は
#   albumart のヘッダ+バイナリ (実行順は2番目) → status のテキスト行 (実行順は
#   1番目、ただしソケット到達順は albumart の後) → 最後に OK
# という、コマンドの実行順序と矛盾した並びになる。sizeフィールドで宣言した
# バイト数だけ読んでから次のコマンド応答をパースするクライアントは、
# この並び順崩壊で確実にデシンクする (これは装飾的な問題ではなくプロトコルの
# フレーミング崩壊)。
#
# 関連する既存パッチ: mpdalbumartrace-patch.py は _MPDART_CACHE の
# TOCTOU/KeyError (並行接続間のロック) を修正したのみで本件とは無関係。
# mpdcmdlistidle-patch.py/mpdcmdlistnest-patch.py は idle/noidle・ネストされた
# command_list_begin の再実行を防ぐ修正で、albumart/readpicture の
# queue_send() 直接書き込みには触れていない。
#
# 修正: mpdcmdlistidle-patch.py が idle/noidle に対して行ったのと全く同じ手法
# (ハンドラ本体を一切呼ばずリプレイループ内で直接 ACK を返す) を
# albumart/readpicture にも適用し、command_list 内での実行自体を拒否する
# (実 MPD の「同期的でないコマンドは list 内禁止」という原則に倣い、同じ
# ACK_ERROR_NOT_LIST で即座に打ち切る)。連携する connection.py 側の変更は不要。

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
    '        elif command_name in ("idle", "noidle", "albumart", "readpicture"):\n'
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
    print("command_list_end() albumart/readpicture guard already patched, skip")
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
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched command_list.py: albumart/readpictureがcommand_list内で"
        "queue_send()による直接ソケット書き込みを行いレスポンスの並び順を"
        "破壊する不具合を修正 (idle/noidleと同様ACK_ERROR_NOT_LISTでlist内実行を拒否)"
    )
