# mopidy-mpd 3.3.0 の `move`/`moveid` は TO を `protocol.UINT` (絶対位置のみ) で
# パースしており、実 MPD 0.15+ が仕様化している「TO が `+`/`-` で始まる場合は
# 現在曲を基準とした相対位置」(`+0` = 現在曲の直後、`-0` = 現在曲の直前) を一切
# 受け付けない (`ValueError` → `ACK incorrect arguments` になり機能が丸ごと失敗
# する)。mopidy_mpd の `moveid` のdocstring自身が既に「If TO is negative, it is
# relative to the current song」と書いているのに実装が追従していない状態だった。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/PositionArg.cxx ParseMoveDestination,
# src/command/QueueCommands.cxx handle_move/handle_moveid) をソース確認して仕様を
# 確定: 相対 TO は addid の POSITION と同じ書式 (+N/-N) だが、move は FROM の
# 範囲を一旦キューから外した後の空間に挿入するため、現在曲の位置を「範囲除去後の
# インデックス」へ補正してから解決する必要がある。また移動対象の範囲自体に現在曲が
# 含まれる場合は基準が定まらないため実 MPD 同様にエラーとする
# (`Cannot move current song relative to itself`)。mopidy core の
# tracklist.move(start, end, to_position) は「[start:end) を除いた後の配列」への
# 挿入位置として to_position を扱うため、そのまま利用できる。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "_mpd_resolve_move_to"
if MARKER in s:
    print("move/moveid TO already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("move", songrange=protocol.RANGE, to=protocol.UINT)\n'
        "def move_range(context, songrange, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``move [{FROM} | {START:END}] {TO}``\n"
        "\n"
        "        Moves the song at ``FROM`` or range of songs at ``START:END`` to\n"
        "        ``TO`` in the playlist.\n"
        '    """\n'
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    context.core.tracklist.move(start, end, to)\n"
        "\n"
        "\n"
        '@protocol.commands.add("moveid", tlid=protocol.UINT, to=protocol.UINT)\n'
        "def moveid(context, tlid, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``moveid {FROM} {TO}``\n"
        "\n"
        "        Moves the song with ``FROM`` (songid) to ``TO`` (playlist index) in\n"
        "        the playlist. If ``TO`` is negative, it is relative to the current\n"
        "        song in the playlist (if there is one).\n"
        '    """\n'
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "    context.core.tracklist.move(position, position + 1, to)\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "def _mpd_move_to(value):\n"
        "    # move/moveid の TO: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid の\n"
        "    # POSITION と同じ書式)。\n"
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
        "def _mpd_resolve_move_to(context, to, start, end):\n"
        "    # (kind, offset) を実際の move() 呼び出し用 to_position (移動対象の\n"
        "    # 範囲 [start:end) を除去した後のインデックス空間、\n"
        "    # 0 <= to_position <= queue_length - (end-start)) へ解決する。\n"
        "    kind, offset = to\n"
        "    queue_length = context.core.tracklist.get_length().get()\n"
        "    new_length = queue_length - (end - start)\n"
        "    if kind is None:\n"
        "        if offset > new_length:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        return offset\n"
        "    current = context.core.tracklist.index().get()\n"
        "    if current is None:\n"
        '        raise _MpdPlayerSyncError("No current song")\n'
        "    if start <= current < end:\n"
        "        raise exceptions.MpdArgError(\n"
        '            "Cannot move current song relative to itself"\n'
        "        )\n"
        "    if current >= end:\n"
        "        current -= end - start\n"
        '    if kind == "+":\n'
        "        if offset > new_length - current - 1:\n"
        '            raise exceptions.MpdArgError("Number too large")\n'
        "        return current + 1 + offset\n"
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n"
        "\n"
        '@protocol.commands.add("move", songrange=protocol.RANGE, to=_mpd_move_to)\n'
        "def move_range(context, songrange, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``move [{FROM} | {START:END}] {TO}``\n"
        "\n"
        "        Moves the song at ``FROM`` or range of songs at ``START:END`` to\n"
        "        ``TO`` in the playlist.\n"
        "\n"
        "        ``TO`` may be relative to the current song: ``+N`` moves right\n"
        "        after the current song (``+0`` = directly after), ``-N`` moves\n"
        "        right before it (``-0`` = directly before).\n"
        '    """\n'
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    context.core.tracklist.move(start, end, to_position)\n"
        "\n"
        "\n"
        '@protocol.commands.add("moveid", tlid=protocol.UINT, to=_mpd_move_to)\n'
        "def moveid(context, tlid, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``moveid {FROM} {TO}``\n"
        "\n"
        "        Moves the song with ``FROM`` (songid) to ``TO`` (playlist index) in\n"
        "        the playlist. ``TO`` may be relative to the current song: ``+N``\n"
        "        moves right after the current song (``+0`` = directly after),\n"
        "        ``-N`` moves right before it (``-0`` = directly before).\n"
        '    """\n'
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    context.core.tracklist.move(position, position + 1, to_position)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: move/moveid の TO に相対指定 (+N/-N) を追加"
    )
