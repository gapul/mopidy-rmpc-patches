# mopidy_mpd/protocol/stored_playlists.py の `rename {NAME} {NEW_NAME}` が、
# `context.core.playlists.create(new_name, uri_scheme).get()` の戻り値を None
# チェックせずいきなり `.replace()` している不具合。TODO 全項目消化済みのため
# 自走エージェントが mopidy_mpd のコード品質を再調査して発見した項目。
#
# mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.create() は
# `self.backend.api.create_playlist(name, "")` が例外を投げた場合
# (ネットワーク瞬断・YouTube Music側のレート制限/クォータ・重複タイトル・
# 不正な文字・認証切れ等) `logger.exception()` した上で None を返す設計であり、
# 同じファイル内の姉妹関数 `_create_playlist()` (playlistadd が使う) は
# `if new_playlist is None: ... continue` で正しくガードしているのに対し、
# `rename()` だけ create() の戻り値を無条件に `.replace()` している非対称な
# 実装だったと判明。実害: create() が None を返すと
# `AttributeError: 'NoneType' object has no attribute 'replace'` という素の
# Exception が送出される。これは exceptions.MpdAckError のサブクラスではないため
# mopidy_mpd/dispatcher.py の `_catch_mpd_ack_errors_filter` に捕捉されず、
# mopidy_mpd/session.py の `on_line_received` にも try/except が無いため、
# pykka アクターの `on_receive` の外まで伝播し network.LineProtocol.on_failure
# (`self.connection.stop("Actor failed.")`) に到達する。結果、クライアントには
# ACK エラーが一切返らずTCP接続そのものが問答無用で切断される
# (rmpc から見れば `rename` を送っただけでサーバーとの接続が落ちる)。
#
# 修正: `_create_playlist()`/`playlistadd`/`playlistclear` 等と同じ流儀で、
# create() 直後に None チェックを追加し、None なら
# `exceptions.MpdFailedToSavePlaylist(uri_scheme)` を送出する
# (以後の `.replace()`/`save()` には到達させない)。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

NEW = (
    "    uri_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
    "    new_playlist = context.core.playlists.create(new_name, uri_scheme).get()\n"
    "    if new_playlist is None:\n"
    "        raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
    "    new_playlist = new_playlist.replace(tracks=old_playlist.tracks)\n"
)

if NEW in s:
    print("rename() create()-None race already patched, skip")
else:
    OLD = (
        "    uri_scheme = urllib.parse.urlparse(old_playlist.uri).scheme\n"
        "    new_playlist = context.core.playlists.create(new_name, uri_scheme).get()\n"
        "    new_playlist = new_playlist.replace(tracks=old_playlist.tracks)\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: rename()のplaylists.create()戻り値Noneを"
        "ガードし、.replace()での素のAttributeError(接続切断)ではなく"
        "他のplaylistadd系コマンドと同様にMpdFailedToSavePlaylistを送出"
    )
