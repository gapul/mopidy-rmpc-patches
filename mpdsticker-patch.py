# mopidy-mpd 3.3.0 の `sticker` コマンド (get/set/delete/list/find) は未実装で
# `raise exceptions.MpdNotImplemented` のスタブのまま (rmpc の一部機能 — 例: 曲への
# メタデータ付与 — が使う)。mopidy コア自体はスティッカーの永続化機構を持たないため、
# core.data_dir 配下の sqlite ファイルに (type, uri, name) -> value を保存する形で自前実装する。
# 実装するのは musicpd.org 仕様の基本形 (sort/window や `=` 比較演算子付き find のような
# 拡張構文は対象外、既存 docstring が示す範囲のみ):
#   sticker get {TYPE} {URI} {NAME}
#   sticker set {TYPE} {URI} {NAME} {VALUE}
#   sticker delete {TYPE} {URI} [NAME]
#   sticker list {TYPE} {URI}
#   sticker find {TYPE} {URI} {NAME}
# TYPE は実際の MPD 同様 "song" のみ対応 (mopidy のライブラリはファイルシステム階層を
# 持たないため playlist/filesystem 等の他ドメインは対象外)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpd_sticker_conn"
if MARKER in s:
    print("sticker support already present, skip")
else:
    old_body = (
        "    # TODO: check that action in ('list', 'find', 'get', 'set', 'delete')\n"
        "    # TODO: check name/value matches with action\n"
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_body) == 1, f"old_body count={s.count(old_body)}"

    old_import = "from mopidy_mpd import exceptions, protocol\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"

    new_import = (
        "import sqlite3\n"
        "\n"
        "from mopidy.internal import path as _mpd_sticker_path\n"
        "from mopidy_mpd import exceptions, protocol\n"
        "\n"
        "_MPD_STICKER_TYPE = \"song\"\n"
        "\n"
        "\n"
        "def _mpd_sticker_db_path(context):\n"
        "    data_dir = _mpd_sticker_path.expand_path(\n"
        '        context.dispatcher.config["core"]["data_dir"]\n'
        "    )\n"
        '    mpd_dir = data_dir / "mpd"\n'
        "    _mpd_sticker_path.get_or_create_dir(mpd_dir)\n"
        '    return mpd_dir / "sticker.db"\n'
        "\n"
        "\n"
        "def _mpd_sticker_conn(context):\n"
        "    conn = sqlite3.connect(str(_mpd_sticker_db_path(context)))\n"
        "    conn.execute(\n"
        '        "CREATE TABLE IF NOT EXISTS sticker ("\n'
        '        "type TEXT NOT NULL, uri TEXT NOT NULL, name TEXT NOT NULL, "\n'
        '        "value TEXT NOT NULL, PRIMARY KEY (type, uri, name))"\n'
        "    )\n"
        "    return conn\n"
        "\n"
        "\n"
        "def _mpd_sticker_check_type(field):\n"
        "    if field != _MPD_STICKER_TYPE:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
        "\n"
        "\n"
        "def _mpd_sticker_list(context, field, uri):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        rows = conn.execute(\n"
        '            "SELECT name, value FROM sticker WHERE type = ? AND uri = ? "\n'
        '            "ORDER BY name",\n'
        "            (field, uri),\n"
        "        ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        '    return [("sticker", f"{name}={value}") for name, value in rows]\n'
        "\n"
        "\n"
        "def _mpd_sticker_get(context, field, uri, name):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        row = conn.execute(\n"
        '            "SELECT value FROM sticker WHERE type = ? AND uri = ? AND name = ?",\n'
        "            (field, uri, name),\n"
        "        ).fetchone()\n"
        "    finally:\n"
        "        conn.close()\n"
        "    if row is None:\n"
        '        raise exceptions.MpdNoExistError("no such sticker")\n'
        '    return [("sticker", f"{name}={row[0]}")]\n'
        "\n"
        "\n"
        "def _mpd_sticker_set(context, field, uri, name, value):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        conn.execute(\n"
        '            "INSERT INTO sticker (type, uri, name, value) VALUES (?, ?, ?, ?) "\n'
        '            "ON CONFLICT(type, uri, name) DO UPDATE SET value = excluded.value",\n'
        "            (field, uri, name, value),\n"
        "        )\n"
        "        conn.commit()\n"
        "    finally:\n"
        "        conn.close()\n"
        "\n"
        "\n"
        "def _mpd_sticker_delete(context, field, uri, name):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        if name is None:\n"
        "            cur = conn.execute(\n"
        '                "DELETE FROM sticker WHERE type = ? AND uri = ?", (field, uri)\n'
        "            )\n"
        "        else:\n"
        "            cur = conn.execute(\n"
        '                "DELETE FROM sticker WHERE type = ? AND uri = ? AND name = ?",\n'
        "                (field, uri, name),\n"
        "            )\n"
        "        conn.commit()\n"
        "        deleted = cur.rowcount\n"
        "    finally:\n"
        "        conn.close()\n"
        "    if not deleted:\n"
        '        raise exceptions.MpdNoExistError("no such sticker")\n'
        "\n"
        "\n"
        "def _mpd_sticker_find(context, field, uri, name):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        rows = conn.execute(\n"
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
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    s = s.replace(old_import, new_import, 1)

    new_body = (
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
    assert s.count(old_body) == 1, f"old_body count(after import replace)={s.count(old_body)}"
    s = s.replace(old_body, new_body, 1)

    open(p, "w").write(s)
    print("patched stickers.py: get/set/delete/list/find を sqlite 永続化で実装")
