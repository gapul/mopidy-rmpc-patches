# mopidy-mpd 3.3.0 の `prio` / `prioid` は `raise MpdNotImplemented` のスタブ。
# 実 MPD 仕様どおり: 0-255 のプリオリティを指定した曲 (prio は START:END 範囲を
# 複数、prioid は songid を複数指定可) に設定し、`playlistinfo`/`playlistid` 等の
# 出力に non-zero のときだけ `Prio: N` として反映する (Pos/Id と同じく tagtypes の
# 対象外なので disable しても常に出る、実 MPD と同じ)。優先度は queue アイテム
# (tlid) に紐付く transient な状態として translator.py 側にモジュールレベルで保持する
# (実 MPD もプロセス再起動で消える揮発性の値なので妥当)。
#
# 既知の制約: mopidy core の Tracklist.set_random()/next_track() は優先度の概念を
# 持たず単純な random.shuffle のみ (mopidy/core/tracklist.py) なので、prio が
# 「random モード時の再生順」に実際に影響することはない (プロトコル応答・
# playlistinfo の Prio フィールド反映のみ)。mopidy core 自体はパッチ対象外
# (nix/lib/mopidy-env.nix が patch するのは mopidy-mpd/ytmusic/listenbrainz の
# 拡張のみ) であり、rmpc 側 (rmpc-mpd/src/mpd_client.rs) も prio/prioid を
# 一切送信しない (moveid/swapid は送信する) ため実害はない。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "translator.set_priority"
if MARKER in s:
    print("prio/prioid already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("prio", priority=protocol.UINT, position=protocol.RANGE)\n'
        "def prio(context, priority, position):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``prio {PRIORITY} {START:END...}``\n"
        "\n"
        "        Set the priority of the specified songs. A higher priority means that\n"
        '        it will be played first when "random" mode is enabled.\n'
        "\n"
        "        A priority is an integer between 0 and 255. The default priority of new\n"
        "        songs is 0.\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
        "\n"
        "\n"
        '@protocol.commands.add("prioid")\n'
        "def prioid(context, *args):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``prioid {PRIORITY} {ID...}``\n"
        "\n"
        "        Same as prio, but address the songs with their id.\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("prio")\n'
        "def prio(context, *args):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``prio {PRIORITY} {START:END...}``\n"
        "\n"
        "        Set the priority of the specified songs. A higher priority means that\n"
        '        it will be played first when "random" mode is enabled.\n'
        "\n"
        "        A priority is an integer between 0 and 255. The default priority of new\n"
        "        songs is 0.\n"
        '    """\n'
        "    if len(args) < 2:\n"
        "        raise exceptions.MpdArgError(\n"
        '            \'wrong number of arguments for "prio"\'\n'
        "        )\n"
        "    priority = _mpd_parse_priority(args[0])\n"
        "    tlids = set()\n"
        "    for token in args[1:]:\n"
        "        try:\n"
        "            songrange = protocol.RANGE(token)\n"
        "        except ValueError:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        start = songrange.start\n"
        "        end = songrange.stop\n"
        "        if end is None:\n"
        "            end = context.core.tracklist.get_length().get()\n"
        "        tl_tracks = context.core.tracklist.slice(start, end).get()\n"
        "        if not tl_tracks:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        tlids.update(tlid for tlid, _track in tl_tracks)\n"
        "    for tlid in tlids:\n"
        "        translator.set_priority(tlid, priority)\n"
        "\n"
        "\n"
        '@protocol.commands.add("prioid")\n'
        "def prioid(context, *args):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``prioid {PRIORITY} {ID...}``\n"
        "\n"
        "        Same as prio, but address the songs with their id.\n"
        '    """\n'
        "    if len(args) < 2:\n"
        "        raise exceptions.MpdArgError(\n"
        '            \'wrong number of arguments for "prioid"\'\n'
        "        )\n"
        "    priority = _mpd_parse_priority(args[0])\n"
        "    tlids = [_mpd_parse_tlid(token) for token in args[1:]]\n"
        "    for tlid in tlids:\n"
        '        if not context.core.tracklist.filter({"tlid": [tlid]}).get():\n'
        '            raise exceptions.MpdNoExistError("No such song")\n'
        "    for tlid in tlids:\n"
        "        translator.set_priority(tlid, priority)\n"
        "\n"
        "\n"
        "def _mpd_parse_priority(value):\n"
        "    try:\n"
        "        priority = protocol.UINT(value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    if priority > 255:\n"
        '        raise exceptions.MpdArgError("Invalid priority")\n'
        "    return priority\n"
        "\n"
        "\n"
        "def _mpd_parse_tlid(value):\n"
        "    try:\n"
        "        return protocol.UINT(value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print("patched current_playlist.py: prio/prioid を実装 (優先度を保存し Prio フィールドへ反映)")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

if "_queue_priorities" in t:
    print("translator.py already patched, skip")
else:
    old_import = "from mopidy_mpd.protocol import tagtype_list\n"
    assert t.count(old_import) == 1, f"old_import count={t.count(old_import)}"
    new_import = old_import + (
        "\n"
        "# prio/prioid (current_playlist.py) 用の揮発性ストア。プロセス再起動で\n"
        "# 消えるのは実 MPD の優先度も同じなので妥当。\n"
        "_queue_priorities = {}\n"
        "\n"
        "\n"
        "def set_priority(tlid, priority):\n"
        "    if priority:\n"
        "        _queue_priorities[tlid] = priority\n"
        "    else:\n"
        "        _queue_priorities.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_priority(tlid):\n"
        "    return _queue_priorities.get(tlid, 0)\n"
    )
    t = t.replace(old_import, new_import, 1)

    old_pos_id = (
        '    if position is not None and tlid is not None:\n'
        '        result.append(("Pos", position))\n'
        '        result.append(("Id", tlid))\n'
    )
    assert t.count(old_pos_id) == 1, f"old_pos_id count={t.count(old_pos_id)}"
    new_pos_id = old_pos_id + (
        "        priority = get_priority(tlid)\n"
        "        if priority:\n"
        '            result.append(("Prio", priority))\n'
    )
    t = t.replace(old_pos_id, new_pos_id, 1)

    open(tp, "w").write(t)
    print("patched translator.py: 優先度ストア + Prio フィールドの反映を追加")
