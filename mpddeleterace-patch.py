# mopidy_mpd/protocol/current_playlist.py の `delete [{POS}|{START:END}]`
# (単曲・範囲指定どちらも) が、`context.core.tracklist.remove(...)` の戻り値
# (pykka の Future) を一度も `.get()` せず投げっぱなしのまま関数を抜けている
# 不具合。
#
# 同じファイル内の `deleteid()` は隣で `context.core.tracklist.remove(...).get()`
# と正しく同期しているのに対し、`delete()` のループ内だけ `.get()` が抜けており
# 非対称。mopidy_mpd はハンドラが返った時点でクライアントへ `OK` を返すため、
# 実際に core actor 側でキューからの除去が反映されるより前に `OK` が届きうる
# (pykka actor は投げたメッセージを順序通り処理するため取りこぼしは無いが、
# 直後に同じ接続/別接続から送る `playlistinfo`/`status` が古いキュー内容を
# 返す競合が起こりうる)。rmpc はキューペインでの単曲削除(`d`キー相当)・
# visual-select複数曲削除のどちらも `delete {POS}` / `delete {START:END}`
# (rmpc-mpd/src/mpd_client.rs send_delete_from_queue) を送るため、最も日常的な
# 削除操作がこの経路を通る。
#
# 修正: ループ内の `remove()` にも `.get()` を追加し、同期化する
# (mopidy.core.tracklist.remove() は該当tlidが見つからなくても例外を投げず
# 空リストを返すだけの実装のため、deleteid()と違い追加の例外処理は不要)。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

NEW = (
    "    tl_tracks = context.core.tracklist.slice(start, end).get()\n"
    '    if not tl_tracks:\n'
    '        raise exceptions.MpdArgError("Bad song index", command="delete")\n'
    "    for (tlid, _) in tl_tracks:\n"
    '        context.core.tracklist.remove({"tlid": [tlid]}).get()\n'
)

if NEW in s:
    print("delete() race already patched, skip")
else:
    OLD = (
        "    tl_tracks = context.core.tracklist.slice(start, end).get()\n"
        '    if not tl_tracks:\n'
        '        raise exceptions.MpdArgError("Bad song index", command="delete")\n'
        "    for (tlid, _) in tl_tracks:\n"
        '        context.core.tracklist.remove({"tlid": [tlid]})\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: delete()内のtracklist.remove()に"
        ".get()を追加しOK応答前に除去を同期化 (deleteid()と対称に修正)"
    )
