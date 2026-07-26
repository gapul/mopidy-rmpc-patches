# mopidy_mpd/protocol/stored_playlists.py の playlistadd/playlistclear/
# playlistdelete/playlistmove/rename/save は、いずれも「stored playlistの現在の
# 内容を _get_playlist() で読む -> ローカルで加工 -> context.core.playlists.save()
# (または create()+delete()) で書き戻す」という read-modify-write を、一切のロック
# 無しで行っている。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# mopidy_mpd のコード品質を再調査して新規発見した項目 (mpdvolumerace-patch.py/
# mpdoutputtogglerace-patch.py が mixer の get->set について既に修正済みの
# 「複合actor呼び出しの間にロックが無い」構造的パターンだが、対象がストアド
# プレイリストの本体データという点でより実害が大きい)。
#
# 実害: mopidy_mpd は各クライアント接続を別OSスレッドの pykka.ThreadingActor
# (MpdSession) として実行する。2本の接続がほぼ同時に同じストアドプレイリストへ
# `playlistadd` (あるいは他の編集コマンド) を送ると、両方が _get_playlist() で
# 同じ「変更前」の内容を読み、それぞれの変更を加えた上で各自 save() を呼ぶため、
# 後勝ちの save() が先行クライアントの変更を踏み潰す (lost update)。
#
# mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.save() (playlist.py) は
# 「渡された playlist.tracks を目的状態とし、save() 呼び出し時点でYTM側から
# 改めて取得した実際の現在状態との Counter 差分だけを add/remove
# API へ送る」設計 (`removeCounts = oldCounts - newCounts` /
# `addCounts = newCounts - oldCounts`)。そのため後勝ちの save() は自分が読んだ
# 古い状態を「目的状態」として渡してしまい、その時点で実際にYTM側に存在する
# (先行クライアントが追加した) 曲は newCounts に含まれず removeCounts に回って
# **実際にYouTube Music側から削除される**。
#
# 具体的な再現: プレイリスト"Test"に[X, Y]がある状態で、接続Aが
# `playlistadd "Test" trackA`、接続Bがほぼ同時に`playlistadd "Test" trackB`を
# 送る。両方とも_get_playlist()で[X,Y]を読み、Aが先にsave()して実際の状態は
# [X,Y,A]になる。Bは自分が読んだ古い[X,Y]+trackBを目的状態としてsave()するが、
# save()内部でYTM側から取得し直す最新状態は[X,Y,A]なので
# oldCounts={X,Y,A}, newCounts={X,Y,B} となり、Aがremove対象に回って削除される。
# 最終的にプレイリストは[X,Y,B]のみとなり、Aが追加した曲は跡形もなく消える。
# 両方の`playlistadd`ともクライアントにはOKが返っており、ACKエラーは一切出ない
# サイレントなデータ消失。
#
# 修正: mpdvolumerace-patch.py/mpdoutputtogglerace-patch.pyと同じ流儀で、
# stored_playlists.pyにモジュールレベルの`threading.Lock()`
# (`_stored_playlist_edit_lock`)を導入し、playlistadd/playlistclear/
# playlistdelete/playlistmove/rename/saveの「読み取り→加工→save()(または
# create()+delete())」区間を`with`ブロックで直列化する。バックエンドへの実
# ネットワーク呼び出しを含むためロック保持時間は他の対策 (mixer等) より
# 長くなりうるが、ストアドプレイリスト編集はstatus/idleのような高頻度の
# ホットパスではなく、サイレントなデータ消失を防ぐことを優先する。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

MARKER = "_stored_playlist_edit_lock"
if MARKER in s:
    print("mpdplaylisteditrace already applied to stored_playlists.py, skip")
