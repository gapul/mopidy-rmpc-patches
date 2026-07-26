# mopidy-mpd 3.3.0 の `search`/`find` は末尾の `sort TYPE` 修飾子 (musicpd.org 仕様:
#   search {FILTER} [sort {TYPE}] [window {START:END}]
# ) を解釈せず、フィルタ式パス (`(Artist == "x")` 形式) では単に無視、旧来のタグ/値ペア
# パスでは "sort" を未知タグとして弾く。rmpc はソート順を UI に反映するため sort を送ってくる
# ので、これを取り除いて実際に結果を並べ替えるようにする。TYPE の `-` 接頭辞は降順、
# ArtistSort/AlbumSort/AlbumArtistSort は非Sort版へフォールバック (MPD仕様どおり)。
# window (ページング) は別項目のため未対応のまま (従来どおり無視・無害)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_extract_sort_params"
if MARKER in s:
    print("sort modifier support already present, skip")
else:
    helper = r'''

_SORT_MAPPING = dict(_SEARCH_MAPPING)
_SORT_MAPPING.pop("any", None)
_SORT_MAPPING.update(
    {
        "artistsort": "artist",
        "albumsort": "album",
        "albumartistsort": "albumartist",
        "last-modified": "last_modified",
    }
)


def _mpd_extract_sort_params(params):
    """末尾から `sort TYPE` / `window ...` 修飾子対を剥がし、(残りの引数, sort用フィールド,
    降順か) を返す。`_mpd_extract_group_params` (mpdlist-patch) と同様、末尾からのみ剥がす
    ことで、フィルタ値がたまたま "sort" だった場合の誤爆を避ける。`window` はこの項目では
    未対応のため、値を読み飛ばすだけ (今まで通り無視・無害)。sort が無ければ
    (params, None, False)。TYPE が未知タグの場合はエラー。
    """
    params = list(params)
    sort_field = None
    descending = False
    while len(params) >= 2 and params[-2].lower() in ("sort", "window"):
        key = params[-2].lower()
        value = params[-1]
        del params[-2:]
        if key == "sort":
            desc = value.startswith("-")
            type_ = value[1:] if desc else value
            field = _SORT_MAPPING.get(type_.lower())
            if field is None:
                raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
            sort_field, descending = field, desc
    return params, sort_field, descending


def _mpd_sort_value(track, field):
    if field == "artist":
        return ", ".join(a.name for a in track.artists if a.name).lower()
    if field == "albumartist":
        artists = track.album.artists if track.album else []
        value = ", ".join(a.name for a in artists if a.name)
        return value.lower() if value else _mpd_sort_value(track, "artist")
    if field == "album":
        name = track.album.name if track.album else None
        return (name or "").lower()
    if field == "composer":
        return ", ".join(a.name for a in track.composers if a.name).lower()
    if field == "performer":
        return ", ".join(a.name for a in track.performers if a.name).lower()
    if field == "track_name":
        return (track.name or "").lower()
    if field in ("track_no", "disc_no", "last_modified"):
        return getattr(track, field, None) or 0
    return (getattr(track, field, None) or "").lower()


def _mpd_sort_tracks(tracks, field, descending):
    return sorted(tracks, key=lambda t: _mpd_sort_value(t, field), reverse=descending)
'''
    anchor_helper = '_SEARCH_MAPPING = dict(_LIST_MAPPING, **{"any": "any"})\n'
    assert s.count(anchor_helper) == 1, f"anchor_helper count={s.count(anchor_helper)}"
    s = s.replace(anchor_helper, anchor_helper + helper, 1)

    # find: 引数から sort を抜き出し、最終トラック列に適用する
    anchor_find = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
    )
    inject_find = (
        "    args, _sort_field, _sort_desc = _mpd_extract_sort_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
    )
    assert s.count(anchor_find) == 1, f"anchor_find count={s.count(anchor_find)}"
    s = s.replace(anchor_find, inject_find, 1)

    anchor_find_tail = (
        "    result_tracks += _get_tracks(results)\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    inject_find_tail = (
        "    result_tracks += _get_tracks(results)\n"
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    assert s.count(anchor_find_tail) == 1, f"anchor_find_tail count={s.count(anchor_find_tail)}"
    s = s.replace(anchor_find_tail, inject_find_tail, 1)

    # search: 同様に sort を抜き出し適用する
    anchor_search = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    results = context.core.library.search(query).get()\n"
        "    artists = [_artist_as_track(a) for a in _get_artists(results)]\n"
        "    albums = [_album_as_track(a) for a in _get_albums(results)]\n"
        "    tracks = _get_tracks(results)\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        artists + albums + tracks, context.session.tagtypes\n"
        "    )\n"
    )
    inject_search = (
        "    args, _sort_field, _sort_desc = _mpd_extract_sort_params(args)\n"
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
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    assert s.count(anchor_search) == 1, f"anchor_search count={s.count(anchor_search)}"
    s = s.replace(anchor_search, inject_search, 1)

    open(p, "w").write(s)
    print("patched music_db.py: search/find の sort 修飾をサポート")
