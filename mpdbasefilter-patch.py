# find/search/count/findadd/searchadd/searchaddpl/searchplaylist が共有する
# フィルタ式パーサ `_query_from_mpd_filter_expression()`/旧式パーサ
# `_query_from_mpd_search_parameters()` (music_db.py) が、実MPD (musicpd.org
# protocol、Filters節) で明記されている `(base "DIR")` 疑似タグ (ディレクトリ
# 配下に検索範囲を限定する特殊フィルタ) を一切認識しない不具合。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが(general-purposeサブエージェント
# への調査委任を経て)新規発見した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、gh apiで実際にソース取得し確認) の
# `src/song/Filter.cxx` は `base` を通常のタグ種別 (TAG_NUM_OF_ITEM_TYPES の
# 値域) とは別の特別な擬似タグ (LOCATE_TAG_BASE_TYPE) として認識し、対応する
# `BaseSongFilter` (`src/song/BaseSongFilter.cxx`) は `fold_case`/
# `strip_diacritics` を一切受け取らず常に生のURI文字列を
# `uri_is_child_or_same()` (`src/util/UriRelative.cxx`) でディレクトリ境界
# 判定する:
#   uri_is_child(parent, child):
#     suffix = StringAfterPrefix(child, parent)
#     return suffix && *suffix && (suffix==child || suffix[-1]=='/' || *suffix=='/')
#   uri_is_child_or_same = StringIsEqual(parent, child) || uri_is_child(...)
# つまり `(TAG OP "VALUE")` の一般形 (`_MPD_POSITIVE_OP_KIND` の
# ==/contains/starts_with/=~) とは別枠の、演算子を取らない特殊構文。
#
# 現状の `_query_from_mpd_filter_expression()` は `head.split()` の結果を
# `len(parts) >= 2` でしか処理しないため、`(base "DIR")` は `head` が
# `"base "` → `parts == ["base"]` (長さ1) となり、このブロックを完全に素通り
# (何もせず次の条件へ) する。実害:
#   - `base` 単独指定 → `query` が空のまま `require_positive` チェックに
#     引っかかり `ACK incorrect arguments` (実MPDでは配下の全曲を返すべき
#     正当な問い合わせだが常に拒否される)。
#   - 他のタグ条件と `AND` で併用した場合は `base` 節が完全に無視され、
#     エラーも出さずディレクトリ制限なしの全件から一致する結果を返してしまう
#     (静かな誤り、最も実害が大きい)。
# 旧式引数列パーサ `_query_from_mpd_search_parameters()` (`find base "DIR"`)
# 側も `mapping.get("base")` が常に `None` になるため同じく
# `ACK incorrect arguments` で拒否される。
#
# 本パッチは既存の negatives/positives 後段フィルタ機構 (mpdnegfilter-patch.py/
# mpdfilterkind-patch.py) に `kind="base_dir"` を追加する形で配線する。
# backend の `library.search()`/`get_distinct()` は "base" というフィールドを
# 理解しないため、query 本体 (バックエンドへ丸投げされる辞書) には一切
# 触れず、必ず `__mpd_positives__`/`__mpd_negatives__` 経由のローカル後段
# フィルタとしてのみ効かせる (kind="exact" 等の一致判定は
# `_mpd_negative_field_values(track, "uri")` = `[track.uri]` を流用)。
#
# 既知の制約: mopidy の library は backend 非依存の tag ベース検索で、実MPDの
# ような「music_directory 相対パス」の概念を持たないため、`base` は
# track.uri (backend固有の完全URI) そのものに対するディレクトリ境界一致と
# なる。ローカルファイルbackend (`file:///.../Artist/Album/...`) では実MPDと
# 同じ意味を持つが、mopidy_ytmusic 等の非階層的backend (`ytmusic:track:xxx`)
# では実用上ほぼ意味を持たない(mount/crossfadeと同種の、mopidy core自体が
# 持たない機能に対する割り切り)。BACKLOG.md を `grep -n -i "\bbase\b"` で
# 確認したが `gst-plugins-base` 等の無関係ヒットのみで、`base` フィルタに
# 関する既存パッチとの重複はない。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "_mpd_base_dir_matches"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    # --- 1. 旧式引数列パーサ: `find base "DIR"` ---
    old_legacy = '''    query = {}
    while parameters:
        # TODO: does it matter that this is now case insensitive
        field = mapping.get(parameters.pop(0).lower())
        if not field:
            raise exceptions.MpdArgError("incorrect arguments")
        if not parameters:
            raise ValueError
        value = parameters.pop(0)
        if value.strip():
            query.setdefault(field, []).append(value)
    _mpdfindmultitag_positives = [
        (f, "exact", v[0]) for f, v in query.items() if len(v) == 1
    ]
    if len(query) > 1 and len(_mpdfindmultitag_positives) == len(query):
        query["__mpd_positives__"] = _mpdfindmultitag_positives
    return query
'''
    assert s.count(old_legacy) == 1, f"legacy anchor count={s.count(old_legacy)}"

    new_legacy = '''    query = {}
    _mpdbasefilter_positives = []
    while parameters:
        # TODO: does it matter that this is now case insensitive
        tag = parameters.pop(0).lower()
        if tag == "base":
            # base は通常のタグではなく特殊フィルタなので mapping を通さず、
            # 常にディレクトリ境界一致のpositiveとして積む(下記参照)。
            if not parameters:
                raise ValueError
            _mpdbasefilter_positives.append(("uri", "base_dir", parameters.pop(0)))
            continue
        field = mapping.get(tag)
        if not field:
            raise exceptions.MpdArgError("incorrect arguments")
        if not parameters:
            raise ValueError
        value = parameters.pop(0)
        if value.strip():
            query.setdefault(field, []).append(value)
    _mpdfindmultitag_positives = [
        (f, "exact", v[0]) for f, v in query.items() if len(v) == 1
    ]
    if len(query) > 1 and len(_mpdfindmultitag_positives) == len(query):
        query["__mpd_positives__"] = _mpdfindmultitag_positives
    if _mpdbasefilter_positives:
        query["__mpd_positives__"] = (
            query.get("__mpd_positives__", []) + _mpdbasefilter_positives
        )
    return query
'''
    s = s.replace(old_legacy, new_legacy, 1)

    # --- 2. 新式フィルタ式パーサ: `(base "DIR")` ---
    old_expr_head = '''def _query_from_mpd_filter_expression(expr, mapping, require_positive=True):
    query = {}
    negatives = []
    positives = []
    idx = 0
'''
    assert s.count(old_expr_head) == 1, f"expr_head anchor count={s.count(old_expr_head)}"
    new_expr_head = '''def _query_from_mpd_filter_expression(expr, mapping, require_positive=True):
    query = {}
    negatives = []
    positives = []
    has_base_positive = False
    idx = 0
'''
    s = s.replace(old_expr_head, new_expr_head, 1)

    old_expr_parts = '''        value = "".join(buf)
        idx = j + 1
        parts = head.split()
        if len(parts) >= 2:
            tag = parts[0].strip("\\"'").lstrip("(")
            op = parts[-1]
            field = mapping.get(tag.lower())
            if not field:
                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")
            if not value.strip():
                continue
'''
    assert s.count(old_expr_parts) == 1, f"expr_parts anchor count={s.count(old_expr_parts)}"
    new_expr_parts = '''        value = "".join(buf)
        idx = j + 1
        parts = head.split()
        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() == "base":
            # 実MPD (Filter.cxx LOCATE_TAG_BASE_TYPE/BaseSongFilter) の
            # `(base "DIR")` は演算子を取らない特殊フィルタで、fold_case
            # (find/searchの大小区別切り替え)の対象外に常に大小を区別する。
            if _neg_wrap:
                negatives.append(("uri", "base_dir", value))
            else:
                positives.append(("uri", "base_dir", value))
                has_base_positive = True
            continue
        if len(parts) >= 2:
            tag = parts[0].strip("\\"'").lstrip("(")
            op = parts[-1]
            field = mapping.get(tag.lower())
            if not field:
                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")
            if not value.strip():
                continue
'''
    s = s.replace(old_expr_parts, new_expr_parts, 1)

    old_require_positive = '''    if require_positive and not query:
        raise exceptions.MpdArgError("incorrect arguments")
    if negatives:
        query["__mpd_negatives__"] = negatives
    if positives:
        query["__mpd_positives__"] = positives
    return query
'''
    assert s.count(old_require_positive) == 1, f"require_positive anchor count={s.count(old_require_positive)}"
    new_require_positive = '''    if require_positive and not query and not has_base_positive:
        raise exceptions.MpdArgError("incorrect arguments")
    if negatives:
        query["__mpd_negatives__"] = negatives
    if positives:
        query["__mpd_positives__"] = positives
    return query
'''
    s = s.replace(old_require_positive, new_require_positive, 1)

    # --- 3. 後段フィルタ: negatives/positives へ kind="base_dir" を追加 ---
    old_negatives = '''def _mpd_track_excluded(track, negatives, case_sensitive, strip_diacritics=False):
    """`!=`/`!~`/`!(...)` (negatives) のいずれかにマッチしたら True
    (=結果から除外)。実MPD仕様 (musicpd.org filter syntax): 否定条件は
    タグの全値のいずれかと一致したら除外する。kind は positives と同じ
    exact/contains/starts_with/regex。`find`/`findadd` は大文字小文字を
    区別、`search`/`searchadd`/`searchaddpl`/`count` は区別しない。
    strip_diacritics は search 系のみ (stringnormalization、mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in negatives:
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if strip_diacritics:
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "regex":
'''
    assert s.count(old_negatives) == 1, f"negatives anchor count={s.count(old_negatives)}"
    new_negatives = '''def _mpd_base_dir_matches(base_dir, uri):
    """`(base "DIR")` のディレクトリ境界判定。実MPD
    (src/util/UriRelative.cxx uri_is_child_or_same) と同じロジック:
    base_dir=="" (ルート) は常に一致、それ以外は uri が base_dir と完全一致
    するか、base_dir を前方一致しかつ境界直後が "/" (兄弟ディレクトリの
    誤爆を防ぐ、mpdstickerfinddir-patch.pyと同じ考え方)。fold_case/
    strip_diacritics の対象外で常に大小を区別する。"""
    if not uri:
        return False
    if uri == base_dir:
        return True
    if not uri.startswith(base_dir):
        return False
    if not base_dir:
        return True
    return base_dir.endswith("/") or uri[len(base_dir)] == "/"


def _mpd_track_excluded(track, negatives, case_sensitive, strip_diacritics=False):
    """`!=`/`!~`/`!(...)` (negatives) のいずれかにマッチしたら True
    (=結果から除外)。実MPD仕様 (musicpd.org filter syntax): 否定条件は
    タグの全値のいずれかと一致したら除外する。kind は positives と同じ
    exact/contains/starts_with/regex/base_dir。`find`/`findadd` は大文字
    小文字を区別、`search`/`searchadd`/`searchaddpl`/`count` は区別しない
    (ただし base_dir は常に区別、上記参照)。strip_diacritics は search 系
    のみ (stringnormalization、mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in negatives:
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "base_dir":
            if any(_mpd_base_dir_matches(needle, v) for v in values):
                return True
        elif kind == "regex":
'''
    s = s.replace(old_negatives, new_negatives, 1)

    old_positives = '''def _mpd_track_matches_positives(track, positives, case_sensitive, strip_diacritics=False):
    """(field, kind, needle) の演算子種別付き肯定条件が全て満たされるか
    判定する (AND)。kind: exact(==)/contains/starts_with/regex(=~)。実MPD
    仕様通り、複数値タグはいずれか1つの値が条件を満たせばそのフィールドは
    合格。strip_diacritics は search 系のみ (mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in positives:
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
        if field == "genre" and len(positives) == 1:
            continue  # genre 単独条件のみ backend のベストエフォート結果を信頼する
            # (mopidy_ytmusic 等 Track.genre を常に持たないbackend向け。
            # 他フィールドと併用時はbackendがgenreを見ていないため対象外)
        if field == "track_no" and len(positives) == 1:
            continue  # track_no 単独条件のみ backend のベストエフォート結果を信頼する
            # (mopidy_ytmusic の検索結果 Track は track_no=None 固定のため。
            # 他フィールドと併用時はbackendがtrack_noを見ていないため対象外)
        values = _mpd_negative_field_values(track, field)
        if not values:
            return False
        if strip_diacritics:
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "regex":
'''
    assert s.count(old_positives) == 1, f"positives anchor count={s.count(old_positives)}"
    new_positives = '''def _mpd_track_matches_positives(track, positives, case_sensitive, strip_diacritics=False):
    """(field, kind, needle) の演算子種別付き肯定条件が全て満たされるか
    判定する (AND)。kind: exact(==)/contains/starts_with/regex(=~)/base_dir。
    実MPD仕様通り、複数値タグはいずれか1つの値が条件を満たせばそのフィールドは
    合格。strip_diacritics は search 系のみ (mpdsearchdiacritics-patch.py、
    ただし base_dir は常に対象外、_mpd_base_dir_matches参照)。"""
    for field, kind, needle in positives:
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
        if field == "genre" and len(positives) == 1:
            continue  # genre 単独条件のみ backend のベストエフォート結果を信頼する
            # (mopidy_ytmusic 等 Track.genre を常に持たないbackend向け。
            # 他フィールドと併用時はbackendがgenreを見ていないため対象外)
        if field == "track_no" and len(positives) == 1:
            continue  # track_no 単独条件のみ backend のベストエフォート結果を信頼する
            # (mopidy_ytmusic の検索結果 Track は track_no=None 固定のため。
            # 他フィールドと併用時はbackendがtrack_noを見ていないため対象外)
        values = _mpd_negative_field_values(track, field)
        if not values:
            return False
        if strip_diacritics and kind != "base_dir":
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
'''
    s = s.replace(old_positives, new_positives, 1)

    open(mp, "w").write(s)
    print("patched music_db.py: find/search/count/findadd/searchadd/searchaddpl/"
          "searchplaylist のフィルタに (base \"DIR\") 疑似タグを配線")

    # --- 3.5. current_playlist.py: playlistfind/playlistsearch/searchplaylist が
    # 共有する _pf_matches() は music_db.py の _mpd_track_excluded/
    # _mpd_track_matches_positives とは別実装で、独自の kind 分岐
    # (regex/starts_with/contains/exact) しか持たない。kind="base_dir" を
    # 素通りしてしまう(どのelifにも一致せず無条件で「合格」扱いになる)ため、
    # searchplaylist に base を渡しても静かに無視されてしまう不具合が
    # music_db.py側の修正だけでは残る。_mpd_base_dir_matches を再利用して
    # 同じ判定を追加する。
    cp = "mopidy_mpd/protocol/current_playlist.py"
    s3 = open(cp).read()

    MARKER3 = "_mpd_base_dir_matches"
    if MARKER3 in s3:
        print("current_playlist.py already patched, skip")
    else:
        old_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _mpd_extract_sort_params,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)'''
        assert s3.count(old_cp_import) == 1, f"cp_import anchor count={s3.count(old_cp_import)}"
        new_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _mpd_base_dir_matches,
    _mpd_extract_sort_params,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)'''
        s3 = s3.replace(old_cp_import, new_cp_import, 1)

        old_cp_negatives = '''    for field, kind, needle in negatives:
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics:
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if kind == "regex":
            try:
                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)
            except re.error:
                continue
            if any(pattern.search(v) for v in values):
                return False
        elif kind == "starts_with":
            if strict:
                if any(v.startswith(needle) for v in values):
                    return False
            elif any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if strict:
                if any(needle in v for v in values):
                    return False
            elif any(needle.lower() in v.lower() for v in values):
                return False
        elif strict:
            if needle in values:
                return False
        elif needle.lower() in [v.lower() for v in values]:
            return False
'''
        assert s3.count(old_cp_negatives) == 1, f"cp_negatives anchor count={s3.count(old_cp_negatives)}"
        new_cp_negatives = '''    for field, kind, needle in negatives:
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if kind == "base_dir":
            if any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
            try:
                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)
            except re.error:
                continue
            if any(pattern.search(v) for v in values):
                return False
        elif kind == "starts_with":
            if strict:
                if any(v.startswith(needle) for v in values):
                    return False
            elif any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if strict:
                if any(needle in v for v in values):
                    return False
            elif any(needle.lower() in v.lower() for v in values):
                return False
        elif strict:
            if needle in values:
                return False
        elif needle.lower() in [v.lower() for v in values]:
            return False
'''
        s3 = s3.replace(old_cp_negatives, new_cp_negatives, 1)

        old_cp_positives = '''    for field, kind, needle in positives:
        values = _pf_field_values(track, field)
        if strip_diacritics:
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if not values:
            return False
        if kind == "regex":
            try:
                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if strict:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if strict:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if strict:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
    return True
'''
        assert s3.count(old_cp_positives) == 1, f"cp_positives anchor count={s3.count(old_cp_positives)}"
        new_cp_positives = '''    for field, kind, needle in positives:
        values = _pf_field_values(track, field)
        if strip_diacritics and kind != "base_dir":
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if not values:
            return False
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
            try:
                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if strict:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if strict:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if strict:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
    return True
'''
        s3 = s3.replace(old_cp_positives, new_cp_positives, 1)

        open(cp, "w").write(s3)
        print("patched current_playlist.py: playlistfind/playlistsearch/searchplaylist "
              "が共有する _pf_matches() が (base \"DIR\") を静かに無視する不具合を修正")

    # --- 4. stored_playlists.py: searchplaylist() の独自の空クエリ判定 ---
    # searchplaylist() は _mpd_pop_positives()/_mpd_pop_negatives() で
    # __mpd_positives__/__mpd_negatives__ を query から取り出した「後」に
    # 独自に `if not query:` で空判定している。base は (上記の通り) 意図的に
    # query 本体には一切触れずpositivesのみに積むため、base単独指定だと
    # positivesを取り出した時点でqueryが空になり、この独自チェックに
    # 誤って弾かれてしまう (music_db.py側のrequire_positiveチェックとは別の、
    # searchplaylist固有のもう1つの関門)。
    spl = "mopidy_mpd/protocol/stored_playlists.py"
    s2 = open(spl).read()

    MARKER2 = "not query and not positives"
    if MARKER2 in s2:
        print("stored_playlists.py already patched, skip")
    else:
        old_spl = '''    negatives = _mpd_pop_negatives(query)
    positives = _mpd_pop_positives(query)
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")
'''
        assert s2.count(old_spl) == 1, f"spl anchor count={s2.count(old_spl)}"
        new_spl = '''    negatives = _mpd_pop_negatives(query)
    positives = _mpd_pop_positives(query)
    if not query and not positives:
        raise exceptions.MpdArgError("incorrect arguments")
'''
        s2 = s2.replace(old_spl, new_spl, 1)
        open(spl, "w").write(s2)
        print("patched stored_playlists.py: searchplaylist() が (base \"DIR\") "
              "単独指定を誤って incorrect arguments にする不具合を修正")
