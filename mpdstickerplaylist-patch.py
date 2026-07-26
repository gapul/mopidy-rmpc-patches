# `sticker` (get/set/delete/list/find/inc/dec) と `stickernamestypes`/`stickertypes` は
# TYPE引数として"song"のみを受け付け、それ以外は常に`ACK Unknown sticker domain`を
# 返してしまう不具合を修正。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
# 実MPD本体(gh rawでsrc/command/StickerCommands.cxxを直接取得し確認)はMPD 0.24以降
# song/playlist/filter/タグ種別12種の4系統をサポートするが、mopidy側のバックエンドが
# ストアドプレイリスト以外(filter式マッチ・タグ値単位)のドメインに対応する実データ構造を
# 持たないため、このパッチではrmpc(mierak/rmpc)が実際に使う可能性のある最小スコープ
# として"playlist"ドメインのみを追加する(filter/タグ種別は別スコープとして対象外)。
# 実MPDのPlaylistHandler::ValidateUri(StickerCommands.cxx)はURIを
# ListPlaylistFiles()で実在チェックし、無ければstd::invalid_argumentを送出する
# (CommandError.cxxのToAck()でstd::invalid_argument→ACK_ERROR_ARG(2)に変換される、
# ACK_ERROR_NO_EXIST(50)ではない点に注意)。ただしこの検証はGet/Set/Inc/Dec/Delete/
# Listでのみ行われ、Find (DomainHandler::Find、URIはプレフィックスとして使われる)では
# 呼ばれない非対称仕様のため、find actionだけは検証をスキップする。
# また実MPDのDomainHandler::Find()はsongドメインのみ"file:"キーで結果を返し、
# 非songドメイン(playlist等)は"{sticker_type}:"キー(つまり"playlist:")で返す
# (sticker_song_find()経由のSongHandler::Findはfileキー固定のまま変更無し)。
# stickertypes/stickernamestypesもplaylistドメインを反映するよう修正
# (stickernamestypesのTYPE引数指定時のフィルタも実MPD
# (sticker/Database.cxx StickerDatabase::NamesTypes())準拠でtype列によるWHERE絞り込みへ)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_MPD_STICKER_PLAYLIST_TYPE"
if MARKER in s:
    print("sticker playlist domain support already present, skip")
else:
    old_const = '_MPD_STICKER_TYPE = "song"\n'
    assert s.count(old_const) == 1, f"old_const count={s.count(old_const)}"
    new_const = (
        '_MPD_STICKER_TYPE = "song"\n'
        '_MPD_STICKER_PLAYLIST_TYPE = "playlist"\n'
        '_MPD_STICKER_DOMAINS = (_MPD_STICKER_TYPE, _MPD_STICKER_PLAYLIST_TYPE)\n'
    )
    s = s.replace(old_const, new_const, 1)

    old_check = (
        "def _mpd_sticker_check_type(field):\n"
        "    if field != _MPD_STICKER_TYPE:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
    )
    assert s.count(old_check) == 1, f"old_check count={s.count(old_check)}"
    new_check = (
        "def _mpd_sticker_check_type(field):\n"
        "    if field not in _MPD_STICKER_DOMAINS:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
        "\n"
        "\n"
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
    )
    s = s.replace(old_check, new_check, 1)

    old_dispatch = (
        "    action, field, uri = args[0], args[1], args[2]\n"
        "    rest = list(args[3:])\n"
        "    _mpd_sticker_check_type(field)\n"
        '    if action == "list":\n'
    )
    assert s.count(old_dispatch) == 1, f"old_dispatch count={s.count(old_dispatch)}"
    new_dispatch = (
        "    action, field, uri = args[0], args[1], args[2]\n"
        "    rest = list(args[3:])\n"
        "    _mpd_sticker_check_type(field)\n"
        '    if action != "find":\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        '    if action == "list":\n'
    )
    s = s.replace(old_dispatch, new_dispatch, 1)

    old_find_result = (
        "    result = []\n"
        "    for row_uri, row_value in matches:\n"
        '        result.append(("file", row_uri))\n'
        '        result.append(("sticker", f"{name}={row_value}"))\n'
        "    return result\n"
    )
    assert s.count(old_find_result) == 1, f"old_find_result count={s.count(old_find_result)}"
    new_find_result = (
        '    key = "file" if field == _MPD_STICKER_TYPE else field\n'
        "    result = []\n"
        "    for row_uri, row_value in matches:\n"
        '        result.append((key, row_uri))\n'
        '        result.append(("sticker", f"{name}={row_value}"))\n'
        "    return result\n"
    )
    s = s.replace(old_find_result, new_find_result, 1)

    old_namestypes_fn = (
        "@_mpd_sticker_guard\n"
        "def _mpd_sticker_namestypes(context):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        rows = conn.execute(\n"
        '            "SELECT DISTINCT name FROM sticker ORDER BY name"\n'
        "        ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        "    result = []\n"
        "    for (name,) in rows:\n"
        '        result.append(("name", name))\n'
        '        result.append(("type", _MPD_STICKER_TYPE))\n'
        "    return result\n"
    )
    assert s.count(old_namestypes_fn) == 1, f"old_namestypes_fn count={s.count(old_namestypes_fn)}"
    new_namestypes_fn = (
        "@_mpd_sticker_guard\n"
        "def _mpd_sticker_namestypes(context, sticker_type=None):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        if sticker_type is None:\n"
        "            rows = conn.execute(\n"
        '                "SELECT DISTINCT name, type FROM sticker ORDER BY name, type"\n'
        "            ).fetchall()\n"
        "        else:\n"
        "            rows = conn.execute(\n"
        '                "SELECT DISTINCT name, type FROM sticker WHERE type = ? "\n'
        '                "ORDER BY name, type",\n'
        "                (sticker_type,),\n"
        "            ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        "    result = []\n"
        "    for name, type_ in rows:\n"
        '        result.append(("name", name))\n'
        '        result.append(("type", type_))\n'
        "    return result\n"
    )
    s = s.replace(old_namestypes_fn, new_namestypes_fn, 1)

    old_namestypes_call = (
        "    if sticker_type is not None:\n"
        "        _mpd_sticker_check_type(sticker_type)\n"
        "    return _mpd_sticker_namestypes(context)\n"
    )
    assert s.count(old_namestypes_call) == 1, f"old_namestypes_call count={s.count(old_namestypes_call)}"
    new_namestypes_call = (
        "    if sticker_type is not None:\n"
        "        _mpd_sticker_check_type(sticker_type)\n"
        "    return _mpd_sticker_namestypes(context, sticker_type)\n"
    )
    s = s.replace(old_namestypes_call, new_namestypes_call, 1)

    old_stickertypes_body = '    return [("stickertype", _MPD_STICKER_TYPE)]\n'
    assert s.count(old_stickertypes_body) == 1, f"old_stickertypes_body count={s.count(old_stickertypes_body)}"
    new_stickertypes_body = (
        '    return [("stickertype", t) for t in _MPD_STICKER_DOMAINS]\n'
    )
    s = s.replace(old_stickertypes_body, new_stickertypes_body, 1)

    open(p, "w").write(s)
    print("patched stickers.py: sticker playlistドメイン対応を追加")
