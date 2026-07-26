# musicpd.org protocol (stored playlists section) の `searchplaylist {NAME} {FILTER}
# [window {START:END}]` (MPD 0.24+ で追加、NEWS: "new commands ... 'searchplaylist' ...")
# が mopidy_mpd 3.3.0 に丸ごと欠落しており常に `ACK unknown command` になっていた件。
# mpdplaylistlength-patch.py の調査時に mpd.readthedocs.io の protocol リファレンスと
# 照合して見つかった未実装6件 (searchcount/outputset/getfingerprint/playlistlength/
# searchplaylist/protocol) のうち、当時は「既存の肯定/否定フィルタ演算子機構との整合を
# 要し1回のパッチとしては範囲が広い」として見送られていた項目。mpdsearchcount-patch.py が
# 同じ懸念だった count の case-insensitive 版を、既存の `_mpd_count_grouped` の再利用だけで
# 単独パッチとして実装できると判明させた前例に倣い、こちらも既存機構の再利用で実装できるか
# 再調査した結果、着手可能と判断した。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/PlaylistCommands.cxx handle_searchplaylist,
# src/playlist/Print.cxx playlist_provider_search_print, src/command/AllCommands.cxx) を
# 実際に取得してソース確認し仕様を確定:
#   - `NAME` のストアドプレイリストを対象に FILTER (find/search と同じフィルタ式構文、
#     `==`/`!=`/`contains`/`starts_with`/`=~`/`!~` および旧来の TAG VALUE ペア) で
#     大文字小文字を区別せず (`search`/`playlistsearch` と同じ fold_case=true) マッチする
#     曲を返す。
#   - sort 修飾は存在しない (window のみ)。AllCommands.cxx の
#     `{ "searchplaylist", PERMISSION_READ, 2, 4, handle_searchplaylist }` で最大引数数が
#     4 に制限されている実装。
#   - StringNormalizationEnabled は一切参照していない (`playlistsearch` と異なり
#     diacritics 除去の対象外。DatabaseCommands.cxx/QueueCommands.cxx のみが
#     StringNormalizationEnabled を参照していることを gh search code で確認済み)。
#   - `Pos: N` (元のプレイリスト内での位置、0-based) が各マッチ曲に付与される
#     (`playlist_provider_search_print` の `position` はマッチの有無に関わらず
#     プレイリストの全曲を順に数えるカウンタで、window はマッチした曲の並びに対する
#     スライスとして働く)。
#
# mopidy_mpd 側の実装: listplaylistinfo/playlistlength (stored_playlists.py) と同じ
# `_get_playlist` + `context.core.library.lookup()` でプレイリストの全曲を実 Track に
# 解決し、current_playlist.py (mpdplaylistfind-patch.py/mpdnegfilter-patch.py/
# mpdfilterkind-patch.py が段階的に拡張してきた) の `_pf_matches` (query/negatives/
# positives 全対応のローカル Track マッチャ、フィルタ式の全演算子と大文字小文字の
# strict/非strictを一手に引き受ける) をそのまま import して再利用する。music_db.py の
# `_query_from_mpd_search_parameters`/`_mpd_pop_negatives`/`_mpd_pop_positives`/
# `_mpd_parse_window` も同様に再利用し、新規に書くロジックは「window のみを末尾から
# 剥がす」抽出関数 (searchplaylist は sort 非対応のため `_mpd_extract_sort_params` は
# 使わない) と、元プレイリスト内インデックスを位置として保ったままのマッチ・スライス
# 処理のみに留めた。
p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

MARKER = "_mpd_extract_window_only"
if MARKER in s:
    print("searchplaylist support already present, skip")
else:
    anchor_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(anchor_import) == 1, f"anchor_import count={s.count(anchor_import)}"
    new_import = anchor_import + (
        "from mopidy_mpd.protocol.current_playlist import _pf_matches\n"
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_parse_window,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_pop_positives,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    s = s.replace(anchor_import, new_import, 1)

    anchor_playlistlength_end = (
        "    total_length = sum(t.length for t in tracks if t.length)\n"
        "    return [\n"
        '        ("songs", len(track_uris)),\n'
        '        ("playtime", int(total_length / 1000)),\n'
        "    ]\n"
        "\n"
        "\n"
        '@protocol.commands.add("listplaylists")\n'
    )
    assert s.count(anchor_playlistlength_end) == 1, (
        f"anchor_playlistlength_end count={s.count(anchor_playlistlength_end)}"
    )

    searchplaylist_code = '''
def _mpd_extract_window_only(params):
    """末尾から `window START:END` 修飾子だけを剥がす (searchplaylist は sort 非対応の
    ため `_mpd_extract_sort_params` とは別に用意)。無ければ (params, None)。"""
    params = list(params)
    window = None
    if len(params) >= 2 and params[-2].lower() == "window":
        window = _mpd_parse_window(params[-1])
        params = params[:-2]
    return params, window


@protocol.commands.add("searchplaylist")
def searchplaylist(context, *params):
    """
    *musicpd.org, stored playlists section:*

        ``searchplaylist {NAME} {FILTER} [window {START:END}]``

        Search the playlist ``NAME.m3u`` for songs matching ``FILTER``
        (see Filters), case insensitively, like with ``search``. A range
        may be specified to list only a part of the matches.

    .. versionadded:: 0.24
        New in MPD protocol version 0.24
    """
    # `protocol.commands.add` は *args を固定引数と混在させられない
    # (playlistfind/playlistsearch と同じ制約) ため、NAME も *params から取り出す。
    if not params:
        raise exceptions.MpdArgError("wrong number of arguments")
    name, *args = params
    args, window = _mpd_extract_window_only(args)
    if not args:
        raise exceptions.MpdArgError("wrong number of arguments")
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    negatives = _mpd_pop_negatives(query)
    positives = _mpd_pop_positives(query)
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")

    playlist = _get_playlist(context, name)
    track_uris = [track.uri for track in playlist.tracks]
    tracks_map = context.core.library.lookup(uris=track_uris).get()

    matches = []
    for position, uri in enumerate(track_uris):
        for track in tracks_map.get(uri, []):
            if _pf_matches(
                track, query, strict=False, negatives=negatives, positives=positives
            ):
                matches.append((position, track))
    if window is not None:
        matches = matches[window]

    result = []
    for position, track in matches:
        formatted = translator.track_to_mpd_format(track, context.session.tagtypes)
        if not formatted:
            continue
        result.append(formatted + [("Pos", position)])
    return result


'''
    listplaylists_marker = '@protocol.commands.add("listplaylists")\n'
    before_marker = anchor_playlistlength_end[: -len(listplaylists_marker)]
    assert anchor_playlistlength_end == before_marker + listplaylists_marker
    s = s.replace(
        anchor_playlistlength_end,
        before_marker + searchplaylist_code.lstrip("\n") + listplaylists_marker,
        1,
    )

    open(p, "w").write(s)
    print("patched stored_playlists.py: searchplaylist (MPD 0.24+) を追加")
