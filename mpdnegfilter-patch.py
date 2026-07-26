# mopidy-mpd 3.3.0 の新 MPD フィルタ式パーサ (mpdsearch-patch.py が追加した
# `_query_from_mpd_filter_expression`) は `!=`/`!~` (not-equal / not-regex) 演算子を
# 「否定/OR は best-effort でスキップ」と明記した上で単純に読み捨てており、
# `find`/`search`/`findadd`/`searchadd`/`searchaddpl`/`count`/`playlistfind`/`playlistsearch`
# 全てで同じ挙動になる。TODO 全項目消化済みのため自走エージェントが調査して新規発見・
# 追加した項目。
#
# 実 MPD 仕様 (WebFetch で mpd.readthedocs.io/protocol.html の Filters 節を確認済み):
#   - find/playlistfind は大文字小文字を区別、search/searchadd/searchaddpl/count/
#     playlistsearch は区別しない
#   - `!=` はタグの全値のいずれとも一致しないことが条件を満たす条件
#     (=いずれか1つでも一致したら除外)。`!~` も同様の否定を正規表現で行う
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc-mpd/src/filter.rs の `FilterKind` は Exact/NotExact/StartsWith/Contains/Regex/
# NotRegex/CustomQuery を持ち、rmpc/src/ui/panes/search/inputs.rs の `SearchMode` の
# NotExact/NotRegex がそのまま `FilterKind::NotExact`/`NotRegex` に変換される、検索ペインの
# 実在する検索モードであることを確認した。加えて rmpc/src/config/search.rs の
# `custom_query`(既定 false、ユーザがconfigで有効化するオプトイン機能)を有効にすると、
# rmpc/src/ui/panes/search/mod.rs の `search()` はユーザが自由入力したフィルタ式文字列を
# ほぼそのまま `FilterKind::CustomQuery` として `find`/`search` に渡す (`!=`/`!~` を他の
# 条件と AND 結合した式を直接送れる)。
#
# dev mopidy(6601, ytmusic 実アカウント) に実際に `find "(Artist == \"YOASOBI\") AND
# (Genre != \"Rock\")"` を送って現況を確認したところ、`Genre != "Rock"` 条件が完全に
# 無視されたまま `Artist == "YOASOBI"` 単独と同じ175行(全曲)が返り、除外条件が一切
# 効かないサイレントな不正確さを実機で再現確認した。
#
# 修正方針: `_query_from_mpd_filter_expression` を、`!=`/`!~` を読み捨てる代わりに
# `(field, is_regex, value)` のリストとして集め、返す query dict に隠しキー
# `__mpd_negatives__` として載せる (バックエンドへ丸投げする前に必ず pop する)。
# `find`/`findadd`/`search`/`searchadd`/`searchaddpl`/`count`(非group) は
# `context.core.library.search()` でバックエンド(mopidy-ytmusicならリモートAPI)から
# 取得した結果に対し、ローカルの Track オブジェクトを直接見て否定条件を後段フィルタする
# (positiveな条件と違い、取得済みの実データに対する単純な文字列/正規表現比較のみで
# 完結するため、mount/crossfade/stringnormalization-on-search のような「バックエンドに
# 丸投げしているため対応不能」という制約が本質的に存在しない)。playlistfind/playlistsearch
# (mpdplaylistfind-patch.py) はキュー内をローカル走査する実装のため、同じ関数を再利用し
# `_pf_matches` に否定条件チェックを追加するだけで対応できる。
#
# 既知の制約 (mount/crossfade と同種の割り切り):
#   - フィルタが `!=`/`!~` のみ (positive な条件が皆無) の場合は今まで通り
#     `ACK incorrect arguments` のまま。実 MPD はローカル全曲DBを持つため
#     「Xを含まない全曲」を素朴に列挙できるが、mopidy-ytmusic はリモート検索APIのみで
#     「全曲を取得する」手段が無く(get_distinct はタグの distinct 値であって曲一覧では
#     ない)、この構成では原理的に代替不能。rmpc の検索ペインは検索モードを全入力欄に
#     一括適用するため (`search_mode.into()` を全 Filter に適用)、単一欄のみ入力して
#     NotExact/NotRegex を選ぶとこのケースに該当し引き続き動作しない
#     (rmpc-mpd/src/mpd_client.rs 経由のカスタムクエリや複数欄併用で positive な条件も
#     含めれば動く)。
#   - `list`/グループ化 `count group ...` は `get_distinct()` 経由でタグの distinct 値を
#     取得する構造上、Track単位の後段フィルタと相性が悪いため対象外のまま
#     (`!=`/`!~` 混入時は query から pop するだけで従来通り無視、クラッシュはしない)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_pop_negatives"
if MARKER in s:
    print("negative filter (!=/!~) support already present in music_db.py, skip")
