# mpdsticker-patch.py が実装した `sticker` は `action, field, uri, name=None, value=None` の
# 固定引数のため、`sticker find TYPE URI NAME` の基本形しか受け付けない。rmpc 本体
# (mierak/rmpc) を実際に clone して調査したところ、rmpc-mpd/src/mpd_client.rs の
# send_find_stickers が StickerFindOptions{filter, sort, window} から
# `sticker find song URI NAME [OP VALUE] [sort TYPE] [window START:END]` を組み立てて送信し、
# 実際に (1) rmpc/src/ui/panes/search/mod.rs の検索ペインの評価(rating: eq/gt/lt 整数比較)・
# お気に入り(liked: eq 整数比較)フィルタ、(2) rmpc/src/ui/panes/recently_played.rs の
# 「最近再生」ペイン (sort value_int/value + window でページング) の両方で使われており、
# 固定引数のままだと余分なトークンで `ACK wrong number of arguments` になり機能が丸ごと
# 失敗する。musicpd.org protocol docs と実 MPD (MusicPlayerDaemon/MPD
# src/command/StickerCommands.cxx handle_sticker) を実際に clone してソース確認し仕様を確定:
#   sticker find {TYPE} {URI} {NAME} [OP VALUE] [sort {SORTTYPE}] [window {START:END}]
#   OP: 文字列比較 `=`/`<`/`>`、整数比較 `eq`/`lt`/`gt`、`contains`/`starts_with`
#   sort: `uri`/`value`/`value_int` (先頭 `-` で降順)、window は他コマンドと同じ `START:END`
# mopidy_mpd の Commands.add() は "*args may not be combined with regular arguments" のため
# 固定引数のままでは可変長を扱えず、`find`/`playlistfind` 等と同じ `def sticker(context, *args)`
# へ変更した上で action ごとに手動で引数を切り出す方式に書き換える必要がある。window は
# mpdwindow-patch が music_db.py に用意した `_mpd_parse_window` をそのまま import して再利用。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpd_sticker_find_ext"
if MARKER in s:
    print("sticker find extended syntax support already present, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = old_import + (
        "from mopidy_mpd.protocol.music_db import _mpd_parse_window\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_find_func = (
        "def _mpd_sticker_find(context, field, uri, name):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        '        rows = conn.execute(\n'
        '            "SELECT uri, value FROM sticker WHERE type = ? AND name = ?",\n'
        "            (field, name),\n"
        "        ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        "    result = []\n"
        "    for row_uri, value in sorted(rows):\n"
        "        if uri and not row_uri.startswith(uri):\n"
        "            continue\n"
        '        result.append(("file", row_uri))\n'
        '        result.append(("sticker", f"{name}={value}"))\n'
        "    return result\n"
    )
    assert s.count(old_find_func) == 1, f"old_find_func count={s.count(old_find_func)}"

    new_find_func = (
        '_MPD_STICKER_SORT_FIELDS = ("uri", "value", "value_int")\n'
        "\n"
        "_MPD_STICKER_OPERATORS = {\n"
        '    "=", "<", ">", "eq", "lt", "gt", "contains", "starts_with",\n'
        "}\n"
        "\n"
        "\n"
        "def _mpd_sticker_as_int(value):\n"
        "    try:\n"
        "        return int(value)\n"
        "    except ValueError:\n"
        "        return 0\n"
        "\n"
        "\n"
        "def _mpd_sticker_match(op, value, needle):\n"
        '    if op == "=":\n'
        "        return value == needle\n"
        '    if op == "<":\n'
        "        return value < needle\n"
        '    if op == ">":\n'
        "        return value > needle\n"
        '    if op == "contains":\n'
        "        return needle in value\n"
        '    if op == "starts_with":\n'
        "        return value.startswith(needle)\n"
        "    a, b = _mpd_sticker_as_int(value), _mpd_sticker_as_int(needle)\n"
        '    if op == "eq":\n'
        "        return a == b\n"
        '    if op == "lt":\n'
        "        return a < b\n"
        "    return a > b\n"
        "\n"
        "\n"
        "def _mpd_sticker_find_ext(\n"
        "    context, field, uri, name, op, value, sort_field, descending, window\n"
        "):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        rows = conn.execute(\n"
        '            "SELECT uri, value FROM sticker WHERE type = ? AND name = ?",\n'
        "            (field, name),\n"
        "        ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        "\n"
        "    matches = []\n"
        "    for row_uri, row_value in rows:\n"
        "        if uri and not row_uri.startswith(uri):\n"
        "            continue\n"
        "        if op is not None and not _mpd_sticker_match(op, row_value, value):\n"
        "            continue\n"
        "        matches.append((row_uri, row_value))\n"
        "\n"
        "    if sort_field == \"uri\":\n"
        "        matches.sort(key=lambda m: m[0], reverse=descending)\n"
        '    elif sort_field == "value":\n'
        "        matches.sort(key=lambda m: m[1], reverse=descending)\n"
        '    elif sort_field == "value_int":\n'
        "        matches.sort(\n"
        "            key=lambda m: _mpd_sticker_as_int(m[1]), reverse=descending\n"
        "        )\n"
        "    else:\n"
        "        matches.sort()\n"
        "\n"
        "    if window is not None:\n"
        "        matches = matches[window]\n"
        "\n"
        "    result = []\n"
        "    for row_uri, row_value in matches:\n"
        '        result.append(("file", row_uri))\n'
        '        result.append(("sticker", f"{name}={row_value}"))\n'
        "    return result\n"
    )
    s = s.replace(old_find_func, new_find_func, 1)

    old_sticker_cmd = (
        '@protocol.commands.add("sticker", list_command=False)\n'
        "def sticker(context, action, field, uri, name=None, value=None):\n"
        '    """\n'
        "    *musicpd.org, sticker section:*\n"
        "\n"
        "        ``sticker list {TYPE} {URI}``\n"
        "\n"
        "        Lists the stickers for the specified object.\n"
        "\n"
        "        ``sticker find {TYPE} {URI} {NAME}``\n"
        "\n"
        "        Searches the sticker database for stickers with the specified name,\n"
        "        below the specified directory (``URI``). For each matching song, it\n"
        "        prints the ``URI`` and that one sticker's value.\n"
        "\n"
        "        ``sticker get {TYPE} {URI} {NAME}``\n"
        "\n"
        "        Reads a sticker value for the specified object.\n"
        "\n"
        "        ``sticker set {TYPE} {URI} {NAME} {VALUE}``\n"
        "\n"
        "        Adds a sticker value to the specified object. If a sticker item\n"
        "        with that name already exists, it is replaced.\n"
        "\n"
        "        ``sticker delete {TYPE} {URI} [NAME]``\n"
        "\n"
        "        Deletes a sticker value from the specified object. If you do not\n"
        "        specify a sticker name, all sticker values are deleted.\n"
        "\n"
        '    """\n'
        "    _mpd_sticker_check_type(field)\n"
        '    if action == "list":\n'
        "        return _mpd_sticker_list(context, field, uri)\n"
        '    elif action == "find":\n'
        "        if name is None:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        return _mpd_sticker_find(context, field, uri, name)\n"
        '    elif action == "get":\n'
        "        if name is None:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        return _mpd_sticker_get(context, field, uri, name)\n"
        '    elif action == "set":\n'
        "        if name is None or value is None:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        _mpd_sticker_set(context, field, uri, name, value)\n"
        "        return None\n"
        '    elif action == "delete":\n'
        "        _mpd_sticker_delete(context, field, uri, name)\n"
        "        return None\n"
        "    else:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker action: {action}")\n'
    )
    assert s.count(old_sticker_cmd) == 1, f"old_sticker_cmd count={s.count(old_sticker_cmd)}"

    new_sticker_cmd = (
        '@protocol.commands.add("sticker", list_command=False)\n'
        "def sticker(context, *args):\n"
        '    """\n'
        "    *musicpd.org, sticker section:*\n"
        "\n"
        "        ``sticker list {TYPE} {URI}``\n"
        "\n"
        "        Lists the stickers for the specified object.\n"
        "\n"
        "        ``sticker find {TYPE} {URI} {NAME} [{OP} {VALUE}] "
        "[sort {SORTTYPE}] [window {START:END}]``\n"
        "\n"
        "        Searches the sticker database for stickers with the specified name,\n"
        "        below the specified directory (``URI``). For each matching song, it\n"
        "        prints the ``URI`` and that one sticker's value. OP is one of\n"
        '        ``=``/``<``/``>`` (string comparison) or ``eq``/``lt``/``gt``\n'
        "        (integer comparison) or ``contains``/``starts_with``. SORTTYPE is\n"
        '        one of ``uri``/``value``/``value_int`` (prefix with ``-`` for\n'
        "        descending order).\n"
        "\n"
        "        ``sticker get {TYPE} {URI} {NAME}``\n"
        "\n"
        "        Reads a sticker value for the specified object.\n"
        "\n"
        "        ``sticker set {TYPE} {URI} {NAME} {VALUE}``\n"
        "\n"
        "        Adds a sticker value to the specified object. If a sticker item\n"
        "        with that name already exists, it is replaced.\n"
        "\n"
        "        ``sticker delete {TYPE} {URI} [NAME]``\n"
        "\n"
        "        Deletes a sticker value from the specified object. If you do not\n"
        "        specify a sticker name, all sticker values are deleted.\n"
        "\n"
        '    """\n'
        "    if len(args) < 3:\n"
        '        raise exceptions.MpdArgError("wrong number of arguments")\n'
        "    action, field, uri = args[0], args[1], args[2]\n"
        "    rest = list(args[3:])\n"
        "    _mpd_sticker_check_type(field)\n"
        '    if action == "list":\n'
        "        if rest:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        return _mpd_sticker_list(context, field, uri)\n"
        '    elif action == "get":\n'
        "        if len(rest) != 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        return _mpd_sticker_get(context, field, uri, rest[0])\n"
        '    elif action == "set":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_set(context, field, uri, rest[0], rest[1])\n"
        "        return None\n"
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        return None\n"
        '    elif action == "find":\n'
        "        if not rest:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        name = rest[0]\n"
        "        tail = rest[1:]\n"
        "\n"
        "        window = None\n"
        '        if len(tail) >= 2 and tail[-2].lower() == "window":\n'
        "            window = _mpd_parse_window(tail[-1])\n"
        "            tail = tail[:-2]\n"
        "\n"
        "        sort_field = None\n"
        "        descending = False\n"
        '        if len(tail) >= 2 and tail[-2].lower() == "sort":\n'
        "            sort_value = tail[-1]\n"
        '            descending = sort_value.startswith("-")\n'
        "            sort_type = sort_value[1:] if descending else sort_value\n"
        "            if sort_type not in _MPD_STICKER_SORT_FIELDS:\n"
        "                raise exceptions.MpdArgError(\n"
        '                    f"Unknown sort type: {sort_type}"\n'
        "                )\n"
        "            sort_field = sort_type\n"
        "            tail = tail[:-2]\n"
        "\n"
        "        op = None\n"
        "        op_value = None\n"
        "        if len(tail) == 2:\n"
        "            op, op_value = tail\n"
        "            if op not in _MPD_STICKER_OPERATORS:\n"
        "                raise exceptions.MpdArgError(\n"
        '                    f"Unknown sticker operator: {op}"\n'
        "                )\n"
        "        elif tail:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
        "        return _mpd_sticker_find_ext(\n"
        "            context, field, uri, name, op, op_value,\n"
        "            sort_field, descending, window,\n"
        "        )\n"
        "    else:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker action: {action}")\n'
    )
    s = s.replace(old_sticker_cmd, new_sticker_cmd, 1)

    open(p, "w").write(s)
    print(
        "patched stickers.py: sticker find に比較演算子(=/</>/eq/lt/gt/contains/"
        "starts_with)とsort/window修飾を追加"
    )
