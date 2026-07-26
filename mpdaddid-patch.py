# mopidy-mpd 3.3.0 の `addid` は POSITION として絶対位置 (protocol.UINT) のみ
# 受け付け、実 MPD 0.23+ が対応する相対位置 (`+N`/`-N`、現在再生中の曲を基準にした
# オフセット) は未対応だった (数値以外を渡すと ValueError → ACK incorrect arguments)。
#
# 実 MPD の src/command/PositionArg.cxx ParseInsertPosition() 相当のロジックを移植:
#   - 接頭辞なし: 絶対位置 (0 <= N <= queue_length)
#   - `+N`: 現在再生中の曲の直後を 0 としたオフセット (`+0` で直後に挿入)。
#     current + 1 + N (0 <= N <= queue_length - current - 1)
#   - `-N`: 現在再生中の曲の直前を 0 としたオフセット (`-0` で直前に挿入)。
#     current - N (0 <= N <= current)
# 相対位置指定時に再生中の曲が無ければ実 MPD 同様 ACK_ERROR_PLAYER_SYNC(55)
# "No current song" を返す。絶対位置指定の既存の範囲外エラー文言 ("Bad song index")
# は後方互換のため変更しない。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "_mpd_addid_position"
if MARKER in s:
    print("addid position already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("addid", songpos=protocol.UINT)\n'
        "def addid(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addid {URI} [POSITION]``\n"
        "\n"
        "        Adds a song to the playlist (non-recursive) and returns the song id.\n"
        "\n"
        "        ``URI`` is always a single file or URL. For example::\n"
        "\n"
        '            addid "foo.mp3"\n'
        "            Id: 999\n"
        "            OK\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - ``addid \"\"`` should return an error.\n"
        '    """\n'
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "\n"
        "    length = context.core.tracklist.get_length()\n"
        "    if songpos is not None and songpos > length.get():\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "\n"
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=songpos\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        '    return ("Id", tl_tracks[0].tlid)\n'
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "class _MpdPlayerSyncError(exceptions.MpdAckError):\n"
        "    error_code = exceptions.MpdAckError.ACK_ERROR_PLAYER_SYNC\n"
        "\n"
        "\n"
        "def _mpd_addid_position(value):\n"
        "    # addid の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する。\n"
        '    if value[:1] in ("+", "-"):\n'
        "        rest = value[1:]\n"
        "        if not rest.isdigit():\n"
        '            raise ValueError("Only positive numbers are allowed")\n'
        "        return (value[0], int(rest))\n"
        "    if not value.isdigit():\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return (None, int(value))\n"
        "\n"
        "\n"
        '@protocol.commands.add("addid", songpos=_mpd_addid_position)\n'
        "def addid(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addid {URI} [POSITION]``\n"
        "\n"
        "        Adds a song to the playlist (non-recursive) and returns the song id.\n"
        "\n"
        "        ``URI`` is always a single file or URL. For example::\n"
        "\n"
        '            addid "foo.mp3"\n'
        "            Id: 999\n"
        "            OK\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before).\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - ``addid \"\"`` should return an error.\n"
        '    """\n'
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "\n"
        "    at_position = None\n"
        "    if songpos is not None:\n"
        "        kind, offset = songpos\n"
        "        length = context.core.tracklist.get_length().get()\n"
        "        if kind is None:\n"
        "            if offset > length:\n"
        '                raise exceptions.MpdArgError("Bad song index")\n'
        "            at_position = offset\n"
        "        else:\n"
        "            current = context.core.tracklist.index().get()\n"
        "            if current is None:\n"
        '                raise _MpdPlayerSyncError("No current song")\n'
        '            if kind == "+":\n'
        "                if offset > length - current - 1:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current + 1 + offset\n"
        "            else:\n"
        "                if offset > current:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current - offset\n"
        "\n"
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        '    return ("Id", tl_tracks[0].tlid)\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print("patched current_playlist.py: addid の POSITION に相対指定 (+N/-N) を追加")
