# mopidy_mpd/protocol/current_playlist.py の `plchanges`/`plchangesposid` が
# MPD 0.20+ (NEWS: "add range parameter to command \"plchanges\" and
# \"plchangesposid\"") で追加された任意の `[START:END]` 範囲引数を一切受け付けない
# 不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見。
#
# 実MPD本体 (gh rawで確認、src/command/QueueCommands.cxx):
#     handle_plchanges():
#         uint32_t version = ParseCommandArgU32(args.front());
#         RangeArg range = args.ParseOptional(1, RangeArg::All());
#         playlist_print_changes_info(r, client.GetPlaylist(), version, range);
#     handle_plchangesposid() も同じ形。
# `playlist_print_changes_info`/`_position` (src/PlaylistPrint.cxx) は
# `range.ClipRelaxed(queue.GetLength())` (src/protocol/RangeArg.hxx: end を
# count へ、start を end へ、それぞれ超過分のみ黙ってクランプ。例外を投げない) の
# 上で `queue_print_changes_info/_position` (src/queue/Print.cxx) が
# `for (i = start; i < end; i++) if (queue.IsNewerAtPosition(i, version)) ...`
# と、範囲外のインデックスを走査対象からそもそも除外する (playlistinfo等の
# `CheckClip`=範囲外はACKと違い、plchanges系はrelaxed=常にOK・空でも構わない)。
#
# mopidy_mpd側は元々 `version` の1引数しか受け付けず (`@protocol.commands.add(
# "plchanges", version=protocol.INT)`)、3つ目以降のトークンがあると dispatcher の
# `inspect.signature(func).bind()` が TypeError → `wrong number of arguments for
# "plchanges"` としてACKされ、範囲指定自体が一切不可能だった。
#
# 修正: 両コマンドに `songrange=protocol.RANGE` (デフォルト `slice(0, None)` =
# 全件、既存の listplaylistinfo と同じ流儀) を追加。共有ヘルパー
# `_mpd_plchanges_clip_range(songrange, length)` で実MPDの `ClipRelaxed` と
# 同じ「endをlengthへ、startをendへ、それぞれ超過分だけクランプ」を行い:
#   - `version < tracklist_version` (全曲「変更」) 分岐は
#     `translator.tracks_to_mpd_format(..., start=, end=)` (既存の
#     start/end引数で position: フィールドも正しく絶対位置を保つ) へ委譲。
#   - version一致のメタデータ更新1曲分岐/リトライ後fallback分岐、および
#     plchangesposidのenumerateループは、対象positionが範囲外なら
#     何も返さない (real MPDの「範囲外は素通り」と同じ)。
# バージョン比較ロジック自体 (mpdcurrentsongrace-patch.py/
# mpdplchangesposidfuture-patch.py 由来のTOCTOU retry・未来バージョン判定) は
# 無変更。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "_mpd_plchanges_clip_range"
if MARKER in s:
    print("plchanges/plchangesposid range already patched, skip")
