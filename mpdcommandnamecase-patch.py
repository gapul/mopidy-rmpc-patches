# mopidy_mpd/tokenize.py の WORD_RE がコマンド名の2文字目以降に大文字を
# 一切許容しない ([a-z][a-z0-9_]*) ため、"sTatus"/"pIng" のように先頭は
# 小文字だが途中に大文字を含む行が、コマンド名として一切トークナイズされず
# split() が MpdUnknownError("Invalid word character") を投げてしまう不具合。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見。
#
# session.py の on_line_received() は行頭1文字のみを
# line[0].islower() and line[0].isalpha() でガードしており (実MPD本体の
# IsLowerAlphaASCII(*line) と一致、この部分は正しい)、2文字目以降は
# 素通しで dispatcher 経由 tokenize.split() に渡る。
#
# 実MPD本体 (gh rawで src/util/Tokenizer.cxx を確認) は
#   valid_word_first_char(ch) = IsAlphaASCII(ch)
#   valid_word_char(ch)       = IsAlphaNumericASCII(ch) || ch == '_'
# であり、IsAlphaASCII/IsAlphaNumericASCII (src/util/CharUtil.hxx) は
# 大文字・小文字どちらも真を返す。つまり実MPDの
# Tokenizer::NextWord() (src/command/AllCommands.cxx の command_process()
# が呼ぶ) は "sTatus" のトークナイズ自体には成功し、その後
# command_checked_lookup() の command_lookup() (strcmpベースの大文字小文字を
# 区別する検索) が一致せず ACK_ERROR_UNKNOWN "unknown command "sTatus""
# を返す。行頭1文字だけを小文字必須とする IsLowerAlphaASCII ゲート自体は
# mopidy_mpd の既存実装と一致しており変更不要。
#
# 現状のmopidy_mpdは WORD_RE 不一致により「コマンド名として認識されない」
# 扱いとなり ACK "Invalid word character" (ACKコード自体は5で一致するが
# メッセージ文言が実MPDと異なる) を返してしまう。TCP 6601実機確認:
# 修正前 "sTatus\n" → `ACK [5@0] {} Invalid word character`
# (mpdtokenizecommandnone-patch.py適用によりcommand=""が明示されている)。
#
# 修正: WORD_RE のコマンド名文字クラスの2文字目以降を [a-zA-Z0-9_] に拡張
# (1文字目は [a-z] のまま、session.py側の既存ガードと実MPDのIsLowerAlphaASCII
# ゲートに合わせて維持)。これにより "sTatus xyz" は
# ("", "sTatus", "xyz") として正常にトークナイズされ、後続の
# protocol.commands.call() の未知コマンド判定 (通常の
# MpdUnknownCommand(command=tokens[0]) 経路) に自然に流れ、
# `ACK [5@0] {sTatus} unknown command "sTatus"` を返すようになる。

p = "mopidy_mpd/tokenize.py"
s = open(p).read()

OLD = "    ([a-z][a-z0-9_]*) # A command name\n"
NEW = "    ([a-z][a-zA-Z0-9_]*) # A command name\n"

if NEW in s:
    print("tokenize.py のWORD_REコマンド名大文字非対応は既にパッチ済み、skip")
else:
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched tokenize.py: WORD_REがコマンド名の2文字目以降に大文字を"
        "許容せず、'sTatus'等が「Invalid word character」に誤分類される"
        "不具合を修正 (2文字目以降を[a-zA-Z0-9_]に拡張、実MPDのTokenizer::"
        "NextWord()のvalid_word_char=IsAlphaNumericASCIIに整合)"
    )
