# mpdstringnorm-patch.py が実装した `stringnormalization enable strip_diacritics`
# (MPD 0.25+) が、`search`/`searchadd`/`searchaddpl`/`searchcount` のうち
# フィルタ式 (`(TAG OP "VALUE")`、mpdnegfilter-patch.py/mpdfilterkind-patch.py が
# 実装した否定/演算子種別付き肯定条件) を使った検索には一切効かない不具合。
#
# mpdstringnorm-patch.py 自身のコメントは当時「search/find/count/list は全て
# context.core.library.search() へのバックエンド丸投げで、ローカルな文字列比較を
# 一切行わないため diacritics ストリップを適用する対象コードが存在しない
# (mount/crossfade と同種の割り切り)」と明記していた。だがその後の
# mpdnegfilter-patch.py/mpdfilterkind-patch.py は `_mpd_filter_negatives`/
# `_mpd_filter_positives` (music_db.py) という「バックエンドから取得済みの
# Track に対するローカルな後段フィルタ」を追加しており、mpdnegfilter-patch.py の
# BACKLOG 記述自身も「find/search/findadd/searchadd/searchaddpl/count は
# ローカルデータへの後処理のため、mount/crossfade/stringnormalization-on-search の
# ような『バックエンド丸投げのため対応不能』という制約が本質的に存在しない」と
# 明記していた。つまり strip_diacritics を配線する余地がすでに存在していたにも
# 関わらず、mpdstringnorm-patch.py 側の「対応不能」判断が更新されないまま
# 放置されていた不具合 (TODO 全項目消化済みのため自走エージェントが横断調査し
# 新規発見・追加した項目)。
#
# current_playlist.py の `_pf_matches` (playlistfind/playlistsearch 用) は
# 既に `context.session.string_normalization` を見て `_pf_strip_diacritics`
# (NFD分解→結合文字(Mark)除去→NFC、実MPDのICU "NFD; [:M:] Remove; NFC"
# transliteratorと同じアルゴリズム) を values/needle 双方に適用しているが、
# music_db.py の `_mpd_track_excluded`/`_mpd_track_matches_positives` には
# 同等のロジックが一切無い (patch前は music_db.py に strip_diacritics の
# 文字列が0件)。本パッチは同じアルゴリズムを music_db.py 側にも配線し、
# search/searchadd/searchaddpl/searchcount (実MPD仕様上 stringnormalization が
# 効く対象、count/find/findadd は対象外) のフィルタ式後段フィルタで
# strip_diacritics を適用する。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "def _mpd_strip_diacritics("
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    import re as _re

    # --- 1. _mpd_track_excluded / _mpd_filter_negatives ---
    old_negatives = '''def _mpd_track_excluded(track, negatives, case_sensitive):
    """`!=`/`!~`/`!(...)` (negatives) のいずれかにマッチしたら True
    (=結果から除外)。実MPD仕様 (musicpd.org filter syntax): 否定条件は
    タグの全値のいずれかと一致したら除外する。kind は positives と同じ
    exact/contains/starts_with/regex。`find`/`findadd` は大文字小文字を
    区別、`search`/`searchadd`/`searchaddpl`/`count` は区別しない。"""
    for field, kind, needle in negatives:
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if kind == "regex":
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if any(pattern.search(v) for v in values):
                return True
        elif kind == "starts_with":
            if case_sensitive:
                if any(v.startswith(needle) for v in values):
                    return True
            elif any(v.lower().startswith(needle.lower()) for v in values):
                return True
        elif kind == "contains":
            if case_sensitive:
                if any(needle in v for v in values):
                    return True
            elif any(needle.lower() in v.lower() for v in values):
                return True
        elif case_sensitive:
            if needle in values:
                return True
        elif needle.lower() in [v.lower() for v in values]:
            return True
    return False


def _mpd_filter_negatives(tracks, negatives, case_sensitive):
    if not negatives:
        return tracks
    return [t for t in tracks if not _mpd_track_excluded(t, negatives, case_sensitive)]
'''
    assert s.count(old_negatives) == 1, f"negatives anchor count={s.count(old_negatives)}"

    new_negatives = '''import unicodedata as _mpdsd_unicodedata


def _mpd_strip_diacritics(text):
    """実MPDのICU "NFD; [:M:] Remove; NFC" transliteratorと同じアルゴリズム
    (current_playlist.py の _pf_strip_diacritics と同一実装)。"""
    decomposed = _mpdsd_unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not _mpdsd_unicodedata.combining(c))
    return _mpdsd_unicodedata.normalize("NFC", stripped)


def _mpd_track_excluded(track, negatives, case_sensitive, strip_diacritics=False):
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
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if any(pattern.search(v) for v in values):
                return True
        elif kind == "starts_with":
            if case_sensitive:
                if any(v.startswith(needle) for v in values):
                    return True
            elif any(v.lower().startswith(needle.lower()) for v in values):
                return True
        elif kind == "contains":
            if case_sensitive:
                if any(needle in v for v in values):
                    return True
            elif any(needle.lower() in v.lower() for v in values):
                return True
        elif case_sensitive:
            if needle in values:
                return True
        elif needle.lower() in [v.lower() for v in values]:
            return True
    return False


def _mpd_filter_negatives(tracks, negatives, case_sensitive, strip_diacritics=False):
    if not negatives:
        return tracks
    return [
        t
        for t in tracks
        if not _mpd_track_excluded(t, negatives, case_sensitive, strip_diacritics)
    ]
'''
    s = s.replace(old_negatives, new_negatives, 1)

    # --- 2. _mpd_track_matches_positives / _mpd_filter_positives ---
    old_positives = '''def _mpd_track_matches_positives(track, positives, case_sensitive):
    """(field, kind, needle) の演算子種別付き肯定条件が全て満たされるか
    判定する (AND)。kind: exact(==)/contains/starts_with/regex(=~)。実MPD
    仕様通り、複数値タグはいずれか1つの値が条件を満たせばそのフィールドは
    合格。"""
    for field, kind, needle in positives:
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
        values = _mpd_negative_field_values(track, field)
        if not values:
            return False
        if kind == "regex":
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if case_sensitive:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if case_sensitive:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if case_sensitive:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
    return True


def _mpd_filter_positives(tracks, positives, case_sensitive):
    if not positives:
        return tracks
    return [t for t in tracks if _mpd_track_matches_positives(t, positives, case_sensitive)]
'''
    assert s.count(old_positives) == 1, f"positives anchor count={s.count(old_positives)}"

    new_positives = '''def _mpd_track_matches_positives(track, positives, case_sensitive, strip_diacritics=False):
    """(field, kind, needle) の演算子種別付き肯定条件が全て満たされるか
    判定する (AND)。kind: exact(==)/contains/starts_with/regex(=~)。実MPD
    仕様通り、複数値タグはいずれか1つの値が条件を満たせばそのフィールドは
    合格。strip_diacritics は search 系のみ (mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in positives:
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
        values = _mpd_negative_field_values(track, field)
        if not values:
            return False
        if strip_diacritics:
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "regex":
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if case_sensitive:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if case_sensitive:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if case_sensitive:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
    return True


def _mpd_filter_positives(tracks, positives, case_sensitive, strip_diacritics=False):
    if not positives:
        return tracks
    return [
        t
        for t in tracks
        if _mpd_track_matches_positives(t, positives, case_sensitive, strip_diacritics)
    ]
'''
    s = s.replace(old_positives, new_positives, 1)

    # --- 3. _mpd_count_grouped ---
    old_count_grouped = '''def _mpd_count_grouped(context, query, groups, negatives=(), positives=(), exact=True):
    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=False
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=False
        )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives, positives, exact)
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    assert s.count(old_count_grouped) == 1, f"count_grouped anchor count={s.count(old_count_grouped)}"

    new_count_grouped = '''def _mpd_count_grouped(
    context, query, groups, negatives=(), positives=(), exact=True, strip_diacritics=False
):
    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=False, strip_diacritics=strip_diacritics
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=False, strip_diacritics=strip_diacritics
        )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_count_grouped(
            context, subquery, groups[1:], negatives, positives, exact, strip_diacritics
        )
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    s = s.replace(old_count_grouped, new_count_grouped, 1)

    # --- 4. 呼び出し元: searchcount ---
    old_searchcount_call = '''    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False
    )
'''
    assert s.count(old_searchcount_call) == 1, f"searchcount anchor count={s.count(old_searchcount_call)}"
    new_searchcount_call = '''    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    _strip_diacritics = "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False,
        strip_diacritics=_strip_diacritics,
    )
'''
    s = s.replace(old_searchcount_call, new_searchcount_call, 1)

    # --- 5. 呼び出し元: search ---
    old_search_call = '''    result_tracks = artists + albums + tracks
    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=False)
    result_tracks = _mpd_filter_positives(result_tracks, _positives, case_sensitive=False)
    if _sort_field:
        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)
    if _window is not None:
        result_tracks = result_tracks[_window]
    return translator.tracks_to_mpd_format(
        result_tracks, context.session.tagtypes
    )
'''
    assert s.count(old_search_call) == 1, f"search anchor count={s.count(old_search_call)}"
    new_search_call = '''    result_tracks = artists + albums + tracks
    _strip_diacritics = "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    result_tracks = _mpd_filter_negatives(
        result_tracks, _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    result_tracks = _mpd_filter_positives(
        result_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    if _sort_field:
        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)
    if _window is not None:
        result_tracks = result_tracks[_window]
    return translator.tracks_to_mpd_format(
        result_tracks, context.session.tagtypes
    )
'''
    s = s.replace(old_search_call, new_search_call, 1)

    # --- 6. 呼び出し元: searchadd ---
    old_searchadd_call = '''    results = context.core.library.search(query).get()
    tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=False
    )
    tracks = _mpd_filter_positives(tracks, _positives, case_sensitive=False)
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]

    position = None
    if _position is not None:
        old_size = context.core.tracklist.get_length().get()
        position = _mpd_resolve_addpos_position(context, _position, old_size)
'''
    assert s.count(old_searchadd_call) == 1, f"searchadd anchor count={s.count(old_searchadd_call)}"
    new_searchadd_call = '''    _strip_diacritics = "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    results = context.core.library.search(query).get()
    tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    tracks = _mpd_filter_positives(
        tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]

    position = None
    if _position is not None:
        old_size = context.core.tracklist.get_length().get()
        position = _mpd_resolve_addpos_position(context, _position, old_size)
'''
    s = s.replace(old_searchadd_call, new_searchadd_call, 1)

    # --- 7. 呼び出し元: searchaddpl ---
    old_searchaddpl_call = '''    results = context.core.library.search(query).get()
    _new_tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=False
    )
    _new_tracks = _mpd_filter_positives(_new_tracks, _positives, case_sensitive=False)
    if _sort_field:
        _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)
    if _window is not None:
        _new_tracks = _new_tracks[_window]
'''
    assert s.count(old_searchaddpl_call) == 1, f"searchaddpl anchor count={s.count(old_searchaddpl_call)}"
    new_searchaddpl_call = '''    _strip_diacritics = "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    results = context.core.library.search(query).get()
    _new_tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    _new_tracks = _mpd_filter_positives(
        _new_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    if _sort_field:
        _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)
    if _window is not None:
        _new_tracks = _new_tracks[_window]
'''
    s = s.replace(old_searchaddpl_call, new_searchaddpl_call, 1)

    open(mp, "w").write(s)
    print("patched music_db.py: search/searchadd/searchaddpl/searchcount のフィルタ式後段"
          "フィルタに strip_diacritics (stringnormalization) を配線")
