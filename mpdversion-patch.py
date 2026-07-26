# mopidy-mpd 3.3.0 は接続時の greeting (`OK MPD {VERSION}`) を常に固定文字列 "0.19.0"
# で送る (mopidy_mpd/protocol/__init__.py の VERSION 定数、session.py がそのまま使用)。
#
# rmpc (rmpc-mpd) はこの greeting から `client.version()` を実際にパースし、複数の機能を
# バージョンゲートしている (gh clone mierak/rmpc で実際に確認):
#   - rmpc-mpd/src/mpd_client.rs send_get_volume: version < 0.23.0 なら `getvol` 自体を
#     送らずクライアント側で `UnsupportedMpdVersion` エラーにする
#   - rmpc-mpd/src/mpd_client.rs send_consume: version < 0.24.0 かつ Oneshot 指定なら同様に
#     送らずエラーにする
#   - rmpc/src/ui/mod.rs ToggleSingle/ToggleConsume, rmpc/src/core/command.rs
#     Command::ToggleSingle/ToggleConsume: version < 0.21.0/0.24.0 なら oneshot を含まない
#     on/off の2値サイクルにフォールバックし、oneshot 状態へは一切遷移させない
# つまり mpdgetvol-patch.py (getvol, MPD 0.23+) と mpdoneshot-patch.py (single/consume
# oneshot, MPD 0.21+/0.24+) は既にサーバー側で実装・プロトコル単体では検証済みなのに、
# VERSION が "0.19.0" に固定されている限り実際の rmpc クライアントからは一生呼ばれず
# 死んだ実装のままになる、という実害ある新規ギャップ (自走エージェントが rmpc-mpd 本体を
# 実際に clone・調査して発見)。
#
# 対策: VERSION を実装済み機能に見合う "0.24.0" へ引き上げる。ただし version だけ上げると
# 新たに1つ副作用が生じる: rmpc/src/core/event_loop.rs の reflect_changes_to_playlist
# 機能 (mpdlastloadedplaylist-patch.py で既に対応した lastloadedplaylist と対になる
# 機能。opt-in 設定だが既に rmpc 側で存在) が version>=0.24.0 と判定すると
# `save_queue_as_playlist(name, Some(SaveMode::Replace))` (= `save NAME "replace"`) を
# 実際に送るようになる。だが mopidy-mpd の `save` は `save(context, name)` の固定1引数の
# ままで MODE 引数を受け付けないため、この呼び出しが `ACK wrong number of arguments` に
# なり機能が壊れる (version bump 単体では新規リグレッションになる)。そのため本パッチは
# 同時に `save {NAME} [MODE]` (MPD 0.24+, MusicPlayerDaemon/MPD
# src/command/PlaylistCommands.cxx handle_save / src/PlaylistSave.cxx spl_save_queue を
# 実際に clone してソース確認した仕様) にも対応する:
#   - MODE省略時: 既存の mopidy 挙動 (無ければ作成・あれば上書き) を無変更で維持
#     (旧来の rmpc呼び出し・過去 backlog で検証済みの `save` 単体動作の回帰を避けるため、
#     実MPDの「MODE省略時はcreate扱いで存在すればエラー」という仕様はあえて踏襲しない)
#   - "create": 既存なら `ACK Playlist already exists` (実MPDと同じ)
#   - "append": 存在しなければ `ACK No such playlist`、存在すれば末尾に現在のキューを追記
#   - "replace": 存在しなければ `ACK No such playlist`、存在すれば現在のキューで丸ごと上書き
#   - 不明なMODE: `ACK Unrecognized save mode, expected one of 'create', 'append', 'replace'`
#     (実MPDのエラー文言をそのまま踏襲)
# 追記: mpdstringnorm-patch.py で `stringnormalization` (MPD 0.25+) を実装したため、
# `version < 0.25.0` に留めていた上記の理由は解消した。VERSION を "0.25.0" へ引き上げ、
# rmpc/src/ui/panes/search/mod.rs の `strip_diacritics_supported: ctx.mpd_version >=
# Version::new(0, 25, 0)` を実際に満たして検索ペインの「Ignore diacritics」トグルを
# 表示・機能させる (rmpc-mpd/src/mpd_client.rs 全体、rmpc/src/ui/mod.rs、
# rmpc/src/core/command.rs を実際に grep し、0.25.0 でこれ以外に新規ゲートされる機能が
# 無いことも確認済み)。

ip = "mopidy_mpd/protocol/__init__.py"
s = open(ip).read()

