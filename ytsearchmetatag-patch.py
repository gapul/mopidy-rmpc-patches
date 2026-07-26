# mopidy_ytmusic.library.py の search() が query["comment"]/["composer"]/
# ["disc_no"]/["musicbrainz_albumid"]/["musicbrainz_artistid"]/
# ["musicbrainz_trackid"]/["performer"] (MPD の find/search/count
# comment/composer/disc/musicbrainz_*/performer タグ。
# mopidy_mpd/protocol/music_db.py の _LIST_MAPPING/_SEARCH_MAPPING で
# 正式にマップされ、_mpd_positive_field_values()/_mpd_negative_field_values()
# 側の post-filter は既にこれら全フィールドを実装済み) を一切扱わず、
# if/elif チェーンのどの分岐にも一致しないため常に最終 else へ落ち、
# 何もエラーにならないまま `return None` (0件) を返してしまう不具合を発見。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが調査して発見した
# 項目 (ytsearchgenre-patch.py/ytsearchdate-patch.py/ytsearchtrack-patch.py と
# 全く同じ search() 分岐の欠落パターンが、対応漏れの別7フィールド分だけ
# 未対応のまま残っていた)。
#
# 実害: find/search/count/searchcount で composer/performer/comment/disc/
# musicbrainz_* を指定すると常に OK・0件 (find は空応答、count/searchcount
# は songs: 0) になり、対象曲が実在してもヒットしない。ACKエラーにはならない
# サイレントなデータ不整合。
#
# YouTube Music に真のタグ別絞り込み検索APIは無いため完全な等価実装は
# 不可能だが、"any"/"genre"/"date"/"track_no" 分岐と同じベストエフォートの
# テキスト検索 (filter=None) にフォールバックする方が、常に無条件へ0件を
# 返す現状より明らかに有用。7フィールドをまとめて1つの分岐で処理する
# (指定された全フィールドの値を連結して検索語にする、"any" 分岐で複数タグ
# 指定時に単純結合する既存の挙動と同じ方針)。
#
# 対策: "any"/"genre"/"date"/"track_no" 分岐と同じ実装で、7フィールドを
# まとめて扱う分岐を最終 else (uri 分岐) の手前に追加する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

_META_FIELDS = (
    "composer",
    "performer",
    "comment",
    "disc_no",
    "musicbrainz_albumid",
    "musicbrainz_artistid",
    "musicbrainz_trackid",
)

MARKER = "_META_SEARCH_FIELDS = frozenset("
if MARKER in s:
    print("library.py already patched (search meta-tag branch), skip")
else:
    ANCHOR = '        elif "uri" in query:\n'
    assert s.count(ANCHOR) == 1, f"expected 1 occurrence of uri-branch anchor (got {s.count(ANCHOR)})"
    fields_tuple = repr(_META_FIELDS)
    NEW_BRANCH = (
        f"        elif _META_SEARCH_FIELDS.intersection(query):\n"
        f"            terms = []\n"
        f"            for _field in _META_SEARCH_FIELDS:\n"
        f"                if _field in query:\n"
        f"                    terms += query[_field]\n"
        f"            try:\n"
        f"                res = self.backend.api.search(\n"
        f'                    " ".join(terms), filter=None\n'
        f"                )\n"
        f"                results = self.parseSearch(res)\n"
        f"            except Exception:\n"
        f"                logger.exception(\n"
        f'                    \'YTMusic search failed for query "%s"\',\n'
        f'                    " ".join(terms),\n'
        f"                )\n"
    )
    s = s.replace(ANCHOR, NEW_BRANCH + ANCHOR, 1)

    # モジュールレベルの定数として検索対象フィールド集合を定義 (search()冒頭の
    # importの直後に配置)。フィールド一覧を単一箇所に保つことで新規追加時の
    # 分岐コード側とのずれを防ぐ。
    IMPORT_ANCHOR = "from mopidy.models import"
    assert s.count(IMPORT_ANCHOR) >= 1, "expected models import anchor for constant placement"
    first_import_line_end = s.index("\n", s.index(IMPORT_ANCHOR)) + 1
    CONST_DEF = (
        f"\n_META_SEARCH_FIELDS = frozenset({fields_tuple})\n"
    )
    s = s[:first_import_line_end] + CONST_DEF + s[first_import_line_end:]

    open(p, "w").write(s)
    print(
        "patched library.py: search()にcomposer/performer/comment/disc_no/"
        "musicbrainz_*分岐を追加 (any/genre/date/track_no分岐と同じベストエフォート"
        "のテキスト検索、従来は最終elseに落ちて常に0件だった)"
    )
