# library.py の browse() `ytmusic:mood` (Mood and Genre Playlists の
# カテゴリ一覧そのもの、「Feel Good」等のフォルダが並ぶ最上位ページ) が、
# `FEmusic_moods_and_genres` レスポンスの各セクションを無条件に
# `gridRenderer` 持ちと決め打ちし、各アイテムを無条件に
# `musicNavigationButtonRenderer` の完全な構造を持つと決め打ちして nav() で
# 取り出す不具合を修正。
#
# ytmoodgenre-patch.py が既に修正した「ytmusic:mood:<params>:<browseId>」
# (個別カテゴリを開いた後の曲/プレイリスト一覧) は同種の想定外構造
# (musicTwoRowItemRenderer が browseEndpoint を持たず単曲ミュージックビデオを
# 指すケース等) に対処済みだが、そのパッチのコメント自身が明記する
# 「1件の異常で for ループ全体・ひいてはページ全体が丸ごと道連れになる」
# という同型のバグが、実は1階層上のこのカテゴリ一覧側(`elif uri ==
# "ytmusic:mood":`)にはまだ残っている。grep で確認した通り
# `FEmusic_moods_and_genres` に対するパッチはこれまで存在しない
# (TODO 全項目消化済みのため自走エージェントが新規発見・追加した項目)。
#
# ytmusicapi.navigation.nav() は none_if_absent=True を渡さない限り
# KeyError/IndexError を送出する (navigation.py 132〜143行で確認)。現状の
# 実装は:
#   for sect in nav(response, SINGLE_COLUMN_TAB + SECTION_LIST):
#       for cat in nav(sect, ["gridRenderer", "items"]):
#           title = nav(cat, [...]).strip()
#           ...
# であり、(a) セクションが gridRenderer を持たない種別(カルーセル等、
# ytmoodgenre-patch.py が下の階層で実際に混在を確認済み)だった場合、
# (b) 1個でも musicNavigationButtonRenderer の構造が想定と異なる項目が
# 混ざった場合、のいずれでも即座に KeyError/IndexError が for ループの
# 外側まで伝播し、それまでに集めていた moods 辞書ごと唯一の try/except
# (browse() 全体を包む) まで巻き込まれて丸ごと失われ、その関数分岐の
# `return [...]` に到達できないまま except に落ちて何も return しない
# (browse() 末尾の共通 `return []` にフォールスルーし、"Mood and Genre
# Playlists" フォルダを開いても空になる)。
#
# 対策: セクション単位では gridRenderer を持たないものは continue で
# 読み飛ばし、カテゴリ単位では1件ごとに try/except で囲んでパース失敗を
# warning ログに留めて次のカテゴリへ継続する (ytmoodgenre-patch.py/
# ytparsegaps-patch.py/ytautoplaylistfix-patch.py と同じ「1件の異常が
# 全体を道連れにしない」流儀)。

p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "YTMusic skipping unparseable mood/genre category"
if MARKER in s:
    print("library.py already patched (ytmoodcategory), skip")
else:
    OLD = """                for sect in nav(response, SINGLE_COLUMN_TAB + SECTION_LIST):
                    for cat in nav(sect, ["gridRenderer", "items"]):
                        title = nav(
                            cat,
                            [
                                "musicNavigationButtonRenderer",
                                "buttonText",
                                "runs",
                                0,
                                "text",
                            ],
                        ).strip()
                        endpnt = nav(
                            cat,
                            [
                                "musicNavigationButtonRenderer",
                                "clickCommand",
                                "browseEndpoint",
                                "browseId",
                            ],
                        )
                        params = nav(
                            cat,
                            [
                                "musicNavigationButtonRenderer",
                                "clickCommand",
                                "browseEndpoint",
                                "params",
                            ],
                        )
                        moods[title] = {
                            "name": title,
                            "uri": "ytmusic:mood:" + params + ":" + endpnt,
                        }
                return ["""
    NEW = """                for sect in nav(response, SINGLE_COLUMN_TAB + SECTION_LIST):
                    if "gridRenderer" not in sect:
                        continue
                    for cat in nav(sect, ["gridRenderer", "items"]):
                        try:
                            title = nav(
                                cat,
                                [
                                    "musicNavigationButtonRenderer",
                                    "buttonText",
                                    "runs",
                                    0,
                                    "text",
                                ],
                            ).strip()
                            endpnt = nav(
                                cat,
                                [
                                    "musicNavigationButtonRenderer",
                                    "clickCommand",
                                    "browseEndpoint",
                                    "browseId",
                                ],
                            )
                            params = nav(
                                cat,
                                [
                                    "musicNavigationButtonRenderer",
                                    "clickCommand",
                                    "browseEndpoint",
                                    "params",
                                ],
                            )
                            moods[title] = {
                                "name": title,
                                "uri": "ytmusic:mood:" + params + ":" + endpnt,
                            }
                        except Exception:
                            logger.warning(
                                "YTMusic skipping unparseable mood/genre category: keys=%s",
                                list(cat.keys()) if isinstance(cat, dict) else type(cat),
                            )
                return ["""
    assert s.count(OLD) == 1, f"expected 1 occurrence of mood/genre category anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: ytmusic:mood (Mood and Genre Playlists の"
        "カテゴリ一覧そのもの) がセクション種別(gridRenderer以外)や"
        "カテゴリ項目の想定外構造をKeyError/IndexErrorで丸ごと道連れにし"
        "フォルダ全体が空になる不具合を修正。gridRenderer以外のセクションは"
        "読み飛ばし、カテゴリ1件のパース失敗はそのカテゴリだけ警告ログで"
        "読み飛ばして残りを継続するようにした"
    )
