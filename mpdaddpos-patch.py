# mopidy-mpd 3.3.0 の `add` は `add {URI}` のみで POSITION を一切受け付けない
# (実 MPD 0.23+ の `add {URI} [POSITION]` は未対応)。rmpc 本体
# (rmpc/src/config/keys/actions.rs Position::AfterCurrentSong/BeforeCurrentSong が
# QueuePosition::RelativeAdd(0)/RelativeSub(0) を生成し、rmpc-mpd/src/mpd_client.rs
# send_add が `add URI +0`/`add URI -0` を実際に送信する「現在の曲の次に追加」
# 「前に追加」キーバインドアクション、および `rmpc add`/ダウンロードファイルの
# キュー追加 CLI で POSITION 付きの `add` を送信) で実際に使われるが、mopidy-mpd の
# 固定引数 (`uri` のみ) では余分なトークンとなり `ACK wrong number of arguments`
# になり機能が丸ごと失敗する。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/QueueCommands.cxx handle_add /
# src/command/PositionArg.cxx ParseInsertPosition) をソース確認して仕様を確定:
# 位置解決ロジックは addid の相対位置 (+N/-N、現在曲基準) と同一だが、`add` は
# ディレクトリ等を渡すと複数曲を再帰的に追加しうるため、実 MPD は「常に末尾へ
# 追加してから、要求位置が末尾より手前なら追加された範囲だけをまとめて
# move する」実装になっている (MoveRange)。mopidy core の
# tracklist.move(start, end, to_position) が同じセマンティクスを持つため、
# それを利用してこのアルゴリズムを移植する。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "_mpd_resolve_add_position"
if MARKER in s:
    print("add position already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("add")\n'
        "def add(context, uri):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``add {URI}``\n"
        "\n"
        "        Adds the file ``URI`` to the playlist (directories add recursively).\n"
        "        ``URI`` can also be a single file.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``add ""`` should add all tracks in the library to the current playlist.\n'
        '    """\n'
        '    if not uri.strip("/"):\n'
        "        return\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        if context.core.tracklist.add(uris=[uri]).get():\n"
        "            return\n"
        "\n"
        "    try:\n"
        "        uris = []\n"
        "        for _path, ref in context.browse(uri, lookup=False):\n"
        "            if ref:\n"
        "                uris.append(ref.uri)\n"
        "    except exceptions.MpdNoExistError as exc:\n"
        "        exc.message = (  # noqa B306: Our own exception\n"
        '            "directory or file not found"\n'
        "        )\n"
        "        raise\n"
        "\n"
        "    if not uris:\n"
        '        raise exceptions.MpdNoExistError("directory or file not found")\n'
        "    context.core.tracklist.add(uris=uris).get()\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "def _mpd_add_position(value):\n"
        "    # add の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (addid と同じ書式)。\n"
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
        "def _mpd_resolve_add_position(context, songpos, old_size):\n"
        "    # (kind, offset) を実際の挿入位置 (0 <= position <= old_size) へ解決する。\n"
        "    # kind is None: 絶対位置。'+': 現在曲の直後基準。'-': 現在曲の直前基準。\n"
        "    kind, offset = songpos\n"
        "    if kind is None:\n"
        "        if offset > old_size:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        return offset\n"
        "    current = context.core.tracklist.index().get()\n"
        "    if current is None:\n"
        '        raise _MpdPlayerSyncError("No current song")\n'
        '    if kind == "+":\n'
        "        if offset > old_size - current - 1:\n"
        '            raise exceptions.MpdArgError("Number too large")\n'
        "        return current + 1 + offset\n"
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n"
        "\n"
        '@protocol.commands.add("add", songpos=_mpd_add_position)\n'
        "def add(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``add {URI} [POSITION]``\n"
        "\n"
        "        Adds the file ``URI`` to the playlist (directories add recursively).\n"
        "        ``URI`` can also be a single file.\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before). Absent, songs\n"
        "        are appended to the end of the playlist as before.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``add ""`` should add all tracks in the library to the current playlist.\n'
        '    """\n'
        '    if not uri.strip("/"):\n'
        "        return\n"
        "\n"
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        if context.core.tracklist.add(uris=[uri]).get():\n"
        "            added = True\n"
        "\n"
        "    if not added:\n"
        "        try:\n"
        "            uris = []\n"
        "            for _path, ref in context.browse(uri, lookup=False):\n"
        "                if ref:\n"
        "                    uris.append(ref.uri)\n"
        "        except exceptions.MpdNoExistError as exc:\n"
        "            exc.message = (  # noqa B306: Our own exception\n"
        '                "directory or file not found"\n'
        "            )\n"
        "            raise\n"
        "\n"
        "        if not uris:\n"
        '            raise exceptions.MpdNoExistError("directory or file not found")\n'
        "        context.core.tracklist.add(uris=uris).get()\n"
        "\n"
        "    if position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print("patched current_playlist.py: add の POSITION に絶対/相対指定 (+N/-N) を追加")
