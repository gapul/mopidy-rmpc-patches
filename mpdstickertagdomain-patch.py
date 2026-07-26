# `sticker`系コマンド(get/set/delete/list/find/inc/dec)とstickertypes/stickernamestypesが
# TYPE引数として"song"/"playlist"の2種のみを受け付け、実MPD 0.24+が対応する
# タグ種別ドメイン(artist/album/albumartist/title/genre/composer/performer/conductor/
# work/ensemble/location/label/MUSICBRAINZ_*等17種)を送ると常に
# `ACK Unknown sticker domain`になる不具合を修正。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
# 実MPD本体(gh rawでsrc/sticker/AllowedTags.cxx/src/sticker/TagSticker.cxx/
# src/command/StickerCommands.cxxを確認)は`tag_name_parse_i()`(大文字小文字区別無し)で
# タグ名を解決し、`sticker_allowed_tags`ビットマスク(17タグ)に含まれていれば
# TagHandlerとしてディスパッチする。TagHandler::ValidateUri()は
# `TagExists(database, tag_type, uri)` (=`MakeSongFilter(tag_type, uri)`で作った
# 完全一致フィルタがDB内に1件でもヒットするか) でURI引数(=タグ値)の実在を検証し、
# 無ければ`std::invalid_argument`(CommandError.cxxのToAck()でACK_ERROR_ARG(2)、
# ACK_ERROR_NO_EXIST(50)ではない、mpdstickerplaylist-patch.pyのplaylistドメインと同じ
# コード)を送出する。mpdstickerplaylist-patch.py導入時のコメントは
# 「mopidy_ytmusicはfilter式マッチ/タグ値単位の実データ構造を持たないためタグ種別ドメインは
# 対象外」としていたが、BACKLOG.md全体検索でその根拠を再確認したところ、find/searchの
# 既存フィルタ式パーサ(music_db.py `_LIST_MAPPING`/`_LIST_NAME_MAPPING`)は既にartist/album等
# 17タグ全てをtagとして認識・backendへの`library.search(query={field:[value]})`委譲で実際に
# 値の存在確認が可能であり(mpdtagnames-patch.py/mpdtagnames2-patch.py由来)、
# 当時のスコープ外判断は誤りだったと判明。実データが無い"phantom"タグ
# (`_PHANTOM_TAG_FIELDS`、conductor/work/ensemble/location/label/
# musicbrainz_releasetrackid/musicbrainz_workid/musicbrainz_albumartistid)は
# 実データを捏造せず常に「存在しない」として扱う(既存のpoints 8/16の方針を踏襲)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_MPD_STICKER_TAG_DOMAIN_FIELDS"
if MARKER in s:
    print("sticker tag-type domain support already present, skip")
