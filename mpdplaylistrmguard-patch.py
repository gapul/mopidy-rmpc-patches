# mopidy_mpd/protocol/stored_playlists.py の `rm {NAME}` (ストアドプレイリスト削除)
# が、`context.core.playlists.delete(uri).get()` の戻り値 (bool) を一切確認せず、
# 削除が実際に失敗しても常に `OK` を返してしまう不具合。TODO 全項目消化済みのため
# 自走エージェントが、直近の一連の `.get()` 抜け/戻り値未チェック修正
# (mpdsearchaddplsave-patch.py の save() None 未チェック、
# mpdplaylistcreateguard-patch.py の create() None 未チェック等) と同種のパターンが
# 他にも残っていないか `context.core.playlists.*` の呼び出しを再調査し新規発見・
# 追加した項目。
#
# mopidy.core.playlists.delete() の docstring 通り、削除に失敗した場合
# (対応するバックエンドが無い/バックエンド側で実際の削除に失敗した場合) は
# `False` を返す契約であり、実際に mopidy_ytmusic.playlist.
# YTMusicPlaylistsProvider.delete() は `self.backend.api.delete_playlist(bId)` が
# 例外 (ネットワーク瞬断・認証切れ・既に削除済み等) を投げると `logger.exception()`
# した上で `False` を返す設計、mopidy.m3u.playlists (`save`/`searchaddpl` 等の
# 既定の保存先スキーム) の delete() も unlink() が OSError (Permission denied 等)
# を投げると同様に `False` を返す設計であり、実際に踏みうる。
#
# 実害: 削除が実際には行われていないにも関わらずクライアントには `OK` が返り、
# rmpc 等のクライアントはプレイリストが削除されたと誤認してUIから消してしまうが、
# サーバー側には実際にはまだ残ったまま (次に `listplaylists` すると復活して見える
# か、あるいは単に消せていないことに気づけない) という不整合が生じる。
#
# 修正: `save`/`searchaddpl`/`playlistclear`/`playlistadd` 等と同じ流儀で、
# delete() の戻り値を変数で受け取り `.get()` の結果が偽なら
# `exceptions.MpdSystemError` (実MPDのACK_ERROR_SYSTEM相当) を送出する。

import ast

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

NEW = (
    "    _check_playlist_name(name)\n"
    "    uri = context.lookup_playlist_uri_from_name(name)\n"
    "    if not uri:\n"
    '        raise exceptions.MpdNoExistError("No such playlist")\n'
    "    if not context.core.playlists.delete(uri).get():\n"
    '        raise exceptions.MpdSystemError("Failed to delete playlist")\n'
)

if NEW in s:
    print("rm() delete()-False guard already patched, skip")
else:
    OLD = (
        "    _check_playlist_name(name)\n"
        "    uri = context.lookup_playlist_uri_from_name(name)\n"
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such playlist")\n'
        "    context.core.playlists.delete(uri).get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stored_playlists.py: rm()のplaylists.delete()戻り値(bool)を"
        "チェックし、失敗時にMpdSystemErrorを送出するよう修正"
    )
