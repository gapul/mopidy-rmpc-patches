# `playlistadd {NAME} {URI} [POSITION]` (MPD 0.23.3+): mopidy-mpd 3.3.0 の
# `playlistadd` は `name`/`track_uri` の固定2引数のみで、実 MPD 0.23.3+ が追加した
# 第3引数 POSITION (ストアドプレイリスト内の挿入位置、絶対インデックスのみ・
# add/addid/load の相対 +N/-N とは異なる) を一切受け付けない。TODO 全項目消化済みの
# ため自走エージェントが rmpc 本体 (mierak/rmpc, /private/tmp/rmpc-check に既存の
# clone を再利用) の rmpc-mpd/src/mpd_client.rs 全 `send_*` を洗い出したところ、
# `send_add_to_playlist(playlist_name, uri, target_position: Option<usize>)` が
# `target_position` 付きで `playlistadd NAME URI POSITION` を送るコード経路を実装
# 済みと判明。呼び出し元 (rmpc/src/ui/panes/queue.rs, rmpc/src/shared/mpd_client_ext.rs)
# を grep したところ現状は全て `None` 固定で送信しており、addid/add/load の
# POSITION 追加時のように「rmpc の実際のキーバインド操作から到達する」実害の
# 確証は得られなかった。ただし mixrampdb/mixrampdelay (mpdmixramp-patch.py)・
# outputs の plugin (mpdoutputplugin-patch.py)・decoders (mpddecoders-patch.py)・
# replay_gain_mode/status (mpdreplaygain-patch.py)・clearerror
# (mpdclearerror-patch.py) と同じく「rmpc固有ではなく標準 MPD プロトコル準拠の
# 不備」に該当すると判断: 実 MPD (MusicPlayerDaemon/MPD
# src/command/PlaylistCommands.cxx handle_playlistadd/handle_playlistadd_position)
# を gh api で実際にソース確認したところ、POSITION 付きの3引数フォームは
# MPD 0.23.3 で追加された正式な仕様であり、mpc・ncmpcpp 等の汎用 MPD クライアントは
# もちろん、rmpc 自身も (現状 None 固定とはいえ) 未来のバージョンで POSITION を
# 使い始めた場合に送信するコード自体は既に持っている。固定2引数の現状では余分な
# トークンが `ACK wrong number of arguments` になり、POSITION 付きの呼び出しは
# 一律拒否される。
#
# 仕様確定 (gh api で実ソース確認、PlaylistCommands.cxx handle_playlistadd_position):
# - POSITION は絶対インデックスのみ (add/addid/load と違い相対 +N/-N 書式は無い、
#   `args.ParseUnsigned(2)` で単純な非負整数として読む)。
# - `position > editor.size()` (対象プレイリストの現在の曲数、存在しなければ0)
#   なら `ACK_ERROR_ARG` ("Bad position") で拒否。`position == size` (末尾) は許可。
# - 許可範囲内なら該当位置に挿入して保存。
#
# mopidy_mpd の playlistadd は URI 1件を core.library.lookup() で解決して
# 0..N 件の Track へ展開し、既存プレイリストの末尾に追加してから
# core.playlists.save() する実装 (Track 単位の挿入ではなく、解決結果の集合を
# 丸ごとリストへ足すだけ)。POSITION 指定時はこの「追加する集合」を末尾ではなく
# 指定位置へスライス挿入するよう変更するだけで、add/addid/load のような
# 「一旦末尾に追加してから範囲を move する」二段構えは不要 (tracklist.move() に
# 相当する概念がストアドプレイリスト側には無いため、そのまま argmuent の
# 集合をトラックリストへ直接スライス挿入すれば済む)。

sp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(sp).read()

ANCHOR = '@protocol.commands.add("playlistadd", position=protocol.UINT)'
if ANCHOR in s:
    print("playlistadd position already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("playlistadd")\n'
        "def playlistadd(context, name, track_uri):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistadd {NAME} {URI}``\n"
        "\n"
        "        Adds ``URI`` to the playlist ``NAME.m3u``.\n"
        "\n"
        "        ``NAME.m3u`` will be created if it does not exist.\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    old_playlist = _get_playlist(context, name, must_exist=False)\n"
        "    if not old_playlist:\n"
        "        # Create new playlist with this single track\n"
        "        lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "        tracks = [\n"
        "            track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "        ]\n"
        "        _create_playlist(context, name, tracks)\n"
        "    else:\n"
        "        # Add track to existing playlist\n"
        "        lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "        new_tracks = [\n"
        "            track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "        ]\n"
        "        new_playlist = old_playlist.replace(\n"
        "            tracks=list(old_playlist.tracks) + new_tracks\n"
        "        )\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            playlist_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "            uri_scheme = urllib.parse.urlparse(track_uri).scheme\n"
        "            raise exceptions.MpdInvalidTrackForPlaylist(\n"
        "                playlist_scheme, uri_scheme\n"
        "            )\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("playlistadd", position=protocol.UINT)\n'
        "def playlistadd(context, name, track_uri, position=None):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistadd {NAME} {URI} [POSITION]``\n"
        "\n"
        "        Adds ``URI`` to the playlist ``NAME.m3u``.\n"
        "\n"
        "        ``NAME.m3u`` will be created if it does not exist.\n"
        "\n"
        "        ``POSITION`` specifies where the songs will be inserted into the\n"
        "        playlist (an absolute, 0-based index; it may not exceed the\n"
        "        playlist's current length). Absent, the track(s) are appended to\n"
        "        the end of the playlist as before.\n"
        "\n"
        "    .. versionadded:: 0.23.3\n"
        "        The ``POSITION`` parameter, new in MPD protocol version 0.23.3\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    old_playlist = _get_playlist(context, name, must_exist=False)\n"
        "    old_tracks = list(old_playlist.tracks) if old_playlist else []\n"
        "    if position is not None and position > len(old_tracks):\n"
        '        raise exceptions.MpdArgError("Bad position")\n'
        "\n"
        "    lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "    new_tracks = [\n"
        "        track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "    ]\n"
        "\n"
        "    if position is None:\n"
        "        combined_tracks = old_tracks + new_tracks\n"
        "    else:\n"
        "        combined_tracks = (\n"
        "            old_tracks[:position] + new_tracks + old_tracks[position:]\n"
        "        )\n"
        "\n"
        "    if not old_playlist:\n"
        "        # Create new playlist with this single track (POSITION is\n"
        "        # irrelevant here: an empty playlist only accepts position 0,\n"
        "        # already enforced above, and combined_tracks == new_tracks)\n"
        "        _create_playlist(context, name, combined_tracks)\n"
        "    else:\n"
        "        # Add track(s) to existing playlist, at POSITION if given\n"
        "        new_playlist = old_playlist.replace(tracks=combined_tracks)\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            playlist_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "            uri_scheme = urllib.parse.urlparse(track_uri).scheme\n"
        "            raise exceptions.MpdInvalidTrackForPlaylist(\n"
        "                playlist_scheme, uri_scheme\n"
        "            )\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(sp, "w").write(s)
    print(
        "patched stored_playlists.py: playlistadd に POSITION (絶対インデックス、MPD0.23.3+) を追加"
    )
