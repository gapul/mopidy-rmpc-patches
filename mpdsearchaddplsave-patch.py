# mopidy_mpd/protocol/music_db.py の `searchaddpl {NAME} {TYPE} {WHAT} [...]`
# が、検索結果を追加したプレイリストを保存する `context.core.playlists.save(playlist)`
# の戻り値 (pykka の Future) を一度も `.get()` せず投げっぱなしのまま関数を抜けている
# 不具合。TODO 全項目消化済みのため自走エージェントが、直近の一連の TOCTOU/`.get()`
# 抜け修正 (delete/toggleoutput/moveid/swapid 等) と同種のパターンが他にも残っていない
# か `context.core.*` の全呼び出しを ast で洗い出す形で調査し新規発見・追加した項目。
#
# 同じファイル内の `save` (stored_playlists.py) を含む他の全ての
# `context.core.playlists.save(...)` 呼び出し (playlistadd/playlistclear/
# playlistdelete/rename 等、計10箇所) はどれも `.get()` した上で戻り値が `None`
# (保存失敗、mopidy.core.playlists.save() のdocstring通り URI スキームに対応する
# バックエンドが無い/書き込みに失敗した場合の挙動) なら `exceptions.
# MpdFailedToSavePlaylist` を送出しているのに対し、`searchaddpl` だけが唯一
# `.get()` すらせず、保存の成否を一切確認しないまま `OK` を返す非対称な実装
# だったと判明。実害: (1) 保存が実際に失敗しても (yt-dlp/ytmusic 等の読み取り専用
# バックエンドや書き込み権限不足時など) クライアントには `OK` が返り、
# 検索結果が実は1件も保存されていないことに気づけない (mpdloadpos-patch.py の
# 検証時に既に確認済みの通り、このテスト環境の ytmusic 実アカウントは書き込み
# 権限不足で create_playlist が実際に失敗する既知の挙動があり、この経路でも
# 同様に踏み得る)。(2) mopidy_mpd はハンドラが返った時点でクライアントへ `OK`
# を返すため、実際に core actor 側で保存が反映されるより前に `OK` が届きうる
# (mpddeleterace-patch.py 等で既に修正した「.get() 未呼び出しによるOK応答と
# 実状態反映の非同期」と同じバグクラス)。
#
# 修正: `stored_playlists.py` の `playlistclear`/`playlistdelete` 等と同じ流儀で
# `.get()` して結果を変数に受け、`None` (保存失敗) なら
# `exceptions.MpdFailedToSavePlaylist(urllib.parse.urlparse(playlist.uri).scheme)`
# を送出する。music_db.py には urllib が未importのため、stored_playlists.py と
# 同じ `import urllib` を追加する。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

NEW_SAVE = (
    "    saved_playlist = context.core.playlists.save(playlist).get()\n"
    "    if saved_playlist is None:\n"
    "        raise exceptions.MpdFailedToSavePlaylist(\n"
    "            urllib.parse.urlparse(playlist.uri).scheme\n"
    "        )\n"
)

if NEW_SAVE in s:
    print("searchaddpl() save() race already patched, skip")
else:
    OLD_SAVE = "    context.core.playlists.save(playlist)\n"
    assert s.count(OLD_SAVE) == 1, f"OLD_SAVE count={s.count(OLD_SAVE)}"
    s = s.replace(OLD_SAVE, NEW_SAVE, 1)

    OLD_IMPORT = "import functools\n"
    NEW_IMPORT = "import functools\nimport urllib\n"
    assert s.count(OLD_IMPORT) == 1, f"OLD_IMPORT count={s.count(OLD_IMPORT)}"
    assert "import urllib\n" not in s, "urllib already imported?"
    s = s.replace(OLD_IMPORT, NEW_IMPORT, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: searchaddpl()内のplaylists.save()に.get()を追加し"
        "OK応答前に保存を同期化、戻り値Noneなら他のplaylistadd系コマンドと同様に"
        "MpdFailedToSavePlaylistを送出"
    )
