# mopidy_mpd/protocol/command_list.py の command_list_end() が、
# mpdcmdlistnest-patch.py/mpdcmdlistidle-patch.py/mpdalbumartcmdlist-patch.py で
# command_list_begin/command_list_ok_begin・idle/noidle・albumart/readpicture を
# list 内で実行前にガードするようにした後も、そのガード自体がコマンド行の
# 区切り文字としてスペースしか認識せずタブ区切りだとすり抜けてしまう不具合。
# TODO/既知の残課題を全項目消化済みの自走エージェントが、上記3パッチが共通で
# 使っている `command_name = command.split(" ", 1)[0]` を実際のトークナイザ
# (mopidy_mpd/tokenize.py) と突き合わせて再監査し発見・追加した項目。
#
# 実際のコマンド区切り規則は tokenize.py の WORD_RE 自身のコメントが明記している:
#   "Tokens are split by arbitrary amount of spaces or tabs"
# (`(?:\s+|$)` でスペース・タブいずれの空白も区切りとして受理する)。
# ところが command_list.py のガードは素の `command.split(" ", 1)[0]` であり、
# スペースのみを区切りとして扱う。オフラインで実際に確認済み:
#   "idle\tdatabase".split(" ", 1)[0] == "idle\tdatabase"  (guardをすり抜ける)
#   tokenize.split("idle\tdatabase") == ["idle", "database"]  (本物のハンドラはidleとして実行)
# つまりクライアントが
#   command_list_begin
#   idle\tdatabase          (スペースではなくタブ区切り)
#   command_list_end
# を送ると、command_name は "idle\tdatabase" という未知のトークン扱いになり
# ガードの `in ("command_list_begin", "command_list_ok_begin", "idle", "noidle",
# "albumart", "readpicture")` のいずれにもマッチせず else 節へ落ち、
# `context.dispatcher.handle_request("idle\tdatabase", ...)` 経由で
# 本物の idle ハンドラが list 内で実際に実行されてしまう。これは
# mpdcmdlistidle-patch.py が修正した「idle が list 内で実行されると
# context.subscriptions/self.command_list_index が汚染され、以後の OK 応答が
# 黙って握り潰され、次のコマンドで無条件に接続が切断される」不具合そのものが、
# タブ区切りという別経路から再現してしまう (albumart/readpicture・ネストした
# command_list_begin も同様にタブ区切りでガードをすり抜ける)。
#
# 修正: `command.split(" ", 1)[0]` を、スペース・タブいずれの空白の連続でも
# 区切りとして扱う `re.split(r"\s+", command, 1)[0]` に置き換え。空文字列
# ("" .split(" ",1)[0] == "") や1トークンのみの行 ("idle".split(" ",1)[0]
# == "idle") など既存の全ケースで re.split(r"\s+", ..., 1)[0] は元の
# str.split(" ", 1)[0] と同じ結果を返す (空白なし入力は分割されない、空文字列は
# [""] のまま) ため、この変更は純粋な追加防御でスペース区切りの既存動作に対する
# 回帰は無い。

import re

p = "mopidy_mpd/protocol/command_list.py"
s = open(p).read()

OLD = '        command_name = command.split(" ", 1)[0]\n'
NEW = '        command_name = re.split(r"\\s+", command, 1)[0]\n'

if NEW in s:
    print("command_list.py のタブ区切りコマンド名抽出は既にパッチ済み、skip")
else:
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    if "import re\n" not in s:
        IMPORT_OLD = "from mopidy_mpd import exceptions, protocol\n"
        assert s.count(IMPORT_OLD) == 1, f"IMPORT_OLD count={s.count(IMPORT_OLD)}"
        s = s.replace(IMPORT_OLD, "import re\n\n" + IMPORT_OLD, 1)
    open(p, "w").write(s)
    print(
        "patched command_list.py: command_list_end()のidle/noidle/albumart/"
        "readpicture/ネストcommand_list_beginガードがcommand.split(\" \")のため"
        "タブ区切りコマンド行(例: \"idle\\tdatabase\")をすり抜け、list内で本物の"
        "ハンドラが実行されてcontext.subscriptions汚染->以後のOK応答喪失+次コマンド"
        "での無条件切断を招く不具合を修正 (re.split(r\"\\s+\", ...)で実トークナイザと"
        "同じ空白規則に統一)"
    )