else:
    # import re を追加
    anchor_import = "import functools\nimport itertools\n"
    assert s.count(anchor_import) == 1, f"anchor_import count={s.count(anchor_import)}"
    s = s.replace(anchor_import, anchor_import + "import re\n", 1)

    # _query_from_mpd_filter_expression: query 初期化直後に negatives も初期化
    anchor_init = (
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
        "    query = {}\n"
        "    idx = 0\n"
        "    L = len(expr)\n"
    )
    assert s.count(anchor_init) == 1, f"anchor_init count={s.count(anchor_init)}"
    inject_init = (
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
        "    query = {}\n"
        "    negatives = []\n"
        "    idx = 0\n"
        "    L = len(expr)\n"
    )
    s = s.replace(anchor_init, inject_init, 1)

    # !=/!~ を読み捨てず negatives に集約 + helper 関数群を追加
    old_tail = r'''        parts = head.split()
        if len(parts) >= 2:
            tag = parts[0].strip("\"'").lstrip("(")
            op = parts[-1]
            if op in ("!=", "!~"):
                continue
            field = mapping.get(tag.lower())
            if field and value.strip():
                query.setdefault(field, []).append(value)
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")
    return query


def _mpd_extract_group_params(params):
'''
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"

    new_tail = r'''        parts = head.split()
        if len(parts) >= 2:
            tag = parts[0].strip("\"'").lstrip("(")
            op = parts[-1]
            field = mapping.get(tag.lower())
            if not field or not value.strip():
                continue
            if op in ("!=", "!~"):
                negatives.append((field, op == "!~", value))
            else:
                query.setdefault(field, []).append(value)
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")
    if negatives:
        query["__mpd_negatives__"] = negatives
    return query


def _mpd_pop_negatives(query):
    """`_query_from_mpd_filter_expression` が `__mpd_negatives__` に詰めた
    (field, is_regex, value) の否定条件リストを取り出し、query 本体からは
    取り除く (バックエンドの library.search/get_distinct へ丸投げする際に
    未知キーとして混入させないため)。"""
    if not query:
        return []
    return query.pop("__mpd_negatives__", [])


def _mpd_negative_field_values(track, field):
    if field == "any":
        values = []
        for f in _SEARCH_MAPPING.values():
            if f == "any":
                continue
            values.extend(_mpd_negative_field_values(track, f))
        return values
    if field == "uri":
        return [track.uri] if track.uri else []
    if field == "track_name":
        return [track.name] if track.name else []
    if field == "album":
        return [track.album.name] if track.album and track.album.name else []
    if field == "albumartist":
        artists = track.album.artists if track.album else []
        return [a.name for a in artists if a.name]
    if field == "artist":
        return [a.name for a in track.artists if a.name]
    if field == "composer":
        return [a.name for a in track.composers if a.name]
    if field == "performer":
        return [a.name for a in track.performers if a.name]
    if field == "genre":
        return [track.genre] if track.genre else []
    if field == "date":
        return [track.date] if track.date else []
    if field == "comment":
        return [track.comment] if track.comment else []
    if field == "disc_no":
        return [str(track.disc_no)] if track.disc_no is not None else []
    if field == "track_no":
        return [str(track.track_no)] if track.track_no is not None else []
    if field == "musicbrainz_trackid":
        return [track.musicbrainz_id] if track.musicbrainz_id else []
    if field == "musicbrainz_albumid":
        if track.album and track.album.musicbrainz_id:
            return [track.album.musicbrainz_id]
        return []
    if field == "musicbrainz_artistid":
        return [a.musicbrainz_id for a in track.artists if a.musicbrainz_id]
    return []


def _mpd_track_excluded(track, negatives, case_sensitive):
    """`!=`/`!~` (negatives) のいずれかにマッチしたら True (=結果から除外)。
    実MPD仕様 (musicpd.org filter syntax): `!=` はタグの全値のいずれとも
    一致しないことが条件を満たす条件 (=いずれか1つでも一致したら除外)。
    `find`/`findadd` は大文字小文字を区別、`search`/`searchadd`/
    `searchaddpl`/`count` は区別しない。"""
    for field, is_regex, needle in negatives:
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if is_regex:
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if any(pattern.search(v) for v in values):
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


def _mpd_extract_group_params(params):
'''
    s = s.replace(old_tail, new_tail, 1)

    # count(): negatives を抽出して _mpd_count_grouped へ渡す
    old_count = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    return _mpd_count_grouped(context, query, _group_fields)\n"
    )
    assert s.count(old_count) == 1, f"old_count count={s.count(old_count)}"
    new_count = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives)\n"
    )
    s = s.replace(old_count, new_count, 1)

    # _mpd_count_grouped(): negatives 引数を追加し、非group(末端)の結果に適用
    old_count_grouped = (
        "def _mpd_count_grouped(context, query, groups):\n"
        "    if not groups:\n"
        "        results = context.core.library.search(query=query, exact=True).get()\n"
        "        result_tracks = _get_tracks(results)\n"
        "        total_length = sum(t.length for t in result_tracks if t.length)\n"
        "        return [\n"
        '            ("songs", len(result_tracks)),\n'
        '            ("playtime", int(total_length / 1000)),\n'
        "        ]\n"
        "    gfield = groups[0]\n"
        "    gname = _LIST_NAME_MAPPING.get(gfield, gfield)\n"
        "    gvalues = context.core.library.get_distinct(gfield, query).get()\n"
        "    rows = []\n"
        "    for gvalue in sorted(v for v in gvalues if v):\n"
        "        subquery = dict(query or {})\n"
        "        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避\n"
        "        sub = _mpd_count_grouped(context, subquery, groups[1:])\n"
        '        if dict(sub).get("songs"):\n'
        "            rows.append((gname, gvalue))\n"
        "            rows.extend(sub)\n"
        "    return rows\n"
    )
    assert s.count(old_count_grouped) == 1, f"old_count_grouped count={s.count(old_count_grouped)}"
    new_count_grouped = (
        "def _mpd_count_grouped(context, query, groups, negatives=()):\n"
        "    if not groups:\n"
        "        results = context.core.library.search(query=query, exact=True).get()\n"
        "        result_tracks = _mpd_filter_negatives(\n"
        "            _get_tracks(results), negatives, case_sensitive=False\n"
        "        )\n"
        "        total_length = sum(t.length for t in result_tracks if t.length)\n"
        "        return [\n"
        '            ("songs", len(result_tracks)),\n'
        '            ("playtime", int(total_length / 1000)),\n'
        "        ]\n"
        "    gfield = groups[0]\n"
        "    gname = _LIST_NAME_MAPPING.get(gfield, gfield)\n"
        "    gvalues = context.core.library.get_distinct(gfield, query).get()\n"
        "    rows = []\n"
        "    for gvalue in sorted(v for v in gvalues if v):\n"
        "        subquery = dict(query or {})\n"
        "        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避\n"
        "        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives)\n"
        '        if dict(sub).get("songs"):\n'
        "            rows.append((gname, gvalue))\n"
        "            rows.extend(sub)\n"
        "    return rows\n"
    )
    s = s.replace(old_count_grouped, new_count_grouped, 1)

    # list_(): negatives が紛れ込んでいたら query から pop するだけ (grouped値列挙は
    # get_distinct() 経由でTrack単位の後段フィルタと相性が悪いため対象外、既存の
    # 「読み捨てる」挙動を維持しつつ __mpd_negatives__ キーがバックエンドへ漏れないようにする)
    old_list_tail = (
        "            raise\n"
        "        except ValueError:\n"
        "            return\n"
        "\n"
        "    name = _LIST_NAME_MAPPING[field]\n"
        "    return _mpd_list_grouped(context, field, name, query, group_fields)\n"
    )
    assert s.count(old_list_tail) == 1, f"old_list_tail count={s.count(old_list_tail)}"
    new_list_tail = (
        "            raise\n"
        "        except ValueError:\n"
        "            return\n"
        "\n"
        "    _mpd_pop_negatives(query)  # list はグループ化タグ値の列挙のため !=/!~ は対象外\n"
        "    name = _LIST_NAME_MAPPING[field]\n"
        "    return _mpd_list_grouped(context, field, name, query, group_fields)\n"
    )
    s = s.replace(old_list_tail, new_list_tail, 1)

    # find(): negatives を抽出し、結果トラック列に後段フィルタ適用 (find は大文字小文字区別)
    old_find = (
        "    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
        "    if (\n"
        '        "artist" not in query\n'
        '        and "albumartist" not in query\n'
        '        and "composer" not in query\n'
        '        and "performer" not in query\n'
        "    ):\n"
        "        result_tracks += [_artist_as_track(a) for a in _get_artists(results)]\n"
        '    if "album" not in query:\n'
        "        result_tracks += [_album_as_track(a) for a in _get_albums(results)]\n"
        "    result_tracks += _get_tracks(results)\n"
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        result_tracks = result_tracks[_window]\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    assert s.count(old_find) == 1, f"old_find count={s.count(old_find)}"
    new_find = (
        "    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
        "    if (\n"
        '        "artist" not in query\n'
        '        and "albumartist" not in query\n'
        '        and "composer" not in query\n'
        '        and "performer" not in query\n'
        "    ):\n"
        "        result_tracks += [_artist_as_track(a) for a in _get_artists(results)]\n"
        '    if "album" not in query:\n'
        "        result_tracks += [_album_as_track(a) for a in _get_albums(results)]\n"
        "    result_tracks += _get_tracks(results)\n"
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=True)\n"
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        result_tracks = result_tracks[_window]\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    s = s.replace(old_find, new_find, 1)

    # findadd(): 同様 (find と大文字小文字区別の扱いは同じ)
    old_findadd = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[track.uri for track in _get_tracks(results)]\n"
        "    ).get()\n"
    )
    assert s.count(old_findadd) == 1, f"old_findadd count={s.count(old_findadd)}"
    new_findadd = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=True\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
    )
    s = s.replace(old_findadd, new_findadd, 1)

    # search(): negatives を抽出し、結果トラック列に後段フィルタ適用 (search は大文字小文字区別しない)
    old_search = (
        "    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    results = context.core.library.search(query).get()\n"
        "    artists = [_artist_as_track(a) for a in _get_artists(results)]\n"
        "    albums = [_album_as_track(a) for a in _get_albums(results)]\n"
        "    tracks = _get_tracks(results)\n"
        "    result_tracks = artists + albums + tracks\n"
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        result_tracks = result_tracks[_window]\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    assert s.count(old_search) == 1, f"old_search count={s.count(old_search)}"
    new_search = (
        "    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    artists = [_artist_as_track(a) for a in _get_artists(results)]\n"
        "    albums = [_album_as_track(a) for a in _get_albums(results)]\n"
        "    tracks = _get_tracks(results)\n"
        "    result_tracks = artists + albums + tracks\n"
        "    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=False)\n"
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        result_tracks = result_tracks[_window]\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    s = s.replace(old_search, new_search, 1)

    # searchadd(): 同様 (search と大文字小文字区別しない扱いは同じ)
    old_searchadd = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[track.uri for track in _get_tracks(results)]\n"
        "    ).get()\n"
    )
    assert s.count(old_searchadd) == 1, f"old_searchadd count={s.count(old_searchadd)}"
    new_searchadd = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=False\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
    )
    s = s.replace(old_searchadd, new_searchadd, 1)

    # searchaddpl(): 同様
    old_searchaddpl = (
        "    parameters = list(args)\n"
        "    if not parameters:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    playlist_name = parameters.pop(0)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "    playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "    tracks = list(playlist.tracks) + _get_tracks(results)\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    context.core.playlists.save(playlist)\n"
    )
    assert s.count(old_searchaddpl) == 1, f"old_searchaddpl count={s.count(old_searchaddpl)}"
    new_searchaddpl = (
        "    parameters = list(args)\n"
        "    if not parameters:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    playlist_name = parameters.pop(0)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "    playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "    tracks = list(playlist.tracks) + _new_tracks\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    context.core.playlists.save(playlist)\n"
    )
    s = s.replace(old_searchaddpl, new_searchaddpl, 1)

    open(p, "w").write(s)
    print("patched music_db.py: !=/!~ (not-equal/not-regex) フィルタ演算子をサポート")

