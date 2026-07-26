# mopidy-mpd 3.3.0 の `findadd`/`searchadd` は `{TYPE} {WHAT} [...]` の生の args を
# そのまま `_query_from_mpd_search_parameters` に渡すだけで、`sort`/`window`/`position`
# 修飾子を一切解釈しない。フィルタ式形式 (`findadd "(Artist == \"X\")"`) の場合は
# `_query_from_mpd_search_parameters` が args[0] しか見ないため、末尾に付いた
# `sort ...`/`window ...`/`position ...` トークンは ACK エラーにすらならず黙って
# 無視される (クラッシュしないが要求を静かに無視する不具合)。
#
# TODO 全項目消化済みのため自走エージェントが rmpc 本体 (mierak/rmpc) を実際に clone
# して調査したところ、rmpc-mpd/src/mpd_client.rs の `send_find_add` が
# `findadd "(FILTER)" position POS` を実際に送信しており (searchadd は定義はあるが
# 呼び出し元皆無で未使用、searchaddpl は rmpc に送信箇所自体が無い = 既存の
# addid/add/load POSITION 系項目と同じ「クライアントtraitに定義はあるが一部は死んでいる」
# パターン)、rmpc/src/shared/mpd_client_ext.rs の `enqueue_multiple` から
# `Enqueue::Find { filter }` 経由で呼ばれ、実際に rmpc/src/ui/panes/search/mod.rs の
# 検索結果ペインで「現在の曲の次に追加」「前に追加」等の位置指定つき追加アクション
# (rmpc/src/config/keys/actions.rs Position::AfterCurrentSong/BeforeCurrentSong) を
# 検索結果に対して実行すると `findadd "(...)" position "+0"` が送られると確認した。
# mopidy-mpd の現状ではこの position 指定が黙って無視され、常に末尾に追加されてしまう
# (エラーにはならないが要求と異なる位置に追加される) 実害あるギャップと確認した上で
# 追加した項目。
#
# musicpd.org protocol (WebFetch で確認): `findadd {FILTER} [sort {TYPE}]
# [window {START:END}] [position POS]` / `searchadd` も同形式。position は
# addid と同じ絶対/相対 (+N/-N, 現在曲基準) 指定。mpdsort-patch.py/mpdwindow-patch.py が
# 既に music_db.py に用意した `_mpd_extract_sort_params`/`_mpd_sort_tracks`/
# `_mpd_parse_window` をそのまま再利用し、position だけ mpdaddpos-patch.py/
# mpdloadpos-patch.py と同じ MoveRange アルゴリズム (mopidy core の
# tracklist.move(start, end, to_position) で「末尾に追加してから範囲ごと move」) を
# 移植する。searchaddpl は rmpc から一切送信されないため対象外 (position 未対応のまま)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_resolve_addpos_position"
if MARKER in s:
    print("findadd/searchadd position already patched, skip")
