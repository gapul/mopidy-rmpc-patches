# mpdnegfilter-patch.py は MPD フィルタ式の `!=`/`!~` (否定) を実装したが、
# 肯定演算子側 (`==` exact / `contains` / `starts_with` / `=~` regex) は
# `_query_from_mpd_filter_expression` が演算子そのものを読み捨てており、
# `(Artist == "X")` も `(Artist contains "X")` も `(Artist starts_with "X")` も
# `(Artist =~ "X")` も区別なく同じ `query["artist"] = ["X"]` として backend の
# library.search() に丸投げされ、結果は backend の(ytmusicならリモートAPIの)
# 実装依存の緩いマッチのまま返る。TODO 全項目消化済みのため自走エージェントが
# 調査して新規発見・追加した項目。
#
# 実害: rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc/src/ui/panes/search/inputs.rs の `SearchMode` (検索ペインでキーバインド
# により Exact/StartsWith/Contains/Regex/NotExact/NotRegex をユーザが明示的に
# 切り替えられる実在の機能、既定は config の `FilterKindFile`、cycle()で巡回) が
# `FilterKind::Exact/StartsWith/Contains/Regex` として `find`/`search` に
# 送信される (rmpc-mpd/src/filter.rs `Filter::to_query_str`)。つまりユーザが
# 検索ペインで「Exact」や「StartsWith」「Regex」モードへ切り替えても、
# サーバー側が演算子を無視するため実際には常に(backendの緩い)マッチのままで
# あり、ユーザ操作が結果に反映されないサイレントな不整合がある。
#
# 実 MPD 仕様 (WebFetch で mpd.readthedocs.io/protocol.html の Filters 節を
# 確認済み):
#   - `(TAG == "VALUE")`: タグ値の完全一致 (複数値タグは1つでも一致すればOK)
#   - `(TAG contains "VALUE")`: タグ値の部分文字列一致
#   - `(TAG starts_with "VALUE")`: タグ値の前方一致
#   - `(TAG =~ "VALUE")`: Perl互換正規表現
#   - find/playlistfind は大文字小文字を区別、search/searchadd/searchaddpl/
#     count/playlistsearch は区別しない (mpdnegfilter-patch.py と同じ既存の
#     case_sensitive 引数をそのまま流用)
#
# 修正方針: mpdnegfilter-patch.py の negatives と全く同じ機構を肯定側にも追加。
# `_query_from_mpd_filter_expression` は否定でない演算子についても
# `(field, kind, value)` を `positives` リストへ集約し、返す query dict へ隠し
# キー `__mpd_positives__` として載せる (従来通り `query[field]` へも積むため
# backend への検索クエリ自体は無変更=回帰なし)。`find`/`findadd`/`search`/
# `searchadd`/`searchaddpl`/`count`(非group) は `context.core.library.search()`
# で取得済みの実 Track データに対し、演算子の種別ごとに正しいローカル比較を
# 後段フィルタとして適用する (negatives と同じく「取得済みの実データに対する
# 単純な文字列/正規表現比較のみで完結する」ため backend 丸投げの限界を受けない)。
# playlistfind/playlistsearch (mpdplaylistfind-patch.py) も同じ機構をそのまま
# 再利用し `_pf_matches` に演算子種別チェックを追加する。
#
# 既知の制約 (mpdnegfilter-patch.py と同種の割り切り):
#   - `list`/グループ化 `count group ...` は get_distinct() 経由のためTrack単位の
#     後段フィルタと相性が悪く対象外のまま (`__mpd_positives__` 混入時は query
#     から pop するだけで従来通り無視、クラッシュはしないことを確認)。
#   - 伝統的な `TYPE VALUE` 構文 (フィルタ式でない `find artist "X"` 等) は
#     演算子情報を持たないため対象外・無変更 (従来通りbackend丸投げのまま)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_pop_positives"
if MARKER in s:
    print("positive filter operator (==/contains/starts_with/=~) support already present in music_db.py, skip")
