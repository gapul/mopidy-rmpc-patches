# mopidy_ytmusic.library.py の search() が query["date"] (MPD の
# find/search/count "date" タグ。mopidy_mpd/protocol/music_db.py の
# _LIST_MAPPING/_SEARCH_MAPPING で "date" -> "date" と正式にマップされ、
# find() 自身のdocstringが "also uses the search type \"date\"." と明記する
# 公式に想定された検索タイプ) を一切扱わず、if/elif チェーンのどの分岐にも
# 一致しないため常に最終 else へ落ち、何もエラーにならないまま
# `return None` (0件) を返してしまう不具合を発見。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが調査して発見した
# 項目 (ytsearchgenre-patch.py/ytsearchuri-patch.py と同じ search() 分岐の
# 欠落パターン。同ファイルの _mpd_negative_field_values()/_mpd_positive_field_values()
# 相当の post-filter 側は "date" フィールドを既にサポートしているため、backend
# 側さえ結果を返せば絞り込み自体は正しく機能する)。
#
# YouTube Music に真の年代絞り込み検索APIは無いため完全な等価実装は不可能だが、
# "any"/"genre" 分岐と同じベストエフォートのテキスト検索 (filter=None) に
# フォールバックする方が、常に無条件へ0件を返す現状より明らかに有用
# (rmpc の Tag enum は Genre 同様 Date も持たないため date 単体検索を rmpc
# 自体は送らないが、ncmpcpp 等 MPD 公式クライアントは find/list date を送る)。
#
# 対策: "genre" 分岐と同じ実装で "date" 分岐を uri 分岐の手前に追加する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif "date" in query:'
if MARKER in s:
    print("library.py already patched (search date branch), skip")
else:
    ANCHOR = '        elif "uri" in query:\n'
    assert s.count(ANCHOR) == 1, f"expected 1 occurrence of uri-branch anchor (got {s.count(ANCHOR)})"
    NEW_BRANCH = (
        '        elif "date" in query:\n'
        '            try:\n'
        '                res = self.backend.api.search(\n'
        '                    " ".join(query["date"]), filter=None\n'
        '                )\n'
        '                results = self.parseSearch(res)\n'
        '            except Exception:\n'
        '                logger.exception(\n'
        '                    \'YTMusic search failed for query "date"="%s"\',\n'
        '                    " ".join(query["date"]),\n'
        '                )\n'
    )
    s = s.replace(ANCHOR, NEW_BRANCH + ANCHOR, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: search()にdate分岐を追加 (any/genre分岐と同じ"
        "ベストエフォートのテキスト検索、従来は最終elseに落ちて常に0件だった)"
    )
