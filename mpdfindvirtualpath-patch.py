# rmpcのDirectoriesペインでディレクトリを選択して「Save to playlist」/
# 「Create playlist」/「Add to playlist」/「Delete from playlist」等を実行すると
# 常に0曲扱いになる不具合を修正。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが(general-purposeサブエージェントへの調査委任を2段階
# 経て)新規発見。BACKLOG.mdを"list_songs_in_item"/"directories.rs"/
# "Tag::File.*StartsWith"/"find file"等で検索し既出・却下記録が無いことを
# 確認済み。
#
# 原因: mierak/rmpcをgit cloneして確認したrmpc/src/ui/panes/directories.rs
# のlist_songs_in_item()は、選択項目がディレクトリ(非プレイリスト)の場合
# `client.find(&[Filter::new_with_kind(Tag::File, &full_path,
# FilterKind::StartsWith)])` つまり `find "(File starts_with '<full_path>')"`
# を発行し、full_pathにはlsinfoの`directory:`行の値をそのまま使う。実MPD
# (ローカルファイル)ではdirectory:の値がfile:タグの値と同じファイルパス
# 階層を共有するためこの前方一致は正しく機能するが、mopidy_mpd側の
# dispatcher.py MpdContext.browse()(291行目〜)が生成する`path`は
# `"/".join([base_path, ref.name...])`という表示名から合成した仮想パス
# (例: "YouTube Music/Home/Quick picks")であり、mopidy_ytmusicのtrack.uri
# (例: "ytmusic:track:VIDEOID")とは無関係。music_db.pyの`file`/`filename`
# タグは_LIST_MAPPING/_SEARCH_MAPPINGで"uri"フィールドへ写像され
# (_mpd_negative_field_values等はtrack.uriそのものと文字列比較する)、
# 仮想パスは実URIの前方一致に絶対一致しないため、対応するbackend検索
# (context.core.library.search(query={"uri": [full_path]}))も0件、
# ローカルのpositives再検証も0件のまま常にOK(0行)を返してしまう。
#
# 実機確認(dev mopidy, TCP 6601, mopidy-ytmusic実アカウント):
#   lsinfo "YouTube Music/Home/Quick picks"
#     → 9曲 (file: ytmusic:track:... 等、正常表示)
#   find "(File starts_with 'YouTube Music/Home/Quick picks')"
#     → OK (0件)
#
# 修正方針: dispatcher.py MpdContext.browse()は表示パス文字列から実URIへの
# 解決(_uri_map経由のキャッシュ、無ければpart-by-partのlibrary.browse()
# 再帰的解決)を既に実装済みで、context.browse(path, recursive=True,
# lookup=True)は指定パス配下の全トラックをlookup future付きで再帰的に
# yieldする(listallinfo()と全く同じ消費パターン)。find()のsole positive
# (mpdgenrepositivetrust-patch.py以来繰り返し使われている「唯一の肯定条件
# のときだけ特別扱いする」パターンと同型)がuri/starts_with(_cs/_ci)、
# かつnegativesが無い場合に限り、backend検索を丸投げする代わりに
# context.browse()で仮想パスを実URIツリーへ解決し配下の実トラックを
# 直接収集する。解決に失敗した場合(値がそもそも仮想パスとして存在しない
# =実URIのリテラル前方一致等の別用途)はNoneを返し、従来の生文字列前方
# 一致(既存の全経路、複合条件クエリ含む)へ無変更でフォールバックする
# ため退行リスクが無い。current_playlist.py(playlistfind/playlistsearch、
# 既にロード済みのtracklistをローカルの_pf_matches()で判定するだけで
# backend検索を呼ばない)やstored_playlists.py(searchplaylist、同様)は
# この不具合と無関係なため対象外。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdfindvirtualpath-patch"
if MARKER in s:
    print("findのディレクトリ仮想パス解決は既に適用済み、skip")