else:
    old_findadd = (
        '@protocol.commands.add("findadd")\n'
        "def findadd(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``findadd {TYPE} {WHAT}``\n"
        "\n"
        "        Finds songs in the db that are exactly ``WHAT`` and adds them to\n"
        "        current playlist. Parameters have the same meaning as for ``find``.\n"
        '    """\n'
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=True\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert s.count(old_findadd) == 1, f"old_findadd count={s.count(old_findadd)}"

    new_findadd = (
        "class _MpdAddPosPlayerSyncError(exceptions.MpdAckError):\n"
        "    error_code = exceptions.MpdAckError.ACK_ERROR_PLAYER_SYNC\n"
        "\n"
        "\n"
        "def _mpd_parse_addpos_position(value):\n"
        "    # findadd/searchadd の position: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid/load と同じ書式)。\n"
        '    if value[:1] in ("+", "-"):\n'
        "        rest = value[1:]\n"
        "        if not rest.isdigit():\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        return (value[0], int(rest))\n"
        "    if not value.isdigit():\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    return (None, int(value))\n"
        "\n"
        "\n"
        "def _mpd_extract_addpos_params(params):\n"
        "    # findadd/searchadd の末尾修飾子 `[sort TYPE] [window START:END]\n"
        "    # [position POS]` を剥がす。実MPD仕様の並びは常に position が最後尾なので\n"
        "    # 先に position を1組だけ剥がし、残りを既存の _mpd_extract_sort_params\n"
        "    # (sort/window、find/search と共用) に委譲する。\n"
        "    params = list(params)\n"
        "    position = None\n"
        '    if len(params) >= 2 and params[-2].lower() == "position":\n'
        "        position = _mpd_parse_addpos_position(params[-1])\n"
        "        del params[-2:]\n"
        "    params, sort_field, descending, window = _mpd_extract_sort_params(params)\n"
        "    return params, sort_field, descending, window, position\n"
        "\n"
        "\n"
        "def _mpd_resolve_addpos_position(context, songpos, old_size):\n"
        "    # (kind, offset) を実際の挿入位置 (0 <= position <= old_size) へ解決する。\n"
        "    # kind is None: 絶対位置。'+': 現在曲の直後基準。'-': 現在曲の直前基準。\n"
        "    kind, offset = songpos\n"
        "    if kind is None:\n"
        "        if offset > old_size:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        return offset\n"
        "    current = context.core.tracklist.index().get()\n"
        "    if current is None:\n"
        '        raise _MpdAddPosPlayerSyncError("No current song")\n'
        '    if kind == "+":\n'
        "        if offset > old_size - current - 1:\n"
        '            raise exceptions.MpdArgError("Number too large")\n'
        "        return current + 1 + offset\n"
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n"
        "\n"
        '@protocol.commands.add("findadd")\n'
        "def findadd(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``findadd {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]``\n"
        "\n"
        "        Finds songs in the db that are exactly ``WHAT`` and adds them to\n"
        "        current playlist. Parameters have the same meaning as for ``find``.\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before). Absent, songs\n"
        "        are appended to the end of the playlist as before.\n"
        '    """\n'
        "    args, _sort_field, _sort_desc, _window, _position = (\n"
        "        _mpd_extract_addpos_params(args)\n"
        "    )\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=True\n"
        "    )\n"
        "    if _sort_field:\n"
        "        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        tracks = tracks[_window]\n"
        "\n"
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if _position is not None:\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "\n"
        "    if tracks and position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert new_findadd != old_findadd
    s = s.replace(old_findadd, new_findadd, 1)

    old_searchadd = (
        '@protocol.commands.add("searchadd")\n'
        "def searchadd(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``searchadd {TYPE} {WHAT} [...]``\n"
        "\n"
        "        Searches for any song that contains ``WHAT`` in tag ``TYPE`` and adds\n"
        "        them to current playlist.\n"
        "\n"
        "        Parameters have the same meaning as for ``find``, except that search is\n"
        "        not case sensitive.\n"
        '    """\n'
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=False\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert s.count(old_searchadd) == 1, f"old_searchadd count={s.count(old_searchadd)}"

    new_searchadd = (
        '@protocol.commands.add("searchadd")\n'
        "def searchadd(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``searchadd {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]``\n"
        "\n"
        "        Searches for any song that contains ``WHAT`` in tag ``TYPE`` and adds\n"
        "        them to current playlist.\n"
        "\n"
        "        Parameters have the same meaning as for ``find``, except that search is\n"
        "        not case sensitive. ``POSITION`` is as for ``findadd``.\n"
        '    """\n'
        "    args, _sort_field, _sort_desc, _window, _position = (\n"
        "        _mpd_extract_addpos_params(args)\n"
        "    )\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "\n"
        "    results = context.core.library.search(query).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    if _sort_field:\n"
        "        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        tracks = tracks[_window]\n"
        "\n"
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if _position is not None:\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "\n"
        "    if tracks and position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert new_searchadd != old_searchadd
    s = s.replace(old_searchadd, new_searchadd, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: findadd/searchadd に sort/window/position "
        "(MPD0.24+) を追加"
    )
