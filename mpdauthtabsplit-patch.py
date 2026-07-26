# mopidy_mpd/dispatcher.py の MpdDispatcher._authenticate_filter() が、
# パスワード認証有効時 (mopidy.conf の [mpd] password 設定時) に
# 未認証コマンドかどうかを判定するためのコマンド名抽出で
# `request.split(" ")[0]` という素のスペース区切りを使っており、
# タブ区切りのコマンド行だとすり抜けてしまう不具合。
# TODO/既知の残課題を全項目消化済みの自走エージェントが、直前に
# mpdcmdlisttabsplit-patch.py で修正した command_list.py の
# `command.split(" ", 1)[0]` と全く同じパターンを、実トークナイザ
# (mopidy_mpd/tokenize.py の WORD_RE、コメントに明記の通り
# "Tokens are split by arbitrary amount of spaces or tabs") と
# 突き合わせて dispatcher.py 内の他の split(" ") 使用箇所も再監査し
# 発見・追加した項目 (grep で dispatcher.py 内のこの1箇所のみと確認)。
#
# 実際に確認済み:
#   "password\tXXX".split(" ")[0] == "password\tXXX"
#   (protocol.commands.handlers.get() に未知のキーとして渡りNoneを返す)
#   tokenize.split("password\tXXX") == ["password", "XXX"]
#   (本物のパスワード認証ハンドラは "password" として正しく呼ばれるべき)
# つまりパスワード認証が有効な構成で、未認証の接続がタブ区切りで
# `password\tXXX` (認証不要コマンドのはずの password) を送ると、
# command_name が "password\tXXX" という未知のトークン扱いになり
# `protocol.commands.handlers.get(command_name)` が None を返し、
# auth_required=False の判定に到達できず常に MpdPermissionError
# (ACK "you don't have permission for ...") で拒否される。同様に
# close/ping/commands/notcommands 等の他の auth_required=False
# コマンドも同じ経路ですり抜けを阻害される。つまりパスワード認証設定時、
# タブ区切りでコマンドを送るクライアントは認証コマンド自体を通せず
# 永久に未認証のまま拒否され続ける。
#
# 修正: mpdcmdlisttabsplit-patch.py と同じ流儀で、
# `request.split(" ")[0]` を `re.split(r"\s+", request, 1)[0]` に
# 置き換え (スペース区切り・空白なし・空文字列いずれも元の
# str.split(" ")[0] と同じ結果を返すため純粋な追加防御で回帰なし)。
# dispatcher.py は冒頭で既に `import re` 済みのため import 追加は不要。
#
# 2026-07-25 追記: 冪等性チェックを `if NEW in s: skip` から
# `if OLD not in s: skip` に変更。理由: mpdauthtabsplit-patch.py より
# nix/lib/mopidy-env.nix で先に登録されている mpdcmdlistidleclose-patch.py が
# 同じ dispatcher.py の別関数 (_command_list_filter()) へ、全く同一の
# リテラル行 `            command_name = re.split(r"\s+", request, 1)[0]\n`
# を偶然挿入するため、旧来の `if NEW in s` は _authenticate_filter() 自体を
# 一度も書き換えないまま常に「既にパッチ済み」と誤判定してこのパッチを
# 無条件でスキップしていた (実機の dispatcher.py で
# _authenticate_filter() 内が request.split(" ")[0] のまま残っていることを
# 確認して発覚)。OLD は _authenticate_filter() 内にのみ出現する行なので
# `if OLD not in s` の方が本来の「このパッチが指す1箇所を既に書き換えたか」
# を正確に判定できる。

p = "mopidy_mpd/dispatcher.py"
s = open(p).read()

OLD = '            command_name = request.split(" ")[0]\n'
NEW = '            command_name = re.split(r"\\s+", request, 1)[0]\n'

if OLD not in s:
    print("dispatcher.py のタブ区切りコマンド名抽出(認証フィルタ)は既にパッチ済み、skip")
else:
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    assert "import re\n" in s, "dispatcher.py に import re が見つからない"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched dispatcher.py: MpdDispatcher._authenticate_filter()の"
        "command_name抽出がrequest.split(\" \")のためタブ区切りコマンド行"
        "(例: \"password\\tXXX\")をすり抜け、パスワード認証有効時に"
        "auth_required=False判定に到達できず認証コマンド自体が常に"
        "ACK permissionで拒否される不具合を修正 "
        "(re.split(r\"\\s+\", ...)で実トークナイザと同じ空白規則に統一)"
    )
