# mopidy-mpd 3.3.0 の `playlistdelete`/`playlistmove` (ストアドプレイリスト編集系、
# BACKLOG.md 既存項目「プレイリスト編集系」で `playlistadd`/`playlistdelete`/
# `playlistmove`/`playlistclear`/`rename`/`rm`/`save` は無改修で動くと検証済みだった)
# は SONGPOS/FROM が単一の UINT (`songpos=protocol.UINT` / `from_pos=protocol.UINT`)
# のままで、実 MPD が対応するレンジ指定 (`START:END`) を一切受け付けない。TODO 全項目
# 消化済みのため自走エージェントが調査して新規発見・追加した項目。
#
# musicpd.org protocol (WebFetch で確認) と実 MPD (MusicPlayerDaemon/MPD
# src/command/PlaylistCommands.cxx handle_playlistdelete/handle_playlistmove,
# src/PlaylistFile.{hxx,cxx} PlaylistFileEditor::RemoveRange/MoveIndex,
# src/protocol/RangeArg.hxx) を実際に gh api で clone・確認し仕様を確定:
#   - `playlistdelete {NAME} {SONGPOS}` は MPD 0.23.3+ で `{START:END}` も受理
#     (RemoveRange: start > 曲数 なら `ACK Bad song index`、end は曲数へ自動クリップ、
#     開放端 `START:` も可)。
#   - `playlistmove {NAME} {FROM} {TO}` は MPD 0.24+ で FROM に `{START:END}` も受理
#     (MoveIndex: `from.start == to` の場合は存在確認すらせず無条件で無変更 OK
#     — 実 MPD のコメントに "this doesn't check whether the playlist exists,
#     but what the hell.." と明記。開放端レンジは明示的に
#     `ACK Open-ended range not supported` で拒否。end > 曲数 または
#     `to > 曲数 - レンジ幅` なら `ACK Bad song index`。実装は「レンジを
#     切り出してから、切り出し後の配列に対する位置 TO へ挿入」)。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# `rmpc/src/ui/panes/playlists.rs` の `move_selected()` はプレイリストペインで
# 複数曲をマーク(visual-select)した状態で上下移動キーバインドを実行すると、
# 選択中の連続レンジを `client.move_in_playlist(&playlist, &range, new_idx)` 経由で
# `playlistmove NAME "START:END" TO` として実際に送信すると確認 (`rmpc-mpd/src/
# mpd_client.rs` send_move_in_playlist のデフォルト実装)。mopidy-mpd の固定 UINT
# 実装では余分なコロンを含むトークンが `ACK incorrect arguments` になり、
# プレイリストペインでの複数選択移動が丸ごと失敗する実害あるギャップと確認した上で
# 着手した (`playlistdelete` は rmpc からレンジで送信される実際の呼び出し箇所は
# 未確認だが、同じ `stored_playlists.py` の同種コマンドとして仕様準拠のため合わせて
# 対応する)。

pp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(pp).read()

MARKER = "songrange=protocol.RANGE"
if MARKER in s:
    print("playlistdelete/playlistmove range already patched, skip")