else:
    old_import = "from mopidy_mpd.protocol.music_db import _mpd_parse_window\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
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
    s = s.replace(old_import, new_import, 1)

    old_check_and_validate = (
        "def _mpd_sticker_check_type(field):\n"
        "    if field not in _MPD_STICKER_DOMAINS:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
        "\n"
        "\n"
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
        "    elif field == _MPD_STICKER_TYPE:\n"
        "        import mopidy.exceptions\n"
        "\n"
        "        try:\n"
        "            lookup_res = context.core.library.lookup(uris=[uri]).get()\n"
        "        except mopidy.exceptions.ValidationError:\n"
        "            # uri がスキーム無し等で mopidy の URI として不正な場合。\n"
        "            # mpdrawuriguard-patch.py と同じ扱いで「そんな曲は無い」に丸める。\n"
        "            lookup_res = {}\n"
        "        if not any(lookup_res.values()):\n"
        '            raise exceptions.MpdNoExistError(f"no such song: {uri}")\n'
    )
    assert s.count(old_check_and_validate) == 1, (
        f"old_check_and_validate count={s.count(old_check_and_validate)}"
    )
    new_check_and_validate = (
        "# 実MPD(sticker/AllowedTags.cxx)のsticker_allowed_tags(17タグ)。\n"
        "# music_db.pyの_LIST_MAPPING/_LIST_NAME_MAPPINGが使うbackendフィールド名で表す。\n"
        "_MPD_STICKER_TAG_DOMAIN_FIELDS = (\n"
        '    "artist", "album", "albumartist", "track_name", "genre", "composer",\n'
        '    "performer", "conductor", "work", "ensemble", "location", "label",\n'
        '    "musicbrainz_artistid", "musicbrainz_albumid", "musicbrainz_albumartistid",\n'
        '    "musicbrainz_releasetrackid", "musicbrainz_workid",\n'
        ")\n"
        "_MPD_STICKER_TAG_DOMAIN_NAMES = tuple(\n"
        "    _LIST_NAME_MAPPING[f] for f in _MPD_STICKER_TAG_DOMAIN_FIELDS\n"
        ")\n"
        "_MPD_STICKER_TAG_FIELD_BY_NAME = dict(\n"
        "    zip(_MPD_STICKER_TAG_DOMAIN_NAMES, _MPD_STICKER_TAG_DOMAIN_FIELDS)\n"
        ")\n"
        "\n"
        "\n"
        "def _mpd_sticker_resolve_domain(field):\n"
        "    # song/playlistは実MPD同様、大文字小文字を区別する厳密一致\n"
        "    # (StringIsEqual)。タグ種別のみtag_name_parse_i()相当で大文字小文字を\n"
        "    # 区別せずに解決し、canonical名(例: \"Artist\")へ正規化して返す。\n"
        "    if field in _MPD_STICKER_DOMAINS:\n"
        "        return field\n"
        "    backend_field = _LIST_MAPPING.get(field.lower())\n"
        "    if backend_field in _MPD_STICKER_TAG_DOMAIN_FIELDS:\n"
        "        return _LIST_NAME_MAPPING[backend_field]\n"
        '    raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
        "\n"
        "\n"
        "def _mpd_sticker_tag_exists(context, backend_field, value):\n"
        "    # _PHANTOM_TAG_FIELDS(mpdtagnames-patch.py導入)はタグ名として認識は\n"
        "    # されるがbackend(mopidy_ytmusic)に対応する実データが無いフィールドの\n"
        "    # ため、TagExists()相当の存在チェックを行う実データがそもそも無く、\n"
        "    # 実在すると偽装せず常に「存在しない」として扱う。\n"
        "    if backend_field in _PHANTOM_TAG_FIELDS:\n"
        "        return False\n"
        "    results = context.core.library.search(\n"
        "        query={backend_field: [value]}, exact=True\n"
        "    ).get()\n"
        "    return bool(\n"
        "        _get_tracks(results) or _get_albums(results) or _get_artists(results)\n"
        "    )\n"
        "\n"
        "\n"
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
        "    elif field == _MPD_STICKER_TYPE:\n"
        "        import mopidy.exceptions\n"
        "\n"
        "        try:\n"
        "            lookup_res = context.core.library.lookup(uris=[uri]).get()\n"
        "        except mopidy.exceptions.ValidationError:\n"
        "            # uri がスキーム無し等で mopidy の URI として不正な場合。\n"
        "            # mpdrawuriguard-patch.py と同じ扱いで「そんな曲は無い」に丸める。\n"
        "            lookup_res = {}\n"
        "        if not any(lookup_res.values()):\n"
        '            raise exceptions.MpdNoExistError(f"no such song: {uri}")\n'
        "    elif field in _MPD_STICKER_TAG_FIELD_BY_NAME:\n"
        "        backend_field = _MPD_STICKER_TAG_FIELD_BY_NAME[field]\n"
        "        if not _mpd_sticker_tag_exists(context, backend_field, uri):\n"
        '            raise exceptions.MpdArgError(f"no such {field}: {uri}")\n'
    )
    s = s.replace(old_check_and_validate, new_check_and_validate, 1)

    old_dispatch_head = (
        "    action, field, uri = args[0], args[1], args[2]\n"
        "    rest = list(args[3:])\n"
        "    _mpd_sticker_check_type(field)\n"
        '    if action == "list":\n'
    )
    assert s.count(old_dispatch_head) == 1, f"old_dispatch_head count={s.count(old_dispatch_head)}"
    new_dispatch_head = (
        "    action, field, uri = args[0], args[1], args[2]\n"
        "    rest = list(args[3:])\n"
        "    field = _mpd_sticker_resolve_domain(field)\n"
        '    if action == "list":\n'
    )
    s = s.replace(old_dispatch_head, new_dispatch_head, 1)

    old_namestypes_call = (
        "    if sticker_type is not None:\n"
        "        _mpd_sticker_check_type(sticker_type)\n"
        "    return _mpd_sticker_namestypes(context, sticker_type)\n"
    )
    assert s.count(old_namestypes_call) == 1, f"old_namestypes_call count={s.count(old_namestypes_call)}"
    new_namestypes_call = (
        "    if sticker_type is not None:\n"
        "        sticker_type = _mpd_sticker_resolve_domain(sticker_type)\n"
        "    return _mpd_sticker_namestypes(context, sticker_type)\n"
    )
    s = s.replace(old_namestypes_call, new_namestypes_call, 1)

    old_stickertypes_body = (
        '    return [("stickertype", t) for t in _MPD_STICKER_DOMAINS]\n'
    )
    assert s.count(old_stickertypes_body) == 1, f"old_stickertypes_body count={s.count(old_stickertypes_body)}"
    new_stickertypes_body = (
        '    return [("stickertype", t) for t in _MPD_STICKER_DOMAINS] + [\n'
        '        ("stickertype", name) for name in _MPD_STICKER_TAG_DOMAIN_NAMES\n'
        "    ]\n"
    )
    s = s.replace(old_stickertypes_body, new_stickertypes_body, 1)

    open(p, "w").write(s)
    print("patched stickers.py: sticker タグ種別ドメイン対応を追加")
