# mopidy-mpd 3.3.0 の `load` は `load {NAME} [START:END]` までしか受け付けず、
# 実 MPD 0.23+ の `load {NAME} [START:END] [POSITION]` (絶対/相対 `+N`/`-N`、
# add/addid と同じ書式) 未対応。TODO 全項目消化済みのため自走エージェントが
# rmpc 本体 (mierak/rmpc) を実際に clone して調査したところ、
# rmpc-mpd/src/mpd_client.rs send_load_playlist が常に RANGE ("0:") に加えて
# 任意の POSITION を送信する実装で、rmpc/src/ui/panes/directories.rs の
# enqueue() がディレクトリブラウザでストアドプレイリスト項目を選択した際に
# Enqueue::Playlist を生成し、CommonAction::AddOptions (キーバインド可能な
# 「現在の曲の次に追加」「前に追加」等 rmpc/src/config/keys/actions.rs の
# Position::AfterCurrentSong/BeforeCurrentSong を含む位置指定つき追加アクション)
# 経由で実際に `load NAME 0: +0` のような POSITION 付き `load` を送信すると
# 判明。mopidy-mpd の固定引数実装では余分なトークンが
# `ACK wrong number of arguments` になり、ディレクトリブラウザからストアド
# プレイリストを位置指定付きでキューに追加する機能が丸ごと失敗する実害ある
# ギャップと確認した上で追加した項目。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/PlaylistCommands.cxx handle_load)
# を WebFetch でソース確認し仕様を確定: 位置解決は add と同じ
# ParseInsertPosition (現在曲基準の相対 +N/-N、絶対はロード前のキュー長で
# クランプ) だが、load はプレイリストの複数曲を一括で追加しうるため、
# 実 MPD は「常に末尾へ追加してから、要求位置が末尾より手前ならその追加
# された範囲だけをまとめて move する」実装 (MoveRange) になっている。
# mopidy core の tracklist.move(start, end, to_position) が同じセマンティクス
# を持つため、mpdaddpos-patch.py の add と同じアルゴリズムを移植する。

sp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(sp).read()

MARKER = "_mpd_resolve_load_position"
if MARKER in s:
    print("load position already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("load", playlist_slice=protocol.RANGE)\n'
        "def load(context, name, playlist_slice=DEFAULT_PLAYLIST_SLICE):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``load {NAME} [START:END]``\n"
        "\n"
        "        Loads the playlist into the current queue. Playlist plugins are\n"
        "        supported. A range may be specified to load only a part of the\n"
        "        playlist.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - ``load`` appends the given playlist to the current playlist.\n"
        "\n"
        "    - MPD 0.17.1 does not support open-ended ranges, i.e. without end\n"
        "      specified, for the ``load`` command, even though MPD's general range docs\n"
        "      allows open-ended ranges.\n"
        "\n"
        "    - MPD 0.17.1 does not fail if the specified range is outside the playlist,\n"
        "      in either or both ends.\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "class _MpdLoadPlayerSyncError(exceptions.MpdAckError):\n"
        "    error_code = exceptions.MpdAckError.ACK_ERROR_PLAYER_SYNC\n"
        "\n"
        "\n"
        "def _mpd_load_position(value):\n"
        "    # load の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid と同じ書式)。\n"
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
        "def _mpd_resolve_load_position(context, songpos, old_size):\n"
        "    # (kind, offset) を実際の挿入位置 (0 <= position <= old_size) へ解決する。\n"
        "    # kind is None: 絶対位置。'+': 現在曲の直後基準。'-': 現在曲の直前基準。\n"
        "    kind, offset = songpos\n"
        "    if kind is None:\n"
        "        if offset > old_size:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        return offset\n"
        "    current = context.core.tracklist.index().get()\n"
        "    if current is None:\n"
        '        raise _MpdLoadPlayerSyncError("No current song")\n'
        '    if kind == "+":\n'
        "        if offset > old_size - current - 1:\n"
        '            raise exceptions.MpdArgError("Number too large")\n'
        "        return current + 1 + offset\n"
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n"
        "\n"
        '@protocol.commands.add(\n'
        '    "load", playlist_slice=protocol.RANGE, songpos=_mpd_load_position\n'
        ")\n"
        "def load(context, name, playlist_slice=DEFAULT_PLAYLIST_SLICE, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``load {NAME} [START:END] [POSITION]``\n"
        "\n"
        "        Loads the playlist into the current queue. Playlist plugins are\n"
        "        supported. A range may be specified to load only a part of the\n"
        "        playlist.\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before). Absent, the\n"
        "        loaded tracks are appended to the end of the playlist as before.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        "    - ``load`` appends the given playlist to the current playlist.\n"
        "\n"
        "    - MPD 0.17.1 does not support open-ended ranges, i.e. without end\n"
        "      specified, for the ``load`` command, even though MPD's general range docs\n"
        "      allows open-ended ranges.\n"
        "\n"
        "    - MPD 0.17.1 does not fail if the specified range is outside the playlist,\n"
        "      in either or both ends.\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        position = _mpd_resolve_load_position(context, songpos, old_size)\n"
        "\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.set_last_loaded_playlist(name)\n"
        "\n"
        "    if position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(sp, "w").write(s)
    print("patched stored_playlists.py: load の POSITION に絶対/相対指定 (+N/-N) を追加")