else:
    # _MPD_POSITIVE_OP_KIND 定義を _query_from_mpd_filter_expression の直前に追加
    anchor_kindmap = "def _query_from_mpd_filter_expression(expr, mapping):\n"
    assert s.count(anchor_kindmap) == 1, f"anchor_kindmap count={s.count(anchor_kindmap)}"
    inject_kindmap = (
        "_MPD_POSITIVE_OP_KIND = {\n"
        '    "==": "exact",\n'
        '    "contains": "contains",\n'
        '    "starts_with": "starts_with",\n'
        '    "=~": "regex",\n'
        "}\n\n\n"
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
    )
    s = s.replace(anchor_kindmap, inject_kindmap, 1)

    # query 初期化直後に positives も初期化
    anchor_init = (
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
        "    query = {}\n"
        "    negatives = []\n"
        "    idx = 0\n"
        "    L = len(expr)\n"
    )
    assert s.count(anchor_init) == 1, f"anchor_init count={s.count(anchor_init)}"
    inject_init = (
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
        "    query = {}\n"
        "    negatives = []\n"
        "    positives = []\n"
        "    idx = 0\n"
        "    L = len(expr)\n"
    )
    s = s.replace(anchor_init, inject_init, 1)

    # 肯定演算子の種別を positives へ集約 + query dict へ __mpd_positives__ を積む
    old_tail = (
        "            if op in (\"!=\", \"!~\"):\n"
        "                negatives.append((field, op == \"!~\", value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "    if not query:\n"
        "        raise exceptions.MpdArgError(\"incorrect arguments\")\n"
        "    if negatives:\n"
        "        query[\"__mpd_negatives__\"] = negatives\n"
        "    return query\n"
    )
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        "            if op in (\"!=\", \"!~\"):\n"
        "                negatives.append((field, op == \"!~\", value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                kind = _MPD_POSITIVE_OP_KIND.get(op)\n"
        "                if kind:\n"
        "                    positives.append((field, kind, value))\n"
        "    if not query:\n"
        "        raise exceptions.MpdArgError(\"incorrect arguments\")\n"
        "    if negatives:\n"
        "        query[\"__mpd_negatives__\"] = negatives\n"
        "    if positives:\n"
        "        query[\"__mpd_positives__\"] = positives\n"
        "    return query\n"
    )
    s = s.replace(old_tail, new_tail, 1)

    # _mpd_pop_positives / _mpd_track_matches_positives / _mpd_filter_positives を
    # _mpd_filter_negatives の直後に追加 (_mpd_negative_field_values はフィールド値
    # 抽出の汎用ヘルパとしてそのまま再利用する)
    anchor_helpers = (
        "def _mpd_filter_negatives(tracks, negatives, case_sensitive):\n"
        "    if not negatives:\n"
        "        return tracks\n"
        "    return [t for t in tracks if not _mpd_track_excluded(t, negatives, case_sensitive)]\n"
    )
    assert s.count(anchor_helpers) == 1, f"anchor_helpers count={s.count(anchor_helpers)}"
    inject_helpers = anchor_helpers + (
        "\n\n"
        "def _mpd_pop_positives(query):\n"
        '    """`_query_from_mpd_filter_expression` が `__mpd_positives__` に詰めた\n'
        "    (field, kind, value) の演算子種別付き肯定条件リストを取り出し、query\n"
        "    本体からは取り除く (バックエンドの library.search/get_distinct へ丸投げ\n"
        '    する際に未知キーとして混入させないため)。"""\n'
        "    if not query:\n"
        "        return []\n"
        '    return query.pop("__mpd_positives__", [])\n'
        "\n\n"
        "def _mpd_track_matches_positives(track, positives, case_sensitive):\n"
        '    """(field, kind, needle) の演算子種別付き肯定条件が全て満たされるか\n'
        "    判定する (AND)。kind: exact(==)/contains/starts_with/regex(=~)。実MPD\n"
        "    仕様通り、複数値タグはいずれか1つの値が条件を満たせばそのフィールドは\n"
        '    合格。"""\n'
        "    for field, kind, needle in positives:\n"
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            return False\n"
        '        if kind == "regex":\n'
        "            try:\n"
        "                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if not any(pattern.search(v) for v in values):\n"
        "                return False\n"
        '        elif kind == "exact":\n'
        "            if case_sensitive:\n"
        "                if needle not in values:\n"
        "                    return False\n"
        "            elif needle.lower() not in [v.lower() for v in values]:\n"
        "                return False\n"
        '        elif kind == "starts_with":\n'
        "            if case_sensitive:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if case_sensitive:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        "    return True\n"
        "\n\n"
        "def _mpd_filter_positives(tracks, positives, case_sensitive):\n"
        "    if not positives:\n"
        "        return tracks\n"
        "    return [t for t in tracks if _mpd_track_matches_positives(t, positives, case_sensitive)]\n"
    )
    s = s.replace(anchor_helpers, inject_helpers, 1)

    # count(): positives も pop して _mpd_count_grouped へ渡す
    old_count = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives)\n"
    )
    assert s.count(old_count) == 1, f"old_count count={s.count(old_count)}"
    new_count = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives, _positives)\n"
    )
    s = s.replace(old_count, new_count, 1)

    # _mpd_count_grouped: シグネチャに positives を追加し非group leafで適用
    old_count_grouped = (
        "def _mpd_count_grouped(context, query, groups, negatives=()):\n"
        "    if not groups:\n"
        "        results = context.core.library.search(query=query, exact=True).get()\n"
        "        result_tracks = _mpd_filter_negatives(\n"
        "            _get_tracks(results), negatives, case_sensitive=False\n"
        "        )\n"
        "        total_length = sum(t.length for t in result_tracks if t.length)\n"
    )
    assert s.count(old_count_grouped) == 1, f"old_count_grouped count={s.count(old_count_grouped)}"
    new_count_grouped = (
        "def _mpd_count_grouped(context, query, groups, negatives=(), positives=()):\n"
        "    if not groups:\n"
        "        results = context.core.library.search(query=query, exact=True).get()\n"
        "        result_tracks = _mpd_filter_negatives(\n"
        "            _get_tracks(results), negatives, case_sensitive=False\n"
        "        )\n"
        "        result_tracks = _mpd_filter_positives(\n"
        "            result_tracks, positives, case_sensitive=False\n"
        "        )\n"
        "        total_length = sum(t.length for t in result_tracks if t.length)\n"
    )
    s = s.replace(old_count_grouped, new_count_grouped, 1)

    old_count_grouped_recurse = (
        "        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives)\n"
    )
    assert s.count(old_count_grouped_recurse) == 1, (
        f"old_count_grouped_recurse count={s.count(old_count_grouped_recurse)}"
    )
    s = s.replace(
        old_count_grouped_recurse,
        "        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives, positives)\n",
        1,
    )

    # find(): positives を pop して結果に適用
    old_find_pop = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
    )
    assert s.count(old_find_pop) == 1, f"old_find_pop count={s.count(old_find_pop)}"
    new_find_pop = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
    )
    s = s.replace(old_find_pop, new_find_pop, 1)

    old_find_filter = (
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=True)\n"
        "    if _sort_field:\n"
    )
    assert s.count(old_find_filter) == 1, f"old_find_filter count={s.count(old_find_filter)}"
    new_find_filter = (
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=True)\n"
        "    result_tracks = _mpd_filter_positives(result_tracks, _positives, case_sensitive=True)\n"
        "    if _sort_field:\n"
    )
    s = s.replace(old_find_filter, new_find_filter, 1)

    # findadd(): positives を pop して結果に適用
    old_findadd = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=True\n"
        "    )\n"
        "    if _sort_field:\n"
    )
    assert s.count(old_findadd) == 1, f"old_findadd count={s.count(old_findadd)}"
    new_findadd = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=True\n"
        "    )\n"
        "    tracks = _mpd_filter_positives(tracks, _positives, case_sensitive=True)\n"
        "    if _sort_field:\n"
    )
    s = s.replace(old_findadd, new_findadd, 1)

    # search(): positives を pop して結果に適用
    old_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    artists = [_artist_as_track(a) for a in _get_artists(results)]\n"
        "    albums = [_album_as_track(a) for a in _get_albums(results)]\n"
        "    tracks = _get_tracks(results)\n"
        "    result_tracks = artists + albums + tracks\n"
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=False)\n"
    )
    assert s.count(old_search) == 1, f"old_search count={s.count(old_search)}"
    new_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    artists = [_artist_as_track(a) for a in _get_artists(results)]\n"
        "    albums = [_album_as_track(a) for a in _get_albums(results)]\n"
        "    tracks = _get_tracks(results)\n"
        "    result_tracks = artists + albums + tracks\n"
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=False)\n"
        "    result_tracks = _mpd_filter_positives(result_tracks, _positives, case_sensitive=False)\n"
    )
    s = s.replace(old_search, new_search, 1)

    # searchadd(): positives を pop して結果に適用
    old_searchadd = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    if _sort_field:\n"
    )
    assert s.count(old_searchadd) == 1, f"old_searchadd count={s.count(old_searchadd)}"
    new_searchadd = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    tracks = _mpd_filter_positives(tracks, _positives, case_sensitive=False)\n"
        "    if _sort_field:\n"
    )
    s = s.replace(old_searchadd, new_searchadd, 1)

    # searchaddpl(): positives を pop して結果に適用
    old_searchaddpl = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
    )
    assert s.count(old_searchaddpl) == 1, f"old_searchaddpl count={s.count(old_searchaddpl)}"
    new_searchaddpl = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    _new_tracks = _mpd_filter_positives(_new_tracks, _positives, case_sensitive=False)\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
    )
    s = s.replace(old_searchaddpl, new_searchaddpl, 1)

    # list_(): positives も pop-and-discard (get_distinct はTrack単位ではないため対象外)
    old_list_pop = (
        '    _mpd_pop_negatives(query)  # list はグループ化タグ値の列挙のため !=/!~ は対象外\n'
    )
    assert s.count(old_list_pop) == 1, f"old_list_pop count={s.count(old_list_pop)}"
    new_list_pop = (
        '    _mpd_pop_negatives(query)  # list はグループ化タグ値の列挙のため !=/!~ は対象外\n'
        '    _mpd_pop_positives(query)  # 同様に演算子種別 (==/contains/starts_with/=~) も対象外\n'
    )
    s = s.replace(old_list_pop, new_list_pop, 1)

    open(p, "w").write(s)
    print("patched music_db.py: フィルタ式の肯定演算子 (==/contains/starts_with/=~) をサポート")