MARKER = 'VERSION = "0.25.0"'
if MARKER in s:
    print("protocol/__init__.py already patched, skip")
else:
    anchor_2019 = '#: The MPD protocol version is 0.19.0.\nVERSION = "0.19.0"\n'
    anchor_2024 = (
        "#: The MPD protocol version we report to clients. Kept in sync with the\n"
        "#: highest MPD version whose behaviour configs/media/mopidy/*.py patches\n"
        "#: (getvol 0.23+, oneshot/mount/partition/save-mode/lastloadedplaylist 0.24+)\n"
        "#: actually implement, so that version-gated rmpc-mpd client features fire.\n"
        'VERSION = "0.24.0"\n'
    )
    replacement = (
        "#: The MPD protocol version we report to clients. Kept in sync with the\n"
        "#: highest MPD version whose behaviour configs/media/mopidy/*.py patches\n"
        "#: (getvol 0.23+, oneshot/mount/partition/save-mode/lastloadedplaylist 0.24+,\n"
        "#: stringnormalization 0.25+) actually implement, so that version-gated\n"
        "#: rmpc-mpd client features fire.\n"
        'VERSION = "0.25.0"\n'
    )
    if anchor_2024 in s:
        assert s.count(anchor_2024) == 1, f"anchor_2024 count={s.count(anchor_2024)}"
        s = s.replace(anchor_2024, replacement, 1)
    else:
        assert s.count(anchor_2019) == 1, f"anchor_2019 count={s.count(anchor_2019)}"
        s = s.replace(anchor_2019, replacement, 1)
    open(ip, "w").write(s)
    print("patched protocol/__init__.py: VERSION を 0.25.0 に引き上げ")

pp = "mopidy_mpd/protocol/stored_playlists.py"
s2 = open(pp).read()

MARKER2 = 'def save(context, name, mode=None):'
if MARKER2 in s2:
    print("stored_playlists.py already patched, skip")
else:
    old_save = (
        '@protocol.commands.add("save")\n'
        "def save(context, name):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``save {NAME}``\n"
        "\n"
        "        Saves the current playlist to ``NAME.m3u`` in the playlist\n"
        "        directory.\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    tracks = context.core.tracklist.get_tracks().get()\n"
        "    playlist = _get_playlist(context, name, must_exist=False)\n"
        "    if not playlist:\n"
        "        # Create new playlist\n"
        "        _create_playlist(context, name, tracks)\n"
        "    else:\n"
        "        # Overwrite existing playlist\n"
        "        new_playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    assert s2.count(old_save) == 1, f"old_save count={s2.count(old_save)}"
    new_save = (
        '@protocol.commands.add("save")\n'
        "def save(context, name, mode=None):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``save {NAME} [MODE]``\n"
        "\n"
        "        Saves the current playlist to ``NAME.m3u`` in the playlist\n"
        "        directory.\n"
        "\n"
        "        ``MODE`` (MPD 0.24+): one of ``create``, ``append`` or\n"
        "        ``replace``. If omitted, an existing playlist named ``NAME``\n"
        "        is silently overwritten (legacy Mopidy behaviour, kept for\n"
        "        backwards compatibility).\n"
        '    """\n'
        "    _check_playlist_name(name)\n"
        "    if mode is not None and mode not in (\"create\", \"append\", \"replace\"):\n"
        "        raise exceptions.MpdArgError(\n"
        "            \"Unrecognized save mode, expected one of 'create', \"\n"
        "            \"'append', 'replace'\"\n"
        "        )\n"
        "    tracks = context.core.tracklist.get_tracks().get()\n"
        "    playlist = _get_playlist(context, name, must_exist=False)\n"
        "    if mode == \"create\" and playlist:\n"
        "        raise exceptions.MpdExistError(\"Playlist already exists\")\n"
        "    if mode in (\"append\", \"replace\") and not playlist:\n"
        "        raise exceptions.MpdNoExistError(\"No such playlist\")\n"
        "    if mode == \"append\":\n"
        "        new_playlist = playlist.replace(\n"
        "            tracks=list(playlist.tracks) + tracks\n"
        "        )\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
        "    elif not playlist:\n"
        "        # Create new playlist (mode is None or \"create\")\n"
        "        _create_playlist(context, name, tracks)\n"
        "    else:\n"
        "        # Overwrite existing playlist (mode is None or \"replace\")\n"
        "        new_playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    s2 = s2.replace(old_save, new_save, 1)
    open(pp, "w").write(s2)
    print("patched stored_playlists.py: save に MODE (create/append/replace) を追加")
