# mpdaddpos-patch.py/mpdloadpos-patch.py の `add`/`load` の POSITION 実装に、
# `prio`/`prioid` (mpdprio-patch.py で修正済み) と同種の TOCTOU レースが残っている。
#
# 現在の実装は「まず末尾へ追加してから、[追加前の長さ, 追加後の長さ) という
# 長さの差分レンジを move する」という、実 MPD (MusicPlayerDaemon/MPD
# src/command/QueueCommands.cxx handle_add の MoveRange) の内部アルゴリズムを
# そのまま移植したものだが、これは mopidy core 側で
# get_length() → add() → get_length() → move() という4回の別々の非同期呼び出しに
# 分解されてしまう。実 MPD はこの全体が1コマンドの範囲で不可分に実行されるため
# レースが存在しないが、mopidy-mpd では別クライアントが間に `add`/`delete` 等で
# キューの長さを変えると、[old_size, new_size) の範囲がもはや「自分が追加した
# 曲」と一致しなくなり、無関係な曲を巻き込んで move してしまいキュー順序が
# 静かに破損する (接続断こそしないが prio の TOCTOU と同じ根本原因)。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc/src/config/keys/actions.rs の `Position::AfterCurrentSong`/
# `BeforeCurrentSong` (キーバインド可能な「現在の曲の次/前に追加」) が
# `QueuePosition::RelativeAdd(0)`/`RelativeSub(0)` を生成し、
# rmpc-mpd/src/mpd_client.rs の send_add (559-562行) が `add URI +0`/`-0`、
# send_load_playlist (738-742行) が `load NAME 0: +0` を実際に送信する
# ("次に追加"は日常的に使う操作) と確認した上で着手。
#
# 実は同じファイル内の `addid` (mpdaddid-patch.py) は元からこのレースが無い:
# `context.core.tracklist.add(uris=[uri], at_position=at_position)` を1回
# 呼ぶだけで、mopidy core の tracklist.add() 自体が at_position 引数で
# 複数曲の直接挿入をサポートしている (mopidy/core/tracklist.py Tracklist.add)
# ため、末尾追加+move の2段階を経由する必要が無い。`add`/`load`も同様に
# at_position を直接渡すだけで、末尾追加+move と全く同じ最終順序になり
# (自分の追加分は常に連続しているため)、かつ addid と同じく1回の core 呼び出しに
# 収まるためレース自体が発生しない。よって add()/load() を addid と同じ流儀に
# 揃える形で修正する。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "at_position=position"
if MARKER in s:
    print("add/load race already patched (current_playlist.py), skip")
else:
    old_block = (
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        "    new_tl_tracks = []\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        new_tl_tracks = context.core.tracklist.add(uris=[uri]).get()\n"
        "        if new_tl_tracks:\n"
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
        "        new_tl_tracks = context.core.tracklist.add(uris=uris).get()\n"
        "\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "\n"
        "    if position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    position = None\n"
        "    if songpos is not None:\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        "    new_tl_tracks = []\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=[uri], at_position=position\n"
        "        ).get()\n"
        "        if new_tl_tracks:\n"
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
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=uris, at_position=position\n"
        "        ).get()\n"
        "\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print("patched current_playlist.py: add() の POSITION 解決を at_position 直接指定に変更 (末尾追加+move のTOCTOUレースを解消)")

sp = "mopidy_mpd/protocol/stored_playlists.py"
t = open(sp).read()

if MARKER in t:
    print("add/load race already patched (stored_playlists.py), skip")
else:
    old_block = (
        "    playlist = _get_playlist(context, name)\n"
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        position = _mpd_resolve_load_position(context, songpos, old_size)\n"
        "\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    new_tl_tracks = context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "    translator.set_last_loaded_playlist(name)\n"
        "\n"
        "    if position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert t.count(old_block) == 1, f"old_block count={t.count(old_block)}"

    new_block = (
        "    playlist = _get_playlist(context, name)\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_load_position(context, songpos, old_size)\n"
        "\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=track_uris, at_position=position\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert new_block != old_block
    t = t.replace(old_block, new_block, 1)
    open(sp, "w").write(t)
    print("patched stored_playlists.py: load() の POSITION 解決を at_position 直接指定に変更 (末尾追加+move のTOCTOUレースを解消)")