# current_playlist.py: playlistfind/playlistsearch にも同じ機構を適用
p2 = "mopidy_mpd/protocol/current_playlist.py"
s2 = open(p2).read()

if "_mpd_pop_positives" in s2:
    print("positive filter operator support already present in current_playlist.py, skip")
else:
    anchor_import2 = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    assert s2.count(anchor_import2) == 1, f"anchor_import2 count={s2.count(anchor_import2)}"
    inject_import2 = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_pop_positives,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    s2 = s2.replace(anchor_import2, inject_import2, 1)

    old_pf_matches = (
        "def _pf_matches(track, query, strict, strip_diacritics=False, negatives=()):\n"
        "    for field, needles in query.items():\n"
        "        values = _pf_field_values(track, field)\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "        matched = False\n"
        "        for needle in needles:\n"
        "            cmp_needle = _pf_strip_diacritics(needle) if strip_diacritics else needle\n"
        "            if strict:\n"
        "                if cmp_needle in values:\n"
        "                    matched = True\n"
        "                    break\n"
        "            elif any(cmp_needle.lower() in v.lower() for v in values):\n"
        "                matched = True\n"
        "                break\n"
        "        if not matched:\n"
        "            return False\n"
        "    for field, is_regex, needle in negatives:\n"
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if is_regex:\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return False\n"
        "        elif strict:\n"
        "            if needle in values:\n"
        "                return False\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return False\n"
        "    return True\n"
    )
    assert s2.count(old_pf_matches) == 1, f"old_pf_matches count={s2.count(old_pf_matches)}"
    new_pf_matches = (
        "def _pf_matches(\n"
        "    track, query, strict, strip_diacritics=False, negatives=(), positives=()\n"
        "):\n"
        "    _pf_positive_fields = {field for field, _kind, _needle in positives}\n"
        "    for field, needles in query.items():\n"
        "        if field in _pf_positive_fields:\n"
        "            continue  # 演算子種別付き肯定条件は下の positives ループで判定する\n"
        "        values = _pf_field_values(track, field)\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "        matched = False\n"
        "        for needle in needles:\n"
        "            cmp_needle = _pf_strip_diacritics(needle) if strip_diacritics else needle\n"
        "            if strict:\n"
        "                if cmp_needle in values:\n"
        "                    matched = True\n"
        "                    break\n"
        "            elif any(cmp_needle.lower() in v.lower() for v in values):\n"
        "                matched = True\n"
        "                break\n"
        "        if not matched:\n"
        "            return False\n"
        "    for field, is_regex, needle in negatives:\n"
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if is_regex:\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return False\n"
        "        elif strict:\n"
        "            if needle in values:\n"
        "                return False\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return False\n"
        "    for field, kind, needle in positives:\n"
        "        values = _pf_field_values(track, field)\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if not values:\n"
        "            return False\n"
        '        if kind == "regex":\n'
        "            try:\n"
        "                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if not any(pattern.search(v) for v in values):\n"
        "                return False\n"
        '        elif kind == "exact":\n'
        "            if strict:\n"
        "                if needle not in values:\n"
        "                    return False\n"
        "            elif needle.lower() not in [v.lower() for v in values]:\n"
        "                return False\n"
        '        elif kind == "starts_with":\n'
        "            if strict:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if strict:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        "    return True\n"
    )
    s2 = s2.replace(old_pf_matches, new_pf_matches, 1)

    old_pf_search = (
        "    negatives = _mpd_pop_negatives(query)\n"
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
        "    strip_diacritics = not strict and \"strip_diacritics\" in getattr(\n"
        "        context.session, \"string_normalization\", ()\n"
        "    )\n"
        "    tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "    matches = [\n"
        "        (position, tl_track)\n"
        "        for position, tl_track in enumerate(tl_tracks)\n"
        "        if _pf_matches(tl_track.track, query, strict, strip_diacritics, negatives)\n"
        "    ]\n"
    )
    assert s2.count(old_pf_search) == 1, f"old_pf_search count={s2.count(old_pf_search)}"
    new_pf_search = (
        "    negatives = _mpd_pop_negatives(query)\n"
        "    positives = _mpd_pop_positives(query)\n"
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
        "    strip_diacritics = not strict and \"strip_diacritics\" in getattr(\n"
        "        context.session, \"string_normalization\", ()\n"
        "    )\n"
        "    tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "    matches = [\n"
        "        (position, tl_track)\n"
        "        for position, tl_track in enumerate(tl_tracks)\n"
        "        if _pf_matches(\n"
        "            tl_track.track, query, strict, strip_diacritics, negatives, positives\n"
        "        )\n"
        "    ]\n"
    )
    s2 = s2.replace(old_pf_search, new_pf_search, 1)

    open(p2, "w").write(s2)
    print("patched current_playlist.py: playlistfind/playlistsearch に肯定演算子種別を適用")
