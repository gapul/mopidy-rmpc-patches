# mpdsticker-patch.py が実装した sticker コマンド群 (list/find/get/set/delete) は MPD 0.15
# 時点の基本セットのみで、MPD 0.24 で追加された `sticker inc`/`sticker dec` および
# `stickernames`/`stickertypes`/`stickernamestypes` (musicpd.org protocol, sticker section) が
# 丸ごと欠落している。TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが
# mopidy_mpd 側の未対応コマンドを再洗い出しして選定 (mpd.readthedocs.io の protocol
# リファレンスと 実MPD MusicPlayerDaemon/MPD src/command/StickerCommands.cxx を実際に
# fetch してソース/仕様を確認)。
#
# 確認した仕様:
#   sticker inc {TYPE} {URI} {NAME} {VALUE}
#   sticker dec {TYPE} {URI} {NAME} {VALUE}
#     既存stickerに VALUE を加算/減算する (無ければ VALUE で新規作成、実MPD Database.cxx の
#     IncValue/DecValue は `INSERT ... ON CONFLICT DO UPDATE SET value = value +/- ?` という
#     単一SQLで新規作成と加減算を両立している。本パッチも同じSQLパターンで踏襲)。
#     名前が空文字列だと実MPDは "empty sticker name" でACKエラーになる。
#     成功時は sticker set/delete と同様レスポンス無し(OKのみ)。
#   stickernames
#     登録済みsticker名のユニーク一覧を `name: NAME` で返す (実MPD StickerCommands.cxx
#     handle_sticker_names → DomainHandler::Names() は "name: " prefix)。
#   stickertypes
#     利用可能なsticker対象タイプを `stickertype: TYPE` で返す。実MPDは
#     filter/playlist/song + 許可タグ名まで固定で返すが、本実装(mopidy_mpd+本パッチ群)は
#     _mpd_sticker_check_type が "song" 以外を一律 "Unknown sticker domain" で拒否する通り
#     song タイプしか実装していないため、実装と矛盾しないよう `stickertype: song` のみ返す
#     (mpdstats-patch.py の songs/db_playtime 未実装や mpdlistfiles-patch.py の
#     size/Last-Modified省略と同種の、実装範囲を偽らない割り切り)。
#   stickernamestypes [TYPE]
#     sticker名とタイプのペアを `name: NAME` / `type: TYPE` で返す。TYPE省略時は全件、
#     指定時はそのタイプのみ (実MPDは song/playlist/filter/タグ名を受け付けるが、本実装は
#     song タイプのみ実装のため TYPE指定時は _mpd_sticker_check_type と同じ基準で検証)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpd_sticker_inc_dec"
if MARKER in s:
    print("sticker inc/dec/names/types already present, skip")
else:
    old_anchor = '@protocol.commands.add("sticker", list_command=False)\ndef sticker(context, *args):\n'
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"

    new_helpers = (
        "def _mpd_sticker_names(context):\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        rows = conn.execute(\n"
        '            "SELECT DISTINCT name FROM sticker ORDER BY name"\n'
        "        ).fetchall()\n"
        "    finally:\n"
        "        conn.close()\n"
        '    return [("name", name) for (name,) in rows]\n'
        "\n"
        "\n"
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
        "\n"
        "\n"
        "def _mpd_sticker_inc_dec(context, field, uri, name, value, sign):\n"
        "    if not name:\n"
        '        raise exceptions.MpdArgError("empty sticker name")\n'
        "    try:\n"
        "        delta = int(value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError(f"invalid sticker value: {value}")\n'
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        conn.execute(\n"
        '            "INSERT INTO sticker (type, uri, name, value) VALUES (?, ?, ?, ?) "\n'
        '            f"ON CONFLICT(type, uri, name) DO UPDATE SET "\n'
        '            f"value = CAST(value AS INTEGER) {sign} ?",\n'
        "            (field, uri, name, str(delta), delta),\n"
        "        )\n"
        "        conn.commit()\n"
        "    finally:\n"
        "        conn.close()\n"
        "\n"
        "\n"
    )
    s = s.replace(old_anchor, new_helpers + old_anchor, 1)

    old_dispatch = (
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
        '    elif action == "find":\n'
    )
    assert s.count(old_dispatch) == 1, f"old_dispatch count={s.count(old_dispatch)}"
    new_dispatch = (
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
        '    elif action == "inc":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "+")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
        '    elif action == "dec":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "-")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
        '    elif action == "find":\n'
    )
    s = s.replace(old_dispatch, new_dispatch, 1)

    old_tail = (
        "    else:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker action: {action}")\n'
    )
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = old_tail + (
        "\n"
        "\n"
        '@protocol.commands.add("stickernames")\n'
        "def stickernames(context):\n"
        '    """\n'
        "    *mpd.readthedocs.io, sticker section:*\n"
        "\n"
        "        ``stickernames``\n"
        "\n"
        "        Gets a list of unique sticker names.\n"
        '    """\n'
        "    return _mpd_sticker_names(context)\n"
        "\n"
        "\n"
        '@protocol.commands.add("stickertypes")\n'
        "def stickertypes(context):\n"
        '    """\n'
        "    *mpd.readthedocs.io, sticker section:*\n"
        "\n"
        "        ``stickertypes``\n"
        "\n"
        "        Shows a list of available sticker types.\n"
        '    """\n'
        '    return [("stickertype", _MPD_STICKER_TYPE)]\n'
        "\n"
        "\n"
        '@protocol.commands.add("stickernamestypes")\n'
        "def stickernamestypes(context, sticker_type=None):\n"
        '    """\n'
        "    *mpd.readthedocs.io, sticker section:*\n"
        "\n"
        "        ``stickernamestypes [TYPE]``\n"
        "\n"
        "        Gets a list of unique sticker names and their types.\n"
        '    """\n'
        "    if sticker_type is not None:\n"
        "        _mpd_sticker_check_type(sticker_type)\n"
        "    return _mpd_sticker_namestypes(context)\n"
    )
    s = s.replace(old_tail, new_tail, 1)

    open(p, "w").write(s)
    print(
        "patched stickers.py: sticker inc/dec と "
        "stickernames/stickertypes/stickernamestypes (MPD0.24+) を追加"
    )
