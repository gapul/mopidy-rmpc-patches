# mopidy_mpd/protocol/music_db.py の `searchaddpl {NAME} {FILTER} [...]` (対象
# プレイリストが未存在で新規作成する経路) と mopidy_mpd/protocol/stored_playlists.py
# の `playlistclear {NAME}` (同じく未存在なら新規作成する経路) が、どちらも
# `context.core.playlists.create(name).get()` の戻り値を None チェックせずいきなり
# `.replace()` している不具合。TODO 全項目消化済みのため自走エージェントが
# mopidy_mpd のコード品質を再調査して発見した項目。
#
# mopidy.core.playlists.create() の docstring 通り、対応するバックエンドが無い/
# 生成に失敗した場合は None を返しうる (mopidy_ytmusic.playlist.
# YTMusicPlaylistsProvider.create() は `api.create_playlist()` が例外
# (ネットワーク瞬断・レート制限・認証切れ等) を投げると logger.exception() した上で
# None を返す設計であり実際に踏みうる)。同じ create()-None 未チェックのバグは
# stored_playlists.py の `rename()` に対して既に mpdrenamefix-patch.py で修正済みだが、
# `searchaddpl()`/`playlistclear()` の2箇所は対象外のまま残っていた
# (`_create_playlist()` ヘルパーは正しく None チェックしているのに対し非対称)。
# 実害: `playlist.replace(...)` が素の
# `AttributeError: 'NoneType' object has no attribute 'replace'` を送出し、これは
# exceptions.MpdAckError のサブクラスではないため dispatcher.py の
# `_catch_mpd_ack_errors_filter` に捕捉されず、session.py にも try/except が無いため
# pykka アクターの外まで伝播し network.LineProtocol.on_failure
# (`self.connection.stop("Actor failed.")`) に到達、ACK エラーが一切返らずTCP接続
# そのものが問答無用で切断される (rmpc から見ればコマンドを送っただけでサーバーとの
# 接続が落ちる)。
#
# 修正: `rename()`/`_create_playlist()` と同じ流儀で、create() 直後に None
# チェックを追加し、None なら
# `exceptions.MpdFailedToSavePlaylist(default_scheme)` を送出する (以後の
# `.replace()`/`save()` には到達させない)。scheme はどちらの呼び出しも
# `create(name)` で URI スキーム未指定 (対象URIが無いため既存playlistのuriから
# 逆算できない) なので、`_create_playlist()` のフォールバック経路と同じく
# `context.dispatcher.config["mpd"]["default_playlist_scheme"]` を使う。

import ast

MUSIC_DB = "mopidy_mpd/protocol/music_db.py"
STORED_PLAYLISTS = "mopidy_mpd/protocol/stored_playlists.py"

# --- music_db.py: searchaddpl() ---
s = open(MUSIC_DB).read()

NEW_SEARCHADDPL = (
    "    if not playlist:\n"
    "        playlist = context.core.playlists.create(playlist_name).get()\n"
    "        if playlist is None:\n"
    '            default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
    "            raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
    "    playlist = playlist.replace(tracks=tracks)\n"
)

if NEW_SEARCHADDPL in s:
    print("searchaddpl() create()-None guard already patched, skip")
else:
    OLD_SEARCHADDPL = (
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
    )
    assert s.count(OLD_SEARCHADDPL) == 1, f"OLD_SEARCHADDPL count={s.count(OLD_SEARCHADDPL)}"
    s = s.replace(OLD_SEARCHADDPL, NEW_SEARCHADDPL, 1)

    open(MUSIC_DB, "w").write(s)
    ast.parse(s)
    print(
        "patched music_db.py: searchaddpl()のplaylists.create()戻り値Noneを"
        "ガードし、.replace()での素のAttributeError(接続切断)ではなく"
        "MpdFailedToSavePlaylistを送出"
    )

# --- stored_playlists.py: playlistclear() ---
s = open(STORED_PLAYLISTS).read()

NEW_PLAYLISTCLEAR = (
    "    playlist = _get_playlist(context, name, must_exist=False)\n"
    "    if not playlist:\n"
    "        playlist = context.core.playlists.create(name).get()\n"
    "        if playlist is None:\n"
    '            default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
    "            raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
    "\n"
    "    # Just replace tracks with empty list and save\n"
    "    playlist = playlist.replace(tracks=[])\n"
)

if NEW_PLAYLISTCLEAR in s:
    print("playlistclear() create()-None guard already patched, skip")
else:
    OLD_PLAYLISTCLEAR = (
        "    playlist = _get_playlist(context, name, must_exist=False)\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(name).get()\n"
        "\n"
        "    # Just replace tracks with empty list and save\n"
        "    playlist = playlist.replace(tracks=[])\n"
    )
    assert s.count(OLD_PLAYLISTCLEAR) == 1, f"OLD_PLAYLISTCLEAR count={s.count(OLD_PLAYLISTCLEAR)}"
    s = s.replace(OLD_PLAYLISTCLEAR, NEW_PLAYLISTCLEAR, 1)

    open(STORED_PLAYLISTS, "w").write(s)
    ast.parse(s)
    print(
        "patched stored_playlists.py: playlistclear()のplaylists.create()戻り値"
        "Noneをガードし、.replace()での素のAttributeError(接続切断)ではなく"
        "MpdFailedToSavePlaylistを送出"
    )
