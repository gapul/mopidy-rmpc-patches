# mpdversion-patch.py が `save {NAME} [MODE]` (MPD 0.24+) を実装した際、MODE省略時は
# 「無ければ作成・あれば上書き」という旧来の mopidy 挙動を意図的に維持した(自身のコメント:
# 「旧来のrmpc呼び出し・過去backlogで検証済みのsave単体動作の回帰を避けるため、実MPDの
# 『MODE省略時はcreate扱いで存在すればエラー』という仕様はあえて踏襲しない」)。
#
# だがこの判断は実MPDとの比較のみで、rmpc本体(mierak/rmpc)がMODE省略のsaveをどう使うかは
# 未検証だった。実際に clone して確認すると、rmpc は3箇所全てで MODE省略(None)の
# save_queue_as_playlist を呼んでおり、いずれも実MPDの「既存なら拒否」という安全装置に
# 依存している:
#   - rmpc/src/ui/panes/queue.rs (「Save queue as playlist」メニュー、InputModalのタイトルは
#     "Create new playlist" — 新規作成前提のUI)
#   - rmpc/src/core/command.rs (`rmpc save NAME` CLI/キーバインドコマンド)
#   - rmpc/src/shared/mpd_client_ext.rs create_playlist() (「新規プレイリストへ追加」の
#     コンテキストメニューが使うワークアラウンド: MPDは空プレイリストを作成できないため
#     save→playlistclear→複数add をcommand_listで実行。既存名を再利用してしまうと
#     save が黙って上書きし、直後のplaylistclearで元の内容が完全消去される)
# いずれのエラーも rmpc/src/core/client.rs → event_loop.rs の status_error! でユーザーに
# 可視化される設計であり、「既存名なら弾かれてユーザーに通知される」ことを前提にしている。
#
# 実害: rmpc の「Save」コンテキストメニューで既存プレイリスト名を(誤って)入力すると、
# save(MODE省略)が黙って現在のキューで上書きし、直後のplaylistclear+addで元の保存内容が
# 警告もACKも無く完全に失われる。実MPD(src/command/PlaylistCommands.cxx handle_save():
# `PlaylistSaveMode mode = PlaylistSaveMode::CREATE;` がMODE省略時のデフォルト、
# src/PlaylistSave.cxx spl_save_queue()がCREATEモードでFileExists()なら
# `PlaylistError(PlaylistResult::LIST_EXISTS, "Playlist already exists")`を投げる)なら
# この事故は "ACK [56@0] {save} Playlist already exists" で防がれ、既存プレイリストは
# 無変更のまま保たれる。
#
# 修正: MODE省略時を "create" と同一に扱う(既存なら`ACK Playlist already exists`)。
# これはmpdversion-patch.py自身が挙げていた「過去backlogで検証済みのsave単体動作の回帰」
# だが、その検証済み動作自体が実MPD非準拠かつrmpcの実際の依存を見落としたまま書かれた
# 挙動だったと判断し、今回はそちらを実MPD準拠へ修正する。

pp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(pp).read()

MARKER = 'if mode in ("create", None) and playlist:'
if MARKER in s:
    print("stored_playlists.py already patched (save create-default), skip")
else:
    old_doc = (
        '        ``MODE`` (MPD 0.24+): one of ``create``, ``append`` or\n'
        "        ``replace``. If omitted, an existing playlist named ``NAME``\n"
        "        is silently overwritten (legacy Mopidy behaviour, kept for\n"
        "        backwards compatibility).\n"
    )
    assert s.count(old_doc) == 1, f"old_doc count={s.count(old_doc)}"
    new_doc = (
        '        ``MODE`` (MPD 0.24+): one of ``create``, ``append`` or\n'
        "        ``replace``. If omitted, behaves like ``create`` (fails if\n"
        "        a playlist named ``NAME`` already exists), matching real\n"
        "        MPD's default.\n"
    )
    s = s.replace(old_doc, new_doc, 1)

    # mpdplaylisteditrace-patch.py が save() 本体全体を
    # `with _stored_playlist_edit_lock:` で1段階分インデントしているため、
    # mpdversion-patch.py が導入した元のインデントのままではアンカーが一致しない。
    old = (
        '        if mode == "create" and playlist:\n'
        '            raise exceptions.MpdExistError("Playlist already exists")\n'
        '        if mode in ("append", "replace") and not playlist:\n'
        '            raise exceptions.MpdNoExistError("No such playlist")\n'
        '        if mode == "append":\n'
        "            new_playlist = playlist.replace(\n"
        "                tracks=list(playlist.tracks) + tracks\n"
        "            )\n"
        "            saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "            if saved_playlist is None:\n"
        "                raise exceptions.MpdFailedToSavePlaylist(\n"
        "                    urllib.parse.urlparse(playlist.uri).scheme\n"
        "                )\n"
        "        elif not playlist:\n"
        '            # Create new playlist (mode is None or "create")\n'
        "            _create_playlist(context, name, tracks)\n"
        "        else:\n"
        '            # Overwrite existing playlist (mode is None or "replace")\n'
        "            new_playlist = playlist.replace(tracks=tracks)\n"
        "            saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "            if saved_playlist is None:\n"
        "                raise exceptions.MpdFailedToSavePlaylist(\n"
        "                    urllib.parse.urlparse(playlist.uri).scheme\n"
        "                )\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        '        if mode in ("create", None) and playlist:\n'
        '            raise exceptions.MpdExistError("Playlist already exists")\n'
        '        if mode in ("append", "replace") and not playlist:\n'
        '            raise exceptions.MpdNoExistError("No such playlist")\n'
        '        if mode == "append":\n'
        "            new_playlist = playlist.replace(\n"
        "                tracks=list(playlist.tracks) + tracks\n"
        "            )\n"
        "            saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "            if saved_playlist is None:\n"
        "                raise exceptions.MpdFailedToSavePlaylist(\n"
        "                    urllib.parse.urlparse(playlist.uri).scheme\n"
        "                )\n"
        "        elif not playlist:\n"
        '            # Create new playlist (mode is None or "create")\n'
        "            _create_playlist(context, name, tracks)\n"
        "        else:\n"
        '            # Overwrite existing playlist (mode == "replace")\n'
        "            new_playlist = playlist.replace(tracks=tracks)\n"
        "            saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "            if saved_playlist is None:\n"
        "                raise exceptions.MpdFailedToSavePlaylist(\n"
        "                    urllib.parse.urlparse(playlist.uri).scheme\n"
        "                )\n"
    )
    s = s.replace(old, new, 1)
    open(pp, "w").write(s)
    print(
        "patched stored_playlists.py: save の MODE省略時デフォルトを実MPD準拠の"
        " create相当(既存なら拒否)へ変更"
    )
