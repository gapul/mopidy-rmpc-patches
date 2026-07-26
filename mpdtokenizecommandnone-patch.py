# mopidy_mpd/tokenize.py の split() が、コマンド名自体のトークナイズに
# 失敗した場合 (先頭が[a-z][a-z0-9_]*にマッチしない、または行頭に
# 空白がある) に raise する MpdUnknownError("Invalid word character")/
# ("Letter expected") がどちらも command 引数を省略しており、
# exceptions.MpdAckError.__init__() のデフォルト command=None のまま
# 例外が生成される不具合。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが (general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# dispatcher.py の _call_handler() は
#   tokens = tokenize.split(request)   # ← try節の外、ここで例外送出
#   try:
#       return protocol.commands.call(tokens, context=self.context)
#   except exceptions.MpdAckError as exc:
#       if exc.command is None:
#           exc.command = tokens[0]    # tokenize.split失敗時はここを通らない
#       raise
# という構造で、tokens[0]でcommand未設定分を後から補うのはコマンド名の
# トークナイズ自体は成功した後続エラー(引数エラー等)専用の救済コードで
# あり、tokenize.split()自体が投げた例外はこの補完を一切通らない。結果、
# MpdAckError.get_mpd_ack() の f"{{{self.command}}}" がNoneをそのまま
# 文字列化し、ACK応答に文字通り "{None}" というPython内部表現が漏れる。
#
# 実MPD本体(gh rawでsrc/client/Response.hxx `const char *command = "";`
# [コマンド名判明前のデフォルトは空文字列]、src/client/Response.cxx
# Error() `Fmt("ACK [{}@{}] {{{}}} ", code, list_index, command)` を確認)
# はコマンド名判明前のトークナイズエラーでも command は空文字列のまま
# であり、"{None}" のような内部実装の漏洩は起きない。mopidy_mpd自身も
# 空行 (No command given) の場合は MpdNoCommand.__init__ が
# kwargs["command"] = "" を明示注入しており "{}" と正しく表示される
# (同じ関数内、同種のトークナイズ前エラー) ため、この2箇所だけが
# その既存の慣習から外れている。
#
# 実機確認 (TCP 6601): "sTaTus\n" (大文字始まりだが行頭CSRFガード
# `line[0].islower()` は先頭が小文字なslashを通過する2文字目以降の
# 不一致パターンでのみ再現、実際には非WORD_RE文字を含む行、例えば
# "sta$tus\n" や 行頭空白 " status\n" で再現) を送ると修正前は
# `ACK [5@0] {None} Invalid word character` / `ACK [5@0] {None} Letter expected`
# となっていたのが、修正後は `ACK [5@0] {} Invalid word character` /
# `ACK [5@0] {} Letter expected` になる。BACKLOG.md全体を
# "{None}"/"command=None"/"Invalid word character"/"Letter expected" で
# 検索したが既出無し。
#
# 修正: tokenize.py の該当2箇所の raise に command="" を明示指定
# (MpdNoCommand と同じ流儀)。tokenize.split()の呼び出し元
# (dispatcher.py._call_handler) 側は変更不要。

p = "mopidy_mpd/tokenize.py"
s = open(p).read()

OLD1 = '        raise exceptions.MpdUnknownError("Invalid word character")\n'
NEW1 = '        raise exceptions.MpdUnknownError("Invalid word character", command="")\n'

OLD2 = '        raise exceptions.MpdUnknownError("Letter expected")\n'
NEW2 = '        raise exceptions.MpdUnknownError("Letter expected", command="")\n'

if NEW1 in s and NEW2 in s:
    print("tokenize.py のコマンド名トークナイズ失敗時のcommand=None漏れは既にパッチ済み、skip")
else:
    assert s.count(OLD1) == 1, f"OLD1 count={s.count(OLD1)}"
    assert s.count(OLD2) == 1, f"OLD2 count={s.count(OLD2)}"
    s = s.replace(OLD1, NEW1, 1)
    s = s.replace(OLD2, NEW2, 1)
    open(p, "w").write(s)
    print(
        "patched tokenize.py: split()がコマンド名トークナイズ失敗時に"
        "raiseするMpdUnknownError('Invalid word character'/'Letter expected')"
        "がcommand引数省略によりcommand=Noneのまま生成され、ACK応答に"
        "文字通り\"{None}\"が漏れる不具合を修正 (command=\"\"を明示指定、"
        "MpdNoCommandと同じ流儀)"
    )
