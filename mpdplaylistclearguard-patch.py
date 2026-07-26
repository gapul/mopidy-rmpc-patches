# `playlistclear {NAME}`(mopidy_mpd/protocol/stored_playlists.py)が対象プレイリスト
# 未存在時、実MPDと異なり黙って新規プレイリストを作成しOKを返してしまう不具合。
# TODO 全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# mpdplaylistcreateguard-patch.py が同じ箇所の `context.core.playlists.create(name)
# .get()` の戻り値None(生成失敗)未チェックによる素のAttributeError(接続切断)は
# 修正済みだが、そのパッチ自身のコメント・BACKLOG.md該当項目のコメントはいずれも
# 「未存在なら新規作成する経路」自体を既存仕様として受け入れており、実MPD準拠性は
# 一度も確認されていなかった。
#
# 実MPD本体(gh rawでsrc/command/PlaylistCommands.cxx handle_playlistclear()を確認)は
# `spl_clear(name)` を呼び、src/PlaylistFile.cxx `spl_clear()` は
# `TruncateFile(path_fs)`(O_CREATなし)を試み、ファイル不在(ENOENT)なら
# `PlaylistError(PlaylistResult::NO_SUCH_LIST, "No such playlist")` を投げる
# (=作成しない)。doc/protocol.rst でも `playlistadd` の項目には
# "NAME.m3u will be created if it does not exist" と明記されているのに対し、
# 直下の `playlistclear` の項目には同様の記述が無く、これは意図的な非対称
# (playlistadd は APPEND_OR_CREATE、playlistclear は非作成の TruncateFile) と確認。
#
# 実害: rmpc等が誤って未存在のプレイリスト名へ `playlistclear` を送ると、ACKも
# 警告も無く空の新規プレイリストがサイレントに作成されてしまう(実MPDなら
# `ACK [50@0] {playlistclear} No such playlist` で拒否されユーザーに可視化される)。
#
# 修正: `_get_playlist(context, name, must_exist=False)` + `playlists.create()`
# フォールバックを削除し、他の兄弟コマンド(listplaylist/listplaylistinfo/rm等)と
# 同じ `_get_playlist(context, name)`(must_exist=True既定、無ければ
# MpdNoExistError("No such playlist")を送出)に置き換える。docstring の
# "The playlist will be created if it does not exist." も実態に合わせ削除。

import ast

STORED_PLAYLISTS = "mopidy_mpd/protocol/stored_playlists.py"

s = open(STORED_PLAYLISTS).read()

NEW_PLAYLISTCLEAR = (
    '    """\n'
    "    *musicpd.org, stored playlists section:*\n"
    "\n"
    "        ``playlistclear {NAME}``\n"
    "\n"
    "        Clears the playlist ``NAME.m3u``.\n"
    '    """\n'
    "    _check_playlist_name(name)\n"
    "    with _stored_playlist_edit_lock:\n"
    "        playlist = _get_playlist(context, name)\n"
    "\n"
    "        # Just replace tracks with empty list and save\n"
    "        playlist = playlist.replace(tracks=[])\n"
)

if NEW_PLAYLISTCLEAR in s:
    print("playlistclear() no-such-playlist guard already patched, skip")
else:
    OLD_PLAYLISTCLEAR = (
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistclear {NAME}``\n"
        "\n"
        "        Clears the playlist ``NAME.m3u``.\n"
        "\n"
        "    The playlist will be created if it does not exist.\n"
        '    """\n'
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
    )
    assert s.count(OLD_PLAYLISTCLEAR) == 1, f"OLD_PLAYLISTCLEAR count={s.count(OLD_PLAYLISTCLEAR)}"
    s = s.replace(OLD_PLAYLISTCLEAR, NEW_PLAYLISTCLEAR, 1)

    open(STORED_PLAYLISTS, "w").write(s)
    ast.parse(s)
    print(
        "patched stored_playlists.py: playlistclear()が未存在プレイリスト名で"
        "黙って新規作成する経路を廃止し、実MPD(spl_clear()のTruncateFile、"
        "作成しない)と同様にMpdNoExistError(No such playlist)を送出"
    )
