# mopidy_ytmusic.library.py の search() が query["genre"] (MPD の
# find/search/count "genre" タグ、mopidy_mpd/protocol/music_db.py の
# _LIST_MAPPING/_SEARCH_MAPPING で "genre" -> "genre" と正式にマップされ、
# find/search/count/list genre 全てがこのフィールド名でバックエンドへ渡す) を
# 一切扱わず、if/elif チェーンのどの分岐にも一致しないため常に最終 else へ落ち、
# 何もエラーにならないまま `return None` (0件) を返してしまう不具合を発見。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが調査して発見した
# 項目 (ytsearchuri-patch.py と同じ search() 分岐の欠落パターン)。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc-mpd/src/filter.rs の `Tag` enum に `Genre` が Any/Artist/AlbumArtist/
# Album/Title/File と並ぶ組み込みバリアントとして定義されており、検索ペインの
# タグ選択で Genre を選んでクエリを打つと実際に `find genre "..."` 相当の
# MPD コマンドが送信されることを確認した。YouTube Music に真のジャンル絞り込み
# 検索APIは無いため完全な等価実装は不可能だが、"any" 分岐と同じベストエフォート
# のテキスト検索 (filter=None) にフォールバックする方が、常に無条件へ0件を返す
# 現状より明らかに有用。
#
# 対策: "any" 分岐と同じ実装で "genre" 分岐を最終 else の手前に追加する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif "genre" in query:'
if MARKER in s:
    print("library.py already patched (search genre branch), skip")
else:
    ANCHOR = '        elif "uri" in query:\n'
    assert s.count(ANCHOR) == 1, f"expected 1 occurrence of uri-branch anchor (got {s.count(ANCHOR)})"
    NEW_BRANCH = (
        '        elif "genre" in query:\n'
        '            try:\n'
        '                res = self.backend.api.search(\n'
        '                    " ".join(query["genre"]), filter=None\n'
        '                )\n'
        '                results = self.parseSearch(res)\n'
        '            except Exception:\n'
        '                logger.exception(\n'
        '                    \'YTMusic search failed for query "genre"="%s"\',\n'
        '                    " ".join(query["genre"]),\n'
        '                )\n'
    )
    s = s.replace(ANCHOR, NEW_BRANCH + ANCHOR, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: search()にgenre分岐を追加 (any分岐と同じ"
        "ベストエフォートのテキスト検索、従来は最終elseに落ちて常に0件だった)"
    )