else:
    # 1) import threading
    old_import = (
        "import datetime\n"
        "import logging\n"
        "import re\n"
        "import urllib\n"
    )
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "import datetime\n"
        "import logging\n"
        "import re\n"
        "import threading\n"
        "import urllib\n"
    )
    s = s.replace(old_import, new_import, 1)

    # 2) モジュールレベルLock定義 (loggerの直後)
    old_logger = 'logger = logging.getLogger(__name__)\n'
    assert s.count(old_logger) == 1, f"old_logger count={s.count(old_logger)}"
    new_logger = (
        'logger = logging.getLogger(__name__)\n'
        "\n"
        "# playlistadd/playlistclear/playlistdelete/playlistmove/rename/save は\n"
        "# 全クライアント接続間で共有される同一のストアドプレイリストに対し\n"
        "# 「読み取り→加工→save()」というread-modify-writeを行うため、\n"
        "# Lockで直列化する(mpdplaylisteditrace-patch.py)。\n"
        "_stored_playlist_edit_lock = threading.Lock()\n"
    )
    s = s.replace(old_logger, new_logger, 1)

    # 3) playlistadd(): 読み取り〜save()/_create_playlist()区間をロックで保護
    old_playlistadd = (
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
        "    if not new_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
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
    assert s.count(old_playlistadd) == 1, f"old_playlistadd count={s.count(old_playlistadd)}"
    new_playlistadd = (
        "    _check_playlist_name(name)\n"
        "    with _stored_playlist_edit_lock:\n"
        "        old_playlist = _get_playlist(context, name, must_exist=False)\n"
        "        old_tracks = list(old_playlist.tracks) if old_playlist else []\n"
        "        if position is not None and position > len(old_tracks):\n"
        '            raise exceptions.MpdArgError("Bad position")\n'
        "\n"
        "        lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "        new_tracks = [\n"
        "            track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "        ]\n"
        "        if not new_tracks:\n"
        '            raise exceptions.MpdNoExistError("No such song")\n'
        "\n"
        "        if position is None:\n"
        "            combined_tracks = old_tracks + new_tracks\n"
        "        else:\n"
        "            combined_tracks = (\n"
        "                old_tracks[:position] + new_tracks + old_tracks[position:]\n"
        "            )\n"
        "\n"
        "        if not old_playlist:\n"
        "            # Create new playlist with this single track (POSITION is\n"
        "            # irrelevant here: an empty playlist only accepts position 0,\n"
        "            # already enforced above, and combined_tracks == new_tracks)\n"
        "            _create_playlist(context, name, combined_tracks)\n"
        "        else:\n"
        "            # Add track(s) to existing playlist, at POSITION if given\n"
        "            new_playlist = old_playlist.replace(tracks=combined_tracks)\n"
        "            saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "            if saved_playlist is None:\n"
        "                playlist_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "                uri_scheme = urllib.parse.urlparse(track_uri).scheme\n"
        "                raise exceptions.MpdInvalidTrackForPlaylist(\n"
        "                    playlist_scheme, uri_scheme\n"
        "                )\n"
    )
    s = s.replace(old_playlistadd, new_playlistadd, 1)

    # 4) playlistclear(): 読み取り〜save()区間をロックで保護
    old_playlistclear = (
        "    _check_playlist_name(name)\n"
        "    playlist = _get_playlist(context, name, must_exist=False)\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(name).get()\n"
        "        if playlist is None:\n"
        '            default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
        "            raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
        "\n"
        "    # Just replace tracks with empty list and save\n"
        "    playlist = playlist.replace(tracks=[])\n"
        "    if context.core.playlists.save(playlist).get() is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert s.count(old_playlistclear) == 1, f"old_playlistclear count={s.count(old_playlistclear)}"
    new_playlistclear = (
        "    _check_playlist_name(name)\n"
        "    with _stored_playlist_edit_lock:\n"
        "        playlist = _get_playlist(context, name, must_exist=False)\n"
        "        if not playlist:\n"
        "            playlist = context.core.playlists.create(name).get()\n"
        "            if playlist is None:\n"
        '                default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
        "                raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
        "\n"
        "        # Just replace tracks with empty list and save\n"
        "        playlist = playlist.replace(tracks=[])\n"
        "        if context.core.playlists.save(playlist).get() is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    s = s.replace(old_playlistclear, new_playlistclear, 1)

    # 5) playlistdelete(): 読み取り〜save()区間をロックで保護
    old_playlistdelete = (
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
    assert s.count(old_playlistdelete) == 1, f"old_playlistdelete count={s.count(old_playlistdelete)}"
    new_playlistdelete = (
        "    _check_playlist_name(name)\n"
        "    with _stored_playlist_edit_lock:\n"
        "        playlist = _get_playlist(context, name)\n"
        "\n"
        "        tracks = list(playlist.tracks)\n"
        "        start = songrange.start\n"
        "        end = songrange.stop\n"
        "        if start > len(tracks):\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        if end is None or end > len(tracks):\n"
        "            end = len(tracks)\n"
        "        del tracks[start:end]\n"
        "\n"
        "        # Replace tracks and save playlist\n"
        "        playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    s = s.replace(old_playlistdelete, new_playlistdelete, 1)

    # 6) playlistmove(): 読み取り〜save()区間をロックで保護 (start==to_pos の
    #    early return と open-ended range チェックはロック不要のためそのまま)
    old_playlistmove = (
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
    assert s.count(old_playlistmove) == 1, f"old_playlistmove count={s.count(old_playlistmove)}"
    new_playlistmove = (
        "    _check_playlist_name(name)\n"
        "    with _stored_playlist_edit_lock:\n"
        "        playlist = _get_playlist(context, name)\n"
        "\n"
        "        tracks = list(playlist.tracks)\n"
        "        count = end - start\n"
        "        if end > len(tracks) or to_pos > len(tracks) - count:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "\n"
        "        # Cut the range out, then insert it at to_pos in the *remaining*\n"
        "        # list, matching real MPD's PlaylistFileEditor::MoveIndex.\n"
        "        moved = tracks[start:end]\n"
        "        del tracks[start:end]\n"
        "        tracks[to_pos:to_pos] = moved\n"
        "\n"
        "        # Replace tracks and save playlist\n"
        "        playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    s = s.replace(old_playlistmove, new_playlistmove, 1)

    # 7) rename(): 読み取り〜create()+save()+delete()区間をロックで保護
    old_rename = (
        "    old_playlist = _get_playlist(context, old_name)\n"
        "\n"
        "    if _get_playlist(context, new_name, must_exist=False):\n"
        '        raise exceptions.MpdExistError("Playlist already exists")\n'
        "    # TODO: should we purge the mapping in an else?\n"
        "\n"
        "    # Create copy of the playlist and remove original\n"
        "    uri_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "    new_playlist = context.core.playlists.create(new_name, uri_scheme).get()\n"
        "    if new_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
        "    new_playlist = new_playlist.replace(tracks=old_playlist.tracks)\n"
        "    saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
        "    if not context.core.playlists.delete(old_playlist.uri).get():\n"
        '        raise exceptions.MpdSystemError("Failed to delete playlist")\n'
    )
    assert s.count(old_rename) == 1, f"old_rename count={s.count(old_rename)}"
    new_rename = (
        "    with _stored_playlist_edit_lock:\n"
        "        old_playlist = _get_playlist(context, old_name)\n"
        "\n"
        "        if _get_playlist(context, new_name, must_exist=False):\n"
        '            raise exceptions.MpdExistError("Playlist already exists")\n'
        "        # TODO: should we purge the mapping in an else?\n"
        "\n"
        "        # Create copy of the playlist and remove original\n"
        "        uri_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "        new_playlist = context.core.playlists.create(new_name, uri_scheme).get()\n"
        "        if new_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
        "        new_playlist = new_playlist.replace(tracks=old_playlist.tracks)\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
        "        if not context.core.playlists.delete(old_playlist.uri).get():\n"
        '            raise exceptions.MpdSystemError("Failed to delete playlist")\n'
    )
    s = s.replace(old_rename, new_rename, 1)

    # 8) save(): _get_playlist()〜save()/_create_playlist()区間をロックで保護
    #    (mode検証自体はロック不要のためそのまま)
    old_save = (
        "    tracks = context.core.tracklist.get_tracks().get()\n"
        "    playlist = _get_playlist(context, name, must_exist=False)\n"
        '    if mode == "create" and playlist:\n'
        '        raise exceptions.MpdExistError("Playlist already exists")\n'
        '    if mode in ("append", "replace") and not playlist:\n'
        '        raise exceptions.MpdNoExistError("No such playlist")\n'
        '    if mode == "append":\n'
        "        new_playlist = playlist.replace(\n"
        "            tracks=list(playlist.tracks) + tracks\n"
        "        )\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
        "    elif not playlist:\n"
        '        # Create new playlist (mode is None or "create")\n'
        "        _create_playlist(context, name, tracks)\n"
        "    else:\n"
        '        # Overwrite existing playlist (mode is None or "replace")\n'
        "        new_playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(new_playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    assert s.count(old_save) == 1, f"old_save count={s.count(old_save)}"
    new_save = (
        "    with _stored_playlist_edit_lock:\n"
        "        tracks = context.core.tracklist.get_tracks().get()\n"
        "        playlist = _get_playlist(context, name, must_exist=False)\n"
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
    s = s.replace(old_save, new_save, 1)

    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: playlistadd/playlistclear/playlistdelete/"
        "playlistmove/rename/saveのread-modify-write(_get_playlist()→save())を"
        "threading.Lockで直列化し、複数クライアントが同じストアドプレイリストへ"
        "ほぼ同時に編集を送った際のlost update(ytmusicバックエンドでは"
        "先行クライアントが追加した曲が実際にYouTube Music側から削除される"
        "サイレントなデータ消失)を解消"
    )