else:
    old_find = '''@protocol.commands.add("find")
def find(context, *args):
    """
    *musicpd.org, music database section:*

        ``find {TYPE} {WHAT}``

        Finds songs in the db that are exactly ``WHAT``. ``TYPE`` can be any
        tag supported by MPD, or one of the two special parameters - ``file``
        to search by full path (relative to database root), and ``any`` to
        match against all available tags. ``WHAT`` is what to find.

    *GMPC:*

    - also uses ``find album "[ALBUM]" artist "[ARTIST]"`` to list album
      tracks.

    *ncmpc:*

    - capitalizes the type argument.

    *ncmpcpp:*

    - also uses the search type "date".
    - uses "file" instead of "filename".
    """
    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        return
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)

    results = context.core.library.search(
        query=query, exact=_mpd_backend_search_exact(True, _positives)
    ).get()
    result_tracks = []
    if (
        "artist" not in query
        and "albumartist" not in query
        and "composer" not in query
        and "performer" not in query
    ):
        result_tracks += [_artist_as_track(a) for a in _get_artists(results)]
    if "album" not in query:
        result_tracks += [_album_as_track(a) for a in _get_albums(results)]
    result_tracks += _get_tracks(results)
    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=True)
    result_tracks = _mpd_filter_positives(result_tracks, _positives, case_sensitive=True)
    if _sort_field:
        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)
    if _window is not None:
        result_tracks = result_tracks[_window]
    return translator.tracks_to_mpd_format(
        result_tracks, context.session.tagtypes
    )'''
    assert s.count(old_find) == 1, f"old_find count={s.count(old_find)}"

    new_find = '''def _mpd_resolve_virtual_path_tracks(context, negatives, positives):  # mpdfindvirtualpath-patch
    """rmpcのDirectoriesペインが送る`find "(File starts_with \\'<仮想パス>\\')"`
    (sole positive、uri/starts_with系)専用: lsinfo等が返す表示パスを
    dispatcher.MpdContext.browse()の既存解決経路で実URIツリーへ変換し、
    配下の実トラックを直接収集する。解決できない(=仮想パスとして存在
    しない、実URIのリテラル前方一致等)場合はNoneを返し呼び出し側は
    従来の生文字列前方一致へフォールバックする。"""
    if negatives or len(positives) != 1:
        return None
    field, kind, value = positives[0]
    if field != "uri" or kind not in ("starts_with", "starts_with_cs", "starts_with_ci"):
        return None
    try:
        entries = list(context.browse(value, recursive=True, lookup=True))
    except exceptions.MpdNoExistError:
        return None
    tracks = []
    for _, lookup_future in entries:
        if lookup_future is None or lookup_future == ():
            continue
        for track_list in lookup_future.get().values():
            if track_list:
                tracks.append(track_list[0])
    return tracks


@protocol.commands.add("find")
def find(context, *args):
    """
    *musicpd.org, music database section:*

        ``find {TYPE} {WHAT}``

        Finds songs in the db that are exactly ``WHAT``. ``TYPE`` can be any
        tag supported by MPD, or one of the two special parameters - ``file``
        to search by full path (relative to database root), and ``any`` to
        match against all available tags. ``WHAT`` is what to find.

    *GMPC:*

    - also uses ``find album "[ALBUM]" artist "[ARTIST]"`` to list album
      tracks.

    *ncmpc:*

    - capitalizes the type argument.

    *ncmpcpp:*

    - also uses the search type "date".
    - uses "file" instead of "filename".
    """
    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        return
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)

    _mpdvpath_tracks = _mpd_resolve_virtual_path_tracks(context, _negatives, _positives)
    if _mpdvpath_tracks is not None:
        result_tracks = _mpdvpath_tracks
        if _sort_field:
            result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)
        if _window is not None:
            result_tracks = result_tracks[_window]
        return translator.tracks_to_mpd_format(
            result_tracks, context.session.tagtypes
        )

    results = context.core.library.search(
        query=query, exact=_mpd_backend_search_exact(True, _positives)
    ).get()
    result_tracks = []
    if (
        "artist" not in query
        and "albumartist" not in query
        and "composer" not in query
        and "performer" not in query
    ):
        result_tracks += [_artist_as_track(a) for a in _get_artists(results)]
    if "album" not in query:
        result_tracks += [_album_as_track(a) for a in _get_albums(results)]
    result_tracks += _get_tracks(results)
    result_tracks = _mpd_filter_negatives(result_tracks, _negatives, case_sensitive=True)
    result_tracks = _mpd_filter_positives(result_tracks, _positives, case_sensitive=True)
    if _sort_field:
        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)
    if _window is not None:
        result_tracks = result_tracks[_window]
    return translator.tracks_to_mpd_format(
        result_tracks, context.session.tagtypes
    )'''
    s = s.replace(old_find, new_find, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: find()にディレクトリ仮想パス→実URIツリー解決を追加"
        "(sole positive uri/starts_with限定、rmpc Directoriesペインのディレクトリ"
        "一括操作が0曲扱いになる不具合を修正)"
    )
