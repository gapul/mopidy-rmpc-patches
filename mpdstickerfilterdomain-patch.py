# `sticker`系コマンド(get/set/delete/list/find/inc/dec)とstickertypes/stickernamestypesが
# 実MPD 0.24+の4つ目のドメインである"filter"(URI引数をMPDフィルタ式としてパースし、
# DB内に1件でもマッチすればそのフィルタ式文字列自体をstickerのキーとして扱うドメイン)を
# 一切受け付けず、常に`ACK Unknown sticker domain: filter`になる不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。song/playlist/タグ種別17種(mpdstickerplaylist-patch.py/mpdstickertagdomain-patch.py)の
# 3ドメインは既に対応済みだが、実MPD本体のドメイン一覧はもう1つ"filter"を含む。
#
# 実MPD本体(gh rawでsrc/command/StickerCommands.cxx handle_sticker()を確認)は
# `StringIsEqual(sticker_type, "filter")`をsong/playlistに続き3番目(タグ名解決より前)に
# 判定しFilterHandlerへディスパッチする。src/sticker/TagSticker.cxx MakeSongFilter()は
# `sticker_type=="filter"`の場合URIをそのままSongFilterとしてパースする
# (`filter.Parse({sticker_uri}, false)`、大文字小文字を区別する厳密パース)。
# FilterHandler::ValidateUri()(StickerCommands.cxx)はこのフィルタが
# `FilterMatches(database, filter)`(=DB内に1件でもマッチする曲があるか)を満たさなければ
# `std::invalid_argument`(CommandError.cxxのToAck()でACK_ERROR_ARG(2)、既存のplaylist/
# タグドメインと同じコード)を送出する。FilterHandler/TagHandlerはどちらもDomainHandler::Find()を
# オーバーライドしない(songのみ独自Find()でディレクトリ境界処理を持つ)ため、
# `sticker find filter <URI> ...`のURI引数はフィルタ式としてはパースされず、他の非songドメインと
# 全く同じ生のuri前方一致(sticker.db内に格納済みのキー文字列に対する`uri LIKE (?||'%')`相当)のまま
# ——mopidy_mpd側の`_mpd_sticker_find_ext`は既にfield非song時はディレクトリ境界処理を
# スキップする実装のため、find側の変更は不要。
#
# mopidy_mpdにはreal MPDの`SongFilter::ToExpression()`に相当する正規化シリアライザが無いため、
# ValidateUri相当のマッチ判定はfind()コマンドと全く同じフィルタ式パーサ/検索パイプライン
# (`_query_from_mpd_filter_expression`/`_mpd_pop_negatives`/`_mpd_pop_positives`/
# `_mpd_filter_negatives`/`_mpd_filter_positives`、いずれもmusic_db.py)を再利用して
# 「1件でも実曲がマッチするか」だけを判定し、正規化はせずクライアントが送った生の文字列を
# そのままsticker DBのキーとして扱う(簡略化)。real MPDのFilterMatches()はDB内の実曲のみを
# 対象としartist/album見出し等の合成placeholderは含まないため、find()自身が行う
# `_artist_as_track`/`_album_as_track`によるplaceholder合成は使わず`_get_tracks(results)`の
# みで判定する。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_MPD_STICKER_FILTER_TYPE"
if MARKER in s:
    print("sticker filter domain support already present, skip")
else:
    old_import = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _mpd_parse_window,\n"
        "    _LIST_MAPPING,\n"
        "    _LIST_NAME_MAPPING,\n"
        "    _PHANTOM_TAG_FIELDS,\n"
        "    _get_albums,\n"
        "    _get_artists,\n"
        "    _get_tracks,\n"
        ")\n"
    )
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _mpd_parse_window,\n"
        "    _LIST_MAPPING,\n"
        "    _LIST_NAME_MAPPING,\n"
        "    _PHANTOM_TAG_FIELDS,\n"
        "    _SEARCH_MAPPING,\n"
        "    _get_albums,\n"
        "    _get_artists,\n"
        "    _get_tracks,\n"
        "    _mpd_backend_search_exact,\n"
        "    _mpd_filter_negatives,\n"
        "    _mpd_filter_positives,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_pop_positives,\n"
        "    _query_from_mpd_filter_expression,\n"
        ")\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_domains = (
        '_MPD_STICKER_TYPE = "song"\n'
        '_MPD_STICKER_PLAYLIST_TYPE = "playlist"\n'
        "_MPD_STICKER_DOMAINS = (_MPD_STICKER_TYPE, _MPD_STICKER_PLAYLIST_TYPE)\n"
    )
    assert s.count(old_domains) == 1, f"old_domains count={s.count(old_domains)}"
    new_domains = (
        '_MPD_STICKER_TYPE = "song"\n'
        '_MPD_STICKER_PLAYLIST_TYPE = "playlist"\n'
        '_MPD_STICKER_FILTER_TYPE = "filter"\n'
        "_MPD_STICKER_DOMAINS = (\n"
        "    _MPD_STICKER_TYPE, _MPD_STICKER_PLAYLIST_TYPE, _MPD_STICKER_FILTER_TYPE,\n"
        ")\n"
    )
    s = s.replace(old_domains, new_domains, 1)

    old_validate_uri = (
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
        "    elif field == _MPD_STICKER_TYPE:\n"
    )
    assert s.count(old_validate_uri) == 1, f"old_validate_uri count={s.count(old_validate_uri)}"
    new_validate_uri = (
        "def _mpd_sticker_validate_filter(context, uri):\n"
        "    # find()と同じパイプラインでURI(=フィルタ式)を評価し、実曲へ1件も\n"
        "    # マッチしなければFilterHandler::ValidateUri()相当のACK_ERROR_ARG(2)を送出する。\n"
        "    query = _query_from_mpd_filter_expression(uri, _SEARCH_MAPPING)\n"
        "    negatives = _mpd_pop_negatives(query)\n"
        "    positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(\n"
        "        query=query, exact=_mpd_backend_search_exact(True, positives)\n"
        "    ).get()\n"
        "    result_tracks = _get_tracks(results)\n"
        "    result_tracks = _mpd_filter_negatives(\n"
        "        result_tracks, negatives, case_sensitive=True\n"
        "    )\n"
        "    result_tracks = _mpd_filter_positives(\n"
        "        result_tracks, positives, case_sensitive=True\n"
        "    )\n"
        "    if not result_tracks:\n"
        '        raise exceptions.MpdArgError(f"no matches found: {uri}")\n'
        "\n"
        "\n"
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
        "    elif field == _MPD_STICKER_FILTER_TYPE:\n"
        "        _mpd_sticker_validate_filter(context, uri)\n"
        "    elif field == _MPD_STICKER_TYPE:\n"
    )
    s = s.replace(old_validate_uri, new_validate_uri, 1)

    open(p, "w").write(s)
    print("patched stickers.py: sticker filterドメイン対応を追加")
