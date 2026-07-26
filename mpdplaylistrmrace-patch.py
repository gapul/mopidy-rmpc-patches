# mpdplaylisteditrace-patch.py が導入した _stored_playlist_edit_lock は
# playlistadd/playlistclear/playlistdelete/playlistmove/rename/save の
# 「_get_playlist()で読む→加工→save()(またはcreate()+delete())で書き戻す」
# read-modify-writeを直列化したが、同じストアドプレイリスト編集系の兄弟コマンド
# である rm (プレイリスト削除) だけはこのロックを一切取らずに
# context.core.playlists.delete() を呼んでいる。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントがmpdplaylisteditrace-patch.py導入後の
# stored_playlists.pyを再監査し新規発見した項目 (ロック対象コマンド一覧からの
# rm単体の抜け漏れ)。
#
# 実害: 接続Aが `rename "P" "Q"` を送ると (_stored_playlist_edit_lock 保持中)
# 「Pの現在の内容を読む → Q を create()+save() で複製 → 最後に P を
# context.core.playlists.delete() で削除」という3段の複合操作を行う。この
# 「最後にPを削除」という自分自身のdelete()呼び出しの直前に、ロックを取らない
# 接続Bの `rm "P"` が割り込んで先にPを削除してしまうと、A自身のdelete()は
# 「既に存在しないPを削除しようとして失敗」となり
# `context.core.playlists.delete(old_playlist.uri).get()` が False を返す。
# renameハンドラはこれを額面通り受け取り `ACK ... Failed to delete playlist`
# を接続Aへ返してしまうが、実際にはQの作成(Pの曲を複製)は既に成功しており
# Pも(Bのrmにより)確かに削除済みという、rename としては実質成功している状態。
# クライアントAは「rename失敗」という誤ったACKを受け取り、rmpc等はQが
# 実際に作成されたことに気付けない(表示更新をスキップしたり、失敗と誤解して
# 同じrenameを再試行し今度はPが既に存在せず別のACKで混乱する、等)。
# save(mode=append/replace)がロック内で`_get_playlist()`により存在確認した
# 直後に、ロックを取らない`rm`がその同じプレイリストを削除してから
# saveがcontext.core.playlists.save()を呼ぶ、という順序も同様に起こりうる
# (mopidy_ytmusicのYTMusicPlaylistsProvider.save()はbId解決後にget_playlist()
# するため、削除済みplaylistIdに対しては例外捕捉でNoneを返しMpdFailedToSavePlaylist
# になるだけで実害は無いが、意図せぬACKエラーである点は同種の問題)。
#
# 修正: mpdplaylisteditrace-patch.pyが導入した既存の_stored_playlist_edit_lockを
# rm()にもそのまま流用し、「uri解決→delete()」区間を他の6コマンドと同じ
# with ブロックで直列化する。これによりrmと他の編集系コマンドが同じ
# ストアドプレイリストに対し互いに完全に排他実行され、上記の「自分自身の
# delete()が横取りされて誤ったACKになる」レースが解消される。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

MARKER = "with _stored_playlist_edit_lock:\n        uri = context.lookup_playlist_uri_from_name(name)"
if MARKER in s:
    print("mpdplaylistrmrace already applied to stored_playlists.py, skip")
else:
    assert "_stored_playlist_edit_lock" in s, (
        "mpdplaylisteditrace-patch.py must run before mpdplaylistrmrace-patch.py "
        "(missing _stored_playlist_edit_lock)"
    )

    old_rm = (
        "    _check_playlist_name(name)\n"
        "    uri = context.lookup_playlist_uri_from_name(name)\n"
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such playlist")\n'
        "    if not context.core.playlists.delete(uri).get():\n"
        '        raise exceptions.MpdSystemError("Failed to delete playlist")\n'
    )
    assert s.count(old_rm) == 1, f"old_rm count={s.count(old_rm)}"
    new_rm = (
        "    _check_playlist_name(name)\n"
        "    with _stored_playlist_edit_lock:\n"
        "        uri = context.lookup_playlist_uri_from_name(name)\n"
        "        if not uri:\n"
        '            raise exceptions.MpdNoExistError("No such playlist")\n'
        "        if not context.core.playlists.delete(uri).get():\n"
        '            raise exceptions.MpdSystemError("Failed to delete playlist")\n'
    )
    s = s.replace(old_rm, new_rm, 1)

    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: rm()もplaylistadd/playlistclear/"
        "playlistdelete/playlistmove/rename/saveと同じ_stored_playlist_edit_lockで"
        "直列化し、rename等の複合操作(create+save+delete)の最後のdelete()を"
        "無関係なrmが横取りして誤ったACK(Failed to delete playlist)を返す"
        "レースを解消"
    )
