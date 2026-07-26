# mopidy_mpd/protocol/stored_playlists.py の `rename {NAME} {NEW_NAME}` が、
# 新規コピー(create+save)成功後の後始末である旧プレイリスト削除
# `context.core.playlists.delete(old_playlist.uri).get()` の戻り値 (bool、
# 失敗時 False) を一切確認せず、削除が実際に失敗しても常に `OK` を返してしまう
# 不具合。mpdplaylistrmguard-patch.py (`rm` の同型の戻り値未チェック) の
# verified 内に「rename() 末尾の同一パターンも残っているが、当時は
# create()/save() 側から先に失敗してしまい delete() 単体の失敗を安全に単離して
# 実機検証できなかったため対象外のままにした」というメモを残しており、TODO/
# 既知の残課題を全項目消化済みの自走エージェントがそのメモを引き継ぎ新規に
# 追加した項目。
#
# mopidy.core.playlists.delete() の docstring 通り、削除に失敗した場合は
# `False` を返す契約。既定の保存先スキームである mopidy.m3u.playlists の
# delete() は `Path.unlink()` が OSError (Permission denied 等) を投げると
# 同様に `False` を返す設計であり、実際に踏みうる。
#
# 実害: rename の複製(create+save)自体はディスクへの新規書き込みとして成功
# しているため、削除の失敗だけを単離しても create/save には影響しない
# (rmguard 項目のメモと異なり、m3u の delete() は unlink() 対象がリネーム後の
# 「旧ファイル」1つだけなので、新ファイルとは独立に旧ファイルだけを削除不能な
# 状態(macOS の `chflags uchg`、ユーザ immutable フラグ)にすることで単離
# 再現できる。ディレクトリ自体の書き込み権限は保ったままなので新ファイルの
# create/save は成功する)。この状態で `rename` を実行すると、新プレイリスト
# (NEW_NAME) が作られた「上に」旧プレイリスト (NAME) も削除されずそのまま
# 残り、`listplaylists` には両方が並んでしまうにも関わらず MPD クライアントに
# は `OK` しか返らず、rmpc 等はリネームが完全に成功したと誤認する。
#
# 修正: mpdplaylistrmguard-patch.py の rm() と同じ流儀で、delete() の戻り値を
# 変数で受け取り偽なら `exceptions.MpdSystemError` (実MPDの
# ACK_ERROR_SYSTEM相当) を送出する。

import ast

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

NEW = (
    "    if saved_playlist is None:\n"
    "        raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
    "    if not context.core.playlists.delete(old_playlist.uri).get():\n"
    '        raise exceptions.MpdSystemError("Failed to delete playlist")\n'
)

if NEW in s:
    print("rename() delete()-False guard already patched, skip")
else:
    OLD = (
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(uri_scheme)\n"
        "    context.core.playlists.delete(old_playlist.uri).get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stored_playlists.py: rename()末尾のplaylists.delete()戻り値"
        "(bool)をチェックし、失敗時にMpdSystemErrorを送出するよう修正"
    )
