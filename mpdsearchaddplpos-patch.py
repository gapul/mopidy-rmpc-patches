# `searchaddpl {NAME} {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]`
# (MPD 0.24+): mopidy-mpd 3.3.0 の `searchaddpl` は `{NAME} {TYPE} {WHAT} [...]`
# (レガシーな TAG/VALUE ペア列のみ) しか受け付けず、findadd/searchadd に既に
# 実装済みの `sort`/`window`/`position` 修飾子を一切解釈しない (常に検索結果を
# 無条件・無ソートで末尾へ追加するのみ)。TODO 全項目消化済みのため自走エージェントが
# 実 MPD 本体のプロトコル仕様書 (mpd.readthedocs.io/en/latest/protocol.html、
# および MusicPlayerDaemon/MPD の doc/protocol.rst) を WebFetch で確認したところ、
# `find`/`search`/`findadd`/`searchadd`/`searchaddpl` の5コマンドはいずれも
# `{FILTER} [sort {TYPE}] [window {START:END}]` を共有する仕様であり、
# `findadd`/`searchadd`/`searchaddpl` の3つはさらに末尾に `[position {POS}]`
# も持つと判明。findadd/searchadd (mpdfindaddpos-patch.py) は既にこれを実装
# 済みだが、`searchaddpl` だけが唯一 legacy な固定引数のみのまま取り残されて
# いた非対称な実装だった。
#
# 実害: rmpc はプレイリストへの検索結果一括追加時に sort/window/position を
# 使い得る (findadd/searchadd と同じ grammar を共有するコマンド群であるため、
# 汎用 MPD クライアントが window でページングしたり sort で順序指定したまま
# ストアドプレイリストへ保存しようとする、あるいは特定位置へ挿入しようとする
# 呼び出しは正当な MPD 0.24+ プロトコル利用であり、現状は余分なトークンが
# `ACK incorrect arguments` になり丸ごと失敗する)。
#
# 仕様確定 (WebFetch で MusicPlayerDaemon/MPD の
# src/command/DatabaseCommands.cxx handle_searchaddpl と
# src/db/DatabasePlaylist.cxx SearchInsertIntoPlaylist を実際にソース確認):
# - POSITION は `playlistadd` (mpdplaylistaddpos-patch.py) と同じく絶対
#   インデックスのみ (add/addid/load/findadd/searchadd の相対 +N/-N とは異なり、
#   ParseQueuePosition は素の非負整数のみを受理)。
# - 対象プレイリストの現在の曲数 (POSITION 指定なしで新規作成する場合は0) を
#   超える POSITION は `ACK_ERROR_ARG` ("Bad position") で拒否 (playlistadd と
#   同一メッセージ)。`position == 曲数` (末尾) は許可。
# - sort/window は検索結果 (追加しようとしている新規トラック集合) に対して
#   適用してから POSITION の位置へ挿入する (find/search/findadd/searchadd と
#   同じ「まずソート、次にwindowで絞り込み」の順序)。
# - 引数の剥がす順序も実装に倣う: 末尾の `position POS` を先に剥がし、
#   残りへ `sort`/`window` (findadd/searchadd と共用の `_mpd_extract_sort_params`)
#   を適用してから FILTER を解釈する。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

ANCHOR = '        ``searchaddpl {NAME} {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]``'
if ANCHOR in s:
    print("searchaddpl sort/window/position already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("searchaddpl")\n'
        "def searchaddpl(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``searchaddpl {NAME} {TYPE} {WHAT} [...]``\n"
        "\n"
        "        Searches for any song that contains ``WHAT`` in tag ``TYPE`` and adds\n"
        "        them to the playlist named ``NAME``.\n"
        "\n"
        "        If a playlist by that name doesn't exist it is created.\n"
        "\n"
        "        Parameters have the same meaning as for ``find``, except that search is\n"
        "        not case sensitive.\n"
        '    """\n'
        "    parameters = list(args)\n"
        "    if not parameters:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    playlist_name = parameters.pop(0)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    _new_tracks = _mpd_filter_positives(_new_tracks, _positives, case_sensitive=False)\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "    playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "    tracks = list(playlist.tracks) + _new_tracks\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("searchaddpl")\n'
        "def searchaddpl(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``searchaddpl {NAME} {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]``\n"
        "\n"
        "        Searches for any song that contains ``WHAT`` in tag ``TYPE`` and adds\n"
        "        them to the playlist named ``NAME``.\n"
        "\n"
        "        If a playlist by that name doesn't exist it is created.\n"
        "\n"
        "        Parameters have the same meaning as for ``find``, except that search is\n"
        "        not case sensitive.\n"
        "\n"
        "        ``POSITION`` specifies where the songs will be inserted into the\n"
        "        playlist (an absolute, 0-based index; it may not exceed the\n"
        "        playlist's current length). Absent, the track(s) are appended to\n"
        "        the end of the playlist as before.\n"
        "\n"
        "    .. versionadded:: 0.24\n"
        "        The ``sort``, ``window`` and ``position`` parameters\n"
        '    """\n'
        "    parameters = list(args)\n"
        "    if not parameters:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    playlist_name = parameters.pop(0)\n"
        "\n"
        "    _position = None\n"
        '    if len(parameters) >= 2 and parameters[-2].lower() == "position":\n'
        "        _position_value = parameters[-1]\n"
        "        if not _position_value.isdigit():\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        _position = int(_position_value)\n"
        "        del parameters[-2:]\n"
        "    parameters, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(\n"
        "        parameters\n"
        "    )\n"
        "\n"
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "    playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "    old_tracks = list(playlist.tracks) if playlist else []\n"
        "    if _position is not None and _position > len(old_tracks):\n"
        '        raise exceptions.MpdArgError("Bad position")\n'
        "\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False\n"
        "    )\n"
        "    _new_tracks = _mpd_filter_positives(_new_tracks, _positives, case_sensitive=False)\n"
        "    if _sort_field:\n"
        "        _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        _new_tracks = _new_tracks[_window]\n"
        "\n"
        "    if _position is None:\n"
        "        tracks = old_tracks + _new_tracks\n"
        "    else:\n"
        "        tracks = old_tracks[:_position] + _new_tracks + old_tracks[_position:]\n"
        "\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: searchaddpl に sort/window/position (MPD0.24+) を追加 "
        "(findadd/searchadd と同じ grammar、POSITIONは playlistadd と同じ絶対インデックス)"
    )
