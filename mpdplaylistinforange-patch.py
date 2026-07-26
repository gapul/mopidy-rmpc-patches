# mopidy-mpd 3.3.0 の `listplaylist`/`listplaylistinfo` (ストアドプレイリスト参照系) は
# NAME のみの固定引数で、実 MPD が MPD 0.24+ で対応する `[START:END]` レンジ指定を
# 一切受け付けない (余分なトークンを渡すと `ACK incorrect arguments`)。TODO 全項目
# 消化済みのため自走エージェントが調査して新規発見・追加した項目。
#
# musicpd.org protocol (WebFetch で確認) と実 MPD (MusicPlayerDaemon/MPD を実際に
# clone して確認) の両方で仕様を確定:
#   - `listplaylist {NAME} [START:END]` / `listplaylistinfo {NAME} [START:END]`
#     (src/command/PlaylistCommands.cxx handle_listplaylist/handle_listplaylistinfo)
#     は共に MPD 0.24+ で範囲指定に対応 (`RangeArg::All()` がデフォルト = 全曲)。
#   - src/playlist/Print.cxx の実装 (playlist_provider_print) は単純にループを
#     start_index/end_index でスキップ/打ち切りするだけで、範囲がプレイリスト長を
#     超えても `playlistdelete`/`playlistmove` と異なりエラーにはならない
#     (Python の list slice と全く同じ「はみ出しは黙って切り詰め」の挙動)。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# `rmpc-mpd/src/mpd_client.rs` の `send_list_playlist_info` は
# `Option<SingleOrRange>` の range 引数を実際に持ち、`self.version() < 0.24.0` を
# 検査した上で `listplaylistinfo {NAME} {RANGE}` を送信するコードパスが存在する
# (現行の rmpc UI 呼び出し箇所は全て None 固定だが、mopidy 側は greeting で
# VERSION=0.25.0 を名乗っている以上、この version gate は通過してしまう —
# バージョン文示と実装の不整合という点で mpdoneshot-patch.py 等の既存項目と同種)。

pp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(pp).read()

MARKER = "def listplaylist(context, name, songrange="
if MARKER in s:
    print("listplaylist/listplaylistinfo range already patched, skip")
else:
    old_listplaylist = (
        '@protocol.commands.add("listplaylist")\n'
        "def listplaylist(context, name):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``listplaylist {NAME}``\n"
        "\n"
        "        Lists the files in the playlist ``NAME.m3u``.\n"
        "\n"
        "    Output format::\n"
        "\n"
        "        file: relative/path/to/file1.flac\n"
        "        file: relative/path/to/file2.ogg\n"
        "        file: relative/path/to/file3.mp3\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        '    return [f"file: {track.uri}" for track in playlist.tracks]\n'
    )
    assert s.count(old_listplaylist) == 1, (
        f"old_listplaylist count={s.count(old_listplaylist)}"
    )

    new_listplaylist = (
        '@protocol.commands.add("listplaylist", songrange=protocol.RANGE)\n'
        "def listplaylist(context, name, songrange=slice(0, None)):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``listplaylist {NAME} [START:END]``\n"
        "\n"
        "        Lists the files in the playlist ``NAME.m3u``. ``START:END``\n"
        "        (MPD 0.24+) limits output to that range of positions; a\n"
        "        range extending past the end of the playlist is silently\n"
        "        truncated rather than treated as an error, matching real\n"
        "        MPD.\n"
        "\n"
        "    Output format::\n"
        "\n"
        "        file: relative/path/to/file1.flac\n"
        "        file: relative/path/to/file2.ogg\n"
        "        file: relative/path/to/file3.mp3\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    return [\n"
        '        f"file: {track.uri}" for track in playlist.tracks[songrange]\n'
        "    ]\n"
    )
    assert new_listplaylist != old_listplaylist
    s = s.replace(old_listplaylist, new_listplaylist, 1)

    old_listplaylistinfo = (
        '@protocol.commands.add("listplaylistinfo")\n'
        "def listplaylistinfo(context, name):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``listplaylistinfo {NAME}``\n"
        "\n"
        "        Lists songs in the playlist ``NAME.m3u``.\n"
        "\n"
        "    Output format:\n"
        "\n"
        "        Standard track listing, with fields: file, Time, Title, Date,\n"
        "        Album, Artist, Track\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks]\n"
        "    tracks_map = context.core.library.lookup(uris=track_uris).get()\n"
        "    tracks = []\n"
        "    for uri in track_uris:\n"
        "        tracks.extend(tracks_map[uri])\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    return translator.playlist_to_mpd_format(playlist, context.session.tagtypes)\n"
    )
    assert s.count(old_listplaylistinfo) == 1, (
        f"old_listplaylistinfo count={s.count(old_listplaylistinfo)}"
    )

    new_listplaylistinfo = (
        '@protocol.commands.add("listplaylistinfo", songrange=protocol.RANGE)\n'
        "def listplaylistinfo(context, name, songrange=slice(0, None)):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``listplaylistinfo {NAME} [START:END]``\n"
        "\n"
        "        Lists songs in the playlist ``NAME.m3u``. ``START:END``\n"
        "        (MPD 0.24+) limits output to that range of positions; a\n"
        "        range extending past the end of the playlist is silently\n"
        "        truncated rather than treated as an error, matching real\n"
        "        MPD.\n"
        "\n"
        "    Output format:\n"
        "\n"
        "        Standard track listing, with fields: file, Time, Title, Date,\n"
        "        Album, Artist, Track\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks[songrange]]\n"
        "    tracks_map = context.core.library.lookup(uris=track_uris).get()\n"
        "    tracks = []\n"
        "    for uri in track_uris:\n"
        "        tracks.extend(tracks_map[uri])\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    return translator.playlist_to_mpd_format(playlist, context.session.tagtypes)\n"
    )
    assert new_listplaylistinfo != old_listplaylistinfo
    s = s.replace(old_listplaylistinfo, new_listplaylistinfo, 1)

    open(pp, "w").write(s)
    print(
        "patched stored_playlists.py: listplaylist/listplaylistinfo に "
        "START:END レンジ指定を追加"
    )
