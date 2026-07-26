# `rangeid` (musicpd.org protocol, current playlist section) が
# mopidy-mpd 3.3.0 では `raise MpdNotImplemented` のスタブのまま。TODO 全項目
# 消化済みのため自走エージェントが mopidy_mpd 残りの `MpdNotImplemented` スタブ
# (listfiles/rangeid、mpdclearerror-patch.py/mpdaddtagid-patch.py のコメントで
# 洗い出し済み) から選定。rmpc 本体 (mierak/rmpc) を実際に clone して grep したが
# `rangeid` を送信する箇所は皆無 (rmpc はこの機能を持たない) と判明。ただし
# clearerror/decoders/stats/listneighbors と同種の「rmpc固有ではなく標準 MPD
# プロトコル準拠の不備」に該当すると判断: mpc・ncmpcpp 等の汎用 MPD クライアントが
# 標準的に使う基本コマンド (トラックの一部区間だけ再生する「部分再生」機能) が
# 常に ACK エラーになる現状はギャップと確認した上で着手。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/QueueCommands.cxx handle_rangeid,
# src/queue/PlaylistEdit.cxx playlist::SetSongIdRange, src/SongPrint.cxx
# PrintRange) を実際に取得してソース確認し仕様を確定:
#   - 引数は "{ID} {START:END}" (START/ENDは秒、小数可、どちらも省略可)。
#     コロンが無い・数値でない・start<0/end<0・(endが0でないのに)end<=start は
#     いずれも同一の ACK_ERROR_ARG "Bad range"。
#   - ID がキューに存在しなければ ACK_ERROR_NO_EXIST "No such song"。
#   - 対象曲が現在再生中の曲そのもの (position==current) なら
#     ACK_ERROR_PERMISSION "Cannot edit the current song"。ただしこのチェック
#     自体が `if (playing)` でガードされており (PlaylistControl.cxx の Stop()
#     は再生位置 current を -1 へ戻さず playing フラグのみ落とすため)、
#     stop 後は直前に再生していた曲であっても編集可能 (再生中でない曲・
#     再生中でも他のポジションの曲は元々編集可)。
#   - 曲の長さが既知なら start>duration は ACK_ERROR_ARG "Invalid start offset"、
#     end>=duration は「無制限」(end=0) へ自動で丸められる (エラーにしない)。
#   - "0:0" 相当 (start/end とも省略、コロンのみ) は「レンジ解除、全体再生」。
#   - 出力側 (SongPrint.cxx PrintRange): end>0 なら
#     "Range: {start}.{ms:03}-{end}.{ms:03}"、end==0かつstart>0なら
#     "Range: {start}.{ms:03}-" (無制限)、両方0ならフィールド自体を出力しない。
#
# mopidy core (mopidy/core/tracklist.py, mopidy/core/playback.py) は実 MPD の
# ような「キュー内の1曲だけ部分再生する」機構を一切持たない (パッチ対象外) ため、
# mount/crossfade/prio と同種の「プロトコル層の状態保持・応答・playlistid/
# playlistinfo への Range 反映のみ提供し、実際の再生区間には影響しない」実装
# にした (既知の制約として明記)。prio/Added/addtagid と同じ流儀で translator.py
# に tlid -> (start_ms, end_ms) の揮発性ストアを追加し、
# track_to_mpd_format() の出力に Range として反映する。actor.py の
# tracklist_changed イベント (既存の _sync_added_timestamps 等と同じフック) で
# キューから消えた tlid のレンジを掃除する。

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

