# mopidy_ytmusic.library.py の search() が query["track_no"] (MPD の
# find/search/count "track" タグ、mopidy_mpd/protocol/music_db.py の
# _LIST_MAPPING/_SEARCH_MAPPING で "track" -> "track_no" と正式にマップされる)
# を一切扱わず、if/elif チェーンのどの分岐にも一致しないため常に最終 else へ落ち、
# 何もエラーにならないまま `return None` (0件) を返してしまう不具合を発見。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントがリサーチ
# サブエージェントに委任して発見した項目 (ytsearchgenre-patch.py/
# ytsearchdate-patch.py と同じ search() 分岐の欠落パターン)。
#
# genre/date と異なり track_no は実データが入る唯一のケース: albumToTracks()
# (library.py) が `for index, song in enumerate(album["tracks"], start=1): ...
# track_no=index` としてアルバムブラウズ/lookup時に self.TRACKS へ妥当な
# トラック番号を格納する (他の生成箇所 — playlistToTracks/uploadAlbumToTracks等
# — は track_no=None 固定)。つまり「データは存在するのに search() 自体が
# track_no フィールドを一切見ずに常に0件を返す」ケースであり、genre/date
# (元々データが空で結果的に0件が妥当) より実害が大きい。
#
# YouTube Music に真のトラック番号絞り込み検索APIは無いため完全な等価実装は
# 不可能だが、"any"/"genre"/"date" 分岐と同じベストエフォートのテキスト検索
# (filter=None) にフォールバックする方が、常に無条件へ0件を返す現状より
# 明らかに有用。
#
# 対策: "date" 分岐と同じ実装で "track_no" 分岐を uri 分岐の手前に追加する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif "track_no" in query:'
if MARKER in s:
    print("library.py already patched (search track_no branch), skip")
else:
    ANCHOR = '        elif "uri" in query:\n'
    assert s.count(ANCHOR) == 1, f"expected 1 occurrence of uri-branch anchor (got {s.count(ANCHOR)})"
    NEW_BRANCH = (
        '        elif "track_no" in query:\n'
        '            try:\n'
        '                res = self.backend.api.search(\n'
        '                    " ".join(query["track_no"]), filter=None\n'
        '                )\n'
        '                results = self.parseSearch(res)\n'
        '            except Exception:\n'
        '                logger.exception(\n'
        '                    \'YTMusic search failed for query "track_no"="%s"\',\n'
        '                    " ".join(query["track_no"]),\n'
        '                )\n'
    )
    s = s.replace(ANCHOR, NEW_BRANCH + ANCHOR, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: search()にtrack_no分岐を追加 (any/genre/date分岐と"
        "同じベストエフォートのテキスト検索、従来は最終elseに落ちて常に0件だった)"
    )