# current_playlist.py 側: playlistfind/playlistsearch (mpdplaylistfind-patch.py) も同じ
# _query_from_mpd_search_parameters を再利用しているため、__mpd_negatives__ キーが
# そのまま _pf_matches に渡ると (field, needles) ループがタプルのリストを文字列needle列
# として扱ってしまい常に不一致→結果0件になる回帰が起きる。_pf_search 側で pop した上で
# _pf_matches に否定条件チェックを追加し、正しく除外できるようにする。
cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

CP_MARKER = "_mpd_pop_negatives"
if CP_MARKER in s_cp:
    print("negative filter (!=/!~) support already present in current_playlist.py, skip")
else:
    anchor_import = "import urllib\n\nimport unicodedata\n"
    assert s_cp.count(anchor_import) == 1, f"cp anchor_import count={s_cp.count(anchor_import)}"
    s_cp = s_cp.replace(anchor_import, "import re\n" + anchor_import, 1)

    old_music_db_import = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    assert s_cp.count(old_music_db_import) == 1, (
        f"old_music_db_import count={s_cp.count(old_music_db_import)}"
    )
    new_music_db_import = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    s_cp = s_cp.replace(old_music_db_import, new_music_db_import, 1)

    old_pf_matches = (
        "def _pf_matches(track, query, strict, strip_diacritics=False):\n"
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
        "    return True\n"
    )
    assert s_cp.count(old_pf_matches) == 1, f"old_pf_matches count={s_cp.count(old_pf_matches)}"
    new_pf_matches = (
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
    s_cp = s_cp.replace(old_pf_matches, new_pf_matches, 1)

    old_pf_search = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
        "    strip_diacritics = not strict and \"strip_diacritics\" in getattr(\n"
        '        context.session, "string_normalization", ()\n'
        "    )\n"
        "    tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "    matches = [\n"
        "        (position, tl_track)\n"
        "        for position, tl_track in enumerate(tl_tracks)\n"
        "        if _pf_matches(tl_track.track, query, strict, strip_diacritics)\n"
        "    ]\n"
    )
    assert s_cp.count(old_pf_search) == 1, f"old_pf_search count={s_cp.count(old_pf_search)}"
    new_pf_search = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    negatives = _mpd_pop_negatives(query)\n"
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
        "    strip_diacritics = not strict and \"strip_diacritics\" in getattr(\n"
        '        context.session, "string_normalization", ()\n'
        "    )\n"
        "    tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "    matches = [\n"
        "        (position, tl_track)\n"
        "        for position, tl_track in enumerate(tl_tracks)\n"
        "        if _pf_matches(tl_track.track, query, strict, strip_diacritics, negatives)\n"
        "    ]\n"
    )
    s_cp = s_cp.replace(old_pf_search, new_pf_search, 1)

    open(cp, "w").write(s_cp)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch へ "
        "!=/!~ (not-equal/not-regex) フィルタ演算子のサポートを追加"
    )