MARKER_C = "_MpdEditCurrentSongError"
if MARKER_C in c:
    print("current_playlist.py already patched for rangeid, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert c.count(old_import) == 1, f"old_import count={c.count(old_import)}"
    new_import = "from mopidy.core import PlaybackState\n" + old_import
    c = c.replace(old_import, new_import, 1)

    old_block = (
        '@protocol.commands.add("rangeid", tlid=protocol.UINT, songrange=protocol.RANGE)\n'
        "def rangeid(context, tlid, songrange):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``rangeid {ID} {START:END}``\n"
        "\n"
        "        Specifies the portion of the song that shall be played. START and END\n"
        "        are offsets in seconds (fractional seconds allowed); both are optional.\n"
        '        Omitting both (i.e. sending just ":") means "remove the range, play\n'
        '        everything". A song that is currently playing cannot be manipulated\n'
        "        this way.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert c.count(old_block) == 1, f"old_block count={c.count(old_block)}"

    new_block = (
        "class _MpdEditCurrentSongError(exceptions.MpdAckError):\n"
        "    error_code = exceptions.MpdAckError.ACK_ERROR_PERMISSION\n"
        "\n"
        "\n"
        "def _mpd_parse_time_range(value):\n"
        "    # 実 MPD の parse_time_range() (QueueCommands.cxx) と同じ規則:\n"
        '    # "START:END" (ms単位の整数へ丸める)、コロン必須、両辺とも省略可\n'
        "    # (省略時は0)。不正な入力・負値・(endが0でないのに)end<=start は\n"
        '    # 全て同一の "Bad range" エラーにまとめる。\n'
        "    if value is None or \":\" not in value:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
        '    start_str, _sep, end_str = value.partition(":")\n'
        "    try:\n"
        "        start = float(start_str) if start_str.strip() else 0.0\n"
        "        end = float(end_str) if end_str.strip() else 0.0\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
        "    if start < 0 or end < 0:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
        "    if end and end <= start:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
        "    return round(start * 1000), round(end * 1000)\n"
        "\n"
        "\n"
        '@protocol.commands.add("rangeid", tlid=protocol.UINT)\n'
        "def rangeid(context, tlid, songrange):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``rangeid {ID} {START:END}``\n"
        "\n"
        "        Specifies the portion of the song that shall be played. START and END\n"
        "        are offsets in seconds (fractional seconds allowed); both are optional.\n"
        '        Omitting both (i.e. sending just ":") means "remove the range, play\n'
        '        everything". A song that is currently playing cannot be manipulated\n'
        "        this way.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    start_ms, end_ms = _mpd_parse_time_range(songrange)\n"
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    playing = context.core.playback.get_state().get() in (\n"
        "        PlaybackState.PLAYING,\n"
        "        PlaybackState.PAUSED,\n"
        "    )\n"
        "    if playing:\n"
        "        current = context.core.playback.get_current_tl_track().get()\n"
        "        if current is not None and current.tlid == tlid:\n"
        '            raise _MpdEditCurrentSongError("Cannot edit the current song")\n'
        "    duration = tl_tracks[0].track.length\n"
        "    if duration is not None and duration >= 0:\n"
        "        if start_ms > duration:\n"
        '            raise exceptions.MpdArgError("Invalid start offset")\n'
        "        if end_ms and end_ms >= duration:\n"
        "            end_ms = 0\n"
        "    translator.set_range(tlid, start_ms, end_ms)\n"
    )
    assert new_block != old_block
    c = c.replace(old_block, new_block, 1)
    open(cp, "w").write(c)
    print(
        "patched current_playlist.py: rangeid を実装 "
        "(Bad range/No such song/Cannot edit the current song/Invalid start offset "
        "+ 揮発性ストア反映)"
    )

# --- translator.py: tlid -> (start_ms, end_ms) の揮発性ストア ---

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_queue_ranges"
if MARKER_T in t:
    print("translator.py already patched for rangeid, skip")
else:
    anchor = (
        "def sync_extra_tags(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_extra_tags if t not in current]:\n"
        "        del _queue_extra_tags[tlid]\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "\n"
        "# rangeid (current_playlist.py) 用の揮発性ストア。tlid -> (start_ms, end_ms)。\n"
        "# end_ms==0 は「開始のみ指定・無制限」、実MPD同様曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_ranges = {}\n"
        "\n"
        "\n"
        "def set_range(tlid, start_ms, end_ms):\n"
        "    if start_ms or end_ms:\n"
        "        _queue_ranges[tlid] = (start_ms, end_ms)\n"
        "    else:\n"
        "        _queue_ranges.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_range(tlid):\n"
        "    return _queue_ranges.get(tlid)\n"
        "\n"
        "\n"
        "def sync_ranges(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_ranges if t not in current]:\n"
        "        del _queue_ranges[tlid]\n"
        "\n"
        "\n"
        "def _format_range(start_ms, end_ms):\n"
        "    # 実 MPD の SongPrint.cxx PrintRange() と同じ形式:\n"
        '    # end>0 なら "{sec}.{ms:03}-{sec}.{ms:03}"、end==0かつstart>0なら\n'
        '    # "{sec}.{ms:03}-" (無制限)、両方0ならNone (フィールド自体を出さない)。\n'
        "    if end_ms:\n"
        "        return (\n"
        "            f\"{start_ms // 1000}.{start_ms % 1000:03d}-\"\n"
        "            f\"{end_ms // 1000}.{end_ms % 1000:03d}\"\n"
        "        )\n"
        "    if start_ms:\n"
        "        return f\"{start_ms // 1000}.{start_ms % 1000:03d}-\"\n"
        "    return None\n"
    )
    t = t.replace(anchor, anchor + store, 1)

    id_anchor = (
        '        result.append(("Pos", position))\n'
        '        result.append(("Id", tlid))\n'
        "        priority = get_priority(tlid)\n"
    )
    assert t.count(id_anchor) == 1, f"id_anchor count={t.count(id_anchor)}"
    id_new = (
        '        result.append(("Pos", position))\n'
        '        result.append(("Id", tlid))\n'
        "        song_range = get_range(tlid)\n"
        "        if song_range:\n"
        "            range_str = _format_range(*song_range)\n"
        "            if range_str:\n"
        '                result.append(("Range", range_str))\n'
        "        priority = get_priority(tlid)\n"
    )
    t = t.replace(id_anchor, id_new, 1)

    open(tp, "w").write(t)
    print(
        "patched translator.py: rangeid の揮発性ストア + "
        "track_to_mpd_format反映を追加"
    )

# --- actor.py: tracklist_changed で消えたtlidのレンジを掃除 ---

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER_A = "_sync_ranges"
if MARKER_A in a:
    print("actor.py already patched for rangeid, skip")
else:
    old_event = (
        '        if event == "tracklist_changed":\n'
        "            self._sync_added_timestamps()\n"
        "            self._sync_extra_tags()\n"
    )
    assert a.count(old_event) == 1, f"old_event count={a.count(old_event)}"
    new_event = old_event + "            self._sync_ranges()\n"
    a = a.replace(old_event, new_event, 1)

    anchor_method = (
        "    def _sync_extra_tags(self):\n"
        "        # addtagid/cleartagid 用のtlid->タグストアからキューに存在しなく\n"
        "        # なったtlidを掃除する (実MPD同様、曲がキューから消えたら\n"
        "        # addtagidで足したタグも消える揮発性のため)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_extra_tags([tlid for tlid, _track in tl_tracks])\n"
    )
    assert a.count(anchor_method) == 1, f"anchor_method count={a.count(anchor_method)}"
    new_method = (
        "\n"
        "    def _sync_ranges(self):\n"
        "        # rangeid 用のtlid->レンジストアからキューに存在しなくなった\n"
        "        # tlidを掃除する (実MPD同様、曲がキューから消えたら部分再生の\n"
        "        # 指定も消える揮発性のため)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_ranges([tlid for tlid, _track in tl_tracks])\n"
    )
    a = a.replace(anchor_method, anchor_method + new_method, 1)

    open(ap, "w").write(a)
    print("patched actor.py: tracklist_changed で消えたtlidのレンジを掃除")