else:
    old_delete = (
        '@protocol.commands.add("playlistdelete", songpos=protocol.UINT)\n'
        "def playlistdelete(context, name, songpos):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistdelete {NAME} {SONGPOS}``\n"
        "\n"
        "        Deletes ``SONGPOS`` from the playlist ``NAME.m3u``.\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    playlist = _get_playlist(context, name)\n"
        "\n"
        "    try:\n"
        "        # Convert tracks to list and remove requested\n"
        "        tracks = list(playlist.tracks)\n"
        "        tracks.pop(songpos)\n"
        "    except IndexError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "\n"
        "    # Replace tracks and save playlist\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert s.count(old_delete) == 1, f"old_delete count={s.count(old_delete)}"

    new_delete = (
        '@protocol.commands.add("playlistdelete", songrange=protocol.RANGE)\n'
        "def playlistdelete(context, name, songrange):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistdelete {NAME} {SONGPOS}``\n"
        "\n"
        "        Deletes ``SONGPOS`` from the playlist ``NAME.m3u``. ``SONGPOS``\n"
        "        may also be a ``START:END`` range (MPD 0.23.3+).\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    playlist = _get_playlist(context, name)\n"
        "\n"
        "    tracks = list(playlist.tracks)\n"
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if start > len(tracks):\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "    if end is None or end > len(tracks):\n"
        "        end = len(tracks)\n"
        "    del tracks[start:end]\n"
        "\n"
        "    # Replace tracks and save playlist\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert new_delete != old_delete
    s = s.replace(old_delete, new_delete, 1)

    old_move = (
        '@protocol.commands.add(\n'
        '    "playlistmove", from_pos=protocol.UINT, to_pos=protocol.UINT\n'
        ")\n"
        "def playlistmove(context, name, from_pos, to_pos):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistmove {NAME} {SONGID} {SONGPOS}``\n"
        "\n"
        "        Moves ``SONGID`` in the playlist ``NAME.m3u`` to the position\n"
        "        ``SONGPOS``.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - The second argument is not a ``SONGID`` as used elsewhere in the protocol\n"
        "      documentation, but just the ``SONGPOS`` to move *from*, i.e.\n"
        "      ``playlistmove {NAME} {FROM_SONGPOS} {TO_SONGPOS}``.\n"
        '    """\n'
        "    if from_pos == to_pos:\n"
        "        return\n"
        "\n"
        "    _check_playlist_name(name)\n"
        "    playlist = _get_playlist(context, name)\n"
        "    if from_pos == to_pos:\n"
        "        return  # Nothing to do\n"
        "\n"
        "    try:\n"
        "        # Convert tracks to list and perform move\n"
        "        tracks = list(playlist.tracks)\n"
        "        track = tracks.pop(from_pos)\n"
        "        tracks.insert(to_pos, track)\n"
        "    except IndexError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "\n"
        "    # Replace tracks and save playlist\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert s.count(old_move) == 1, f"old_move count={s.count(old_move)}"

    new_move = (
        '@protocol.commands.add(\n'
        '    "playlistmove", from_range=protocol.RANGE, to_pos=protocol.UINT\n'
        ")\n"
        "def playlistmove(context, name, from_range, to_pos):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistmove {NAME} {FROM} {TO}``\n"
        "\n"
        "        Moves the song at ``FROM`` or range of songs at ``START:END``\n"
        "        (MPD 0.24+) in the playlist ``NAME.m3u`` to the position ``TO``.\n"
        "        Open-ended ranges (``START:``) are not supported here, matching\n"
        "        real MPD.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - The second argument is not a ``SONGID`` as used elsewhere in the protocol\n"
        "      documentation, but just the ``SONGPOS`` (or range) to move *from*, i.e.\n"
        "      ``playlistmove {NAME} {FROM_SONGPOS} {TO_SONGPOS}``.\n"
        '    """\n'
        "    start = from_range.start\n"
        "    end = from_range.stop\n"
        "    if start == to_pos:\n"
        "        # Real MPD skips even the playlist-existence check here.\n"
        "        return\n"
        "    if end is None:\n"
        '        raise exceptions.MpdArgError("Open-ended range not supported")\n'
        "\n"
        "    _check_playlist_name(name)\n"
        "    playlist = _get_playlist(context, name)\n"
        "\n"
        "    tracks = list(playlist.tracks)\n"
        "    count = end - start\n"
        "    if end > len(tracks) or to_pos > len(tracks) - count:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "\n"
        "    # Cut the range out, then insert it at to_pos in the *remaining*\n"
        "    # list, matching real MPD's PlaylistFileEditor::MoveIndex.\n"
        "    moved = tracks[start:end]\n"
        "    del tracks[start:end]\n"
        "    tracks[to_pos:to_pos] = moved\n"
        "\n"
        "    # Replace tracks and save playlist\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert new_move != old_move
    s = s.replace(old_move, new_move, 1)

    open(pp, "w").write(s)
    print(
        "patched stored_playlists.py: playlistdelete/playlistmove に "
        "START:END レンジ指定を追加"
    )