else:
    old_plchanges = (
        '@protocol.commands.add("plchanges", version=protocol.INT)\n'
        "def plchanges(context, version):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``plchanges {VERSION}``\n"
        "\n"
        "        Displays changed songs currently in the playlist since ``VERSION``.\n"
        "\n"
        "        To detect songs that were deleted at the end of the playlist, use\n"
        "        ``playlistlength`` returned by status command.\n"
        "\n"
        "    *MPDroid:*\n"
        "\n"
        '    - Calls ``plchanges "-1"`` two times per second to get the entire playlist.\n'
        '    """\n'
        "    # XXX Naive implementation that returns all tracks as changed\n"
        "    # version一致(メタデータ更新のみ)分岐のget_current_tl_track()/tracklist.index()\n"
        "    # はcurrentsongと同じTOCTOUレースを持つ(別々のcore呼び出しの間に割り込まれると\n"
        "    # positionがNoneになりPos/Idがサイレントに欠落する)。versionが前後で不変な\n"
        "    # ことを確認し、割り込みがあれば取り直す。\n"
        "    tl_track = None\n"
        "    position = None\n"
        "    stream_title = None\n"
        "    for _ in range(_TRACKLIST_SNAPSHOT_RETRIES):\n"
        "        tracklist_version = context.core.tracklist.get_version().get()\n"
        "        if version < tracklist_version:\n"
        "            return translator.tracks_to_mpd_format(\n"
        "                context.core.tracklist.get_tl_tracks().get(),\n"
        "                context.session.tagtypes,\n"
        "            )\n"
        "        elif version == tracklist_version:\n"
        "            # A version match could indicate this is just a metadata update, so\n"
        "            # check for a stream ref and let the client know about the change.\n"
        "            stream_title = context.core.playback.get_stream_title().get()\n"
        "            if stream_title is None:\n"
        "                return None\n"
        "\n"
        "            tl_track = context.core.playback.get_current_tl_track().get()\n"
        "            position = context.core.tracklist.index(tl_track).get()\n"
        "            if context.core.tracklist.get_version().get() == tracklist_version:\n"
        "                return translator.track_to_mpd_format(\n"
        "                    tl_track,\n"
        "                    context.session.tagtypes,\n"
        "                    position=position,\n"
        "                    stream_title=stream_title,\n"
        "                )\n"
        "        else:\n"
        "            return\n"
        "    return translator.track_to_mpd_format(\n"
        "        tl_track,\n"
        "        context.session.tagtypes,\n"
        "        position=position,\n"
        "        stream_title=stream_title,\n"
        "    )\n"
    )
    assert s.count(old_plchanges) == 1, f"old_plchanges count={s.count(old_plchanges)}"
    new_plchanges = (
        "def _mpd_plchanges_clip_range(songrange, length):\n"
        "    # 実MPD RangeArg::ClipRelaxed()相当: endをlengthへ、\n"
        "    # startをend(クランプ後)へ、それぞれ超過分のみ黙ってクランプする\n"
        "    # (playlistinfo等のCheckClipと違いACKにはしない)。\n"
        "    end = length if songrange.stop is None else min(songrange.stop, length)\n"
        "    start = min(songrange.start, end)\n"
        "    return start, end\n"
        "\n"
        "\n"
        '@protocol.commands.add(\n'
        '    "plchanges", version=protocol.INT, songrange=protocol.RANGE\n'
        ")\n"
        "def plchanges(context, version, songrange=slice(0, None)):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``plchanges {VERSION} [START:END]``\n"
        "\n"
        "        Displays changed songs currently in the playlist since ``VERSION``.\n"
        "        ``START:END`` (MPD 0.20+) limits output to that range of positions;\n"
        "        a range extending past the end of the playlist is silently\n"
        "        truncated rather than treated as an error, matching real MPD.\n"
        "\n"
        "        To detect songs that were deleted at the end of the playlist, use\n"
        "        ``playlistlength`` returned by status command.\n"
        "\n"
        "    *MPDroid:*\n"
        "\n"
        '    - Calls ``plchanges "-1"`` two times per second to get the entire playlist.\n'
        '    """\n'
        "    # XXX Naive implementation that returns all tracks as changed\n"
        "    # version一致(メタデータ更新のみ)分岐のget_current_tl_track()/tracklist.index()\n"
        "    # はcurrentsongと同じTOCTOUレースを持つ(別々のcore呼び出しの間に割り込まれると\n"
        "    # positionがNoneになりPos/Idがサイレントに欠落する)。versionが前後で不変な\n"
        "    # ことを確認し、割り込みがあれば取り直す。\n"
        "    tl_track = None\n"
        "    position = None\n"
        "    stream_title = None\n"
        "    for _ in range(_TRACKLIST_SNAPSHOT_RETRIES):\n"
        "        tracklist_version = context.core.tracklist.get_version().get()\n"
        "        if version < tracklist_version:\n"
        "            tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "            start, end = _mpd_plchanges_clip_range(songrange, len(tl_tracks))\n"
        "            return translator.tracks_to_mpd_format(\n"
        "                tl_tracks,\n"
        "                context.session.tagtypes,\n"
        "                start=start,\n"
        "                end=end,\n"
        "            )\n"
        "        elif version == tracklist_version:\n"
        "            # A version match could indicate this is just a metadata update, so\n"
        "            # check for a stream ref and let the client know about the change.\n"
        "            stream_title = context.core.playback.get_stream_title().get()\n"
        "            if stream_title is None:\n"
        "                return None\n"
        "\n"
        "            tl_track = context.core.playback.get_current_tl_track().get()\n"
        "            position = context.core.tracklist.index(tl_track).get()\n"
        "            if context.core.tracklist.get_version().get() == tracklist_version:\n"
        "                length = context.core.tracklist.get_length().get()\n"
        "                start, end = _mpd_plchanges_clip_range(songrange, length)\n"
        "                if not (start <= position < end):\n"
        "                    return None\n"
        "                return translator.track_to_mpd_format(\n"
        "                    tl_track,\n"
        "                    context.session.tagtypes,\n"
        "                    position=position,\n"
        "                    stream_title=stream_title,\n"
        "                )\n"
        "        else:\n"
        "            return\n"
        "    length = context.core.tracklist.get_length().get()\n"
        "    start, end = _mpd_plchanges_clip_range(songrange, length)\n"
        "    if position is None or not (start <= position < end):\n"
        "        return None\n"
        "    return translator.track_to_mpd_format(\n"
        "        tl_track,\n"
        "        context.session.tagtypes,\n"
        "        position=position,\n"
        "        stream_title=stream_title,\n"
        "    )\n"
    )
    s = s.replace(old_plchanges, new_plchanges, 1)

    old_plchangesposid = (
        '@protocol.commands.add("plchangesposid", version=protocol.INT)\n'
        "def plchangesposid(context, version):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``plchangesposid {VERSION}``\n"
        "\n"
        "        Displays changed songs currently in the playlist since ``VERSION``.\n"
        "        This function only returns the position and the id of the changed\n"
        "        song, not the complete metadata. This is more bandwidth efficient.\n"
        "\n"
        "        To detect songs that were deleted at the end of the playlist, use\n"
        "        ``playlistlength`` returned by status command.\n"
        '    """\n'
        "    # XXX Naive implementation that returns all changed song ids\n"
        "    # version > tracklist_version (未来のバージョン) は「変更なし」を意味すべき\n"
        "    # ところ、元実装は `!=` 判定のため全曲を「変更」として返してしまっていた\n"
        "    # (兄弟コマンドplchangesのversion<tracklist_version分岐とだけ揃える)。\n"
        "    if int(version) < context.core.tracklist.get_version().get():\n"
        "        result = []\n"
        "        for (position, (tlid, _)) in enumerate(\n"
        "            context.core.tracklist.get_tl_tracks().get()\n"
        "        ):\n"
        "            result.append((\"cpos\", position))\n"
        "            result.append((\"Id\", tlid))\n"
        "        return result\n"
    )
    assert s.count(old_plchangesposid) == 1, (
        f"old_plchangesposid count={s.count(old_plchangesposid)}"
    )
    new_plchangesposid = (
        '@protocol.commands.add(\n'
        '    "plchangesposid", version=protocol.INT, songrange=protocol.RANGE\n'
        ")\n"
        "def plchangesposid(context, version, songrange=slice(0, None)):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``plchangesposid {VERSION} [START:END]``\n"
        "\n"
        "        Displays changed songs currently in the playlist since ``VERSION``.\n"
        "        This function only returns the position and the id of the changed\n"
        "        song, not the complete metadata. This is more bandwidth efficient.\n"
        "        ``START:END`` (MPD 0.20+) limits output to that range of positions;\n"
        "        a range extending past the end of the playlist is silently\n"
        "        truncated rather than treated as an error, matching real MPD.\n"
        "\n"
        "        To detect songs that were deleted at the end of the playlist, use\n"
        "        ``playlistlength`` returned by status command.\n"
        '    """\n'
        "    # XXX Naive implementation that returns all changed song ids\n"
        "    # version > tracklist_version (未来のバージョン) は「変更なし」を意味すべき\n"
        "    # ところ、元実装は `!=` 判定のため全曲を「変更」として返してしまっていた\n"
        "    # (兄弟コマンドplchangesのversion<tracklist_version分岐とだけ揃える)。\n"
        "    if int(version) < context.core.tracklist.get_version().get():\n"
        "        tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
        "        start, end = _mpd_plchanges_clip_range(songrange, len(tl_tracks))\n"
        "        result = []\n"
        "        for (position, (tlid, _)) in enumerate(tl_tracks):\n"
        "            if not (start <= position < end):\n"
        "                continue\n"
        "            result.append((\"cpos\", position))\n"
        "            result.append((\"Id\", tlid))\n"
        "        return result\n"
    )
    s = s.replace(old_plchangesposid, new_plchangesposid, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: plchanges/plchangesposidがMPD 0.20+の"
        "任意の[START:END]範囲引数を一切受け付けず'wrong number of arguments'に"
        "ACKしてしまう不具合を修正 (protocol.RANGEで受理し、実MPDのClipRelaxed同様"
        "範囲外は黙って除外・ACKにはしない)"
    )
