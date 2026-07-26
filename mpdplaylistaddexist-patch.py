# `playlistadd {NAME} {URI} [POSITION]` (stored_playlists.py) が、URI がバック
# エンドで実在の曲へ解決できない場合でも例外を出さず黙って `OK` を返してしまう
# 不具合。TODO 全項目消化済みのため自走エージェントがgeneral-purposeサブ
# エージェントに新規発見を委任し着手。
#
# mpdplaylistaddpos-patch.py 適用後の実装 (POSITION 対応版) は
# `context.core.library.lookup(uris=[track_uri]).get()` の結果を
# `new_tracks` へ展開するだけで、その中身が空 (=URI が存在しない/削除済み)
# であるかを一切チェックしない。mopidy.core.library.LibraryController.lookup()
# は問い合わせた URI をキーとして事前に空リストで初期化した dict を返すため、
# 解決失敗時も例外は飛ばず `new_tracks == []` になるだけで後続処理がそのまま
# 進んでしまう。
#
# 実害:
# (1) 既存プレイリストへの追加: `combined_tracks == old_tracks` (無変化) の
#     まま `core.playlists.save()` が成功し `OK` が返る。rmpc は「追加成功」
#     と表示するが実際には何も追加されていない。
# (2) 新規プレイリスト作成: `old_playlist is None` の場合
#     `_create_playlist(context, name, combined_tracks=[])` が呼ばれ、
#     0曲の空プレイリストが実際に作成された上で `OK` が返る (`listplaylists`
#     にゴミが残り続ける)。
#
# 仕様確認: 実MPD (MusicPlayerDaemon/MPD, gh api で実ソース確認) の
# handle_playlistadd (src/command/PlaylistCommands.cxx) は
# `SongLoader::LoadSong()` (src/SongLoader.cxx) 経由でURIを解決しており、
# データベースに存在しない場合は `LoadFromDatabase()` が
# `PlaylistError(PlaylistResult::NO_SUCH_SONG, ...)` を送出、ファイルが
# 存在しない場合も `LoadFile()` が `PlaylistError::NoSuchSong()` を送出する
# (= 常に "No such song" でエラーとして拒否し、黙って無視/空プレイリスト
# 作成にはならない)。同じ mopidy_mpd コードベース内でも
# `music_db.py:readcomments()` や `current_playlist.py` の addid 等
# 多数のコマンドが「lookup結果が空なら `MpdNoExistError("No such song")`」
# という統一方針を取っており (mpdreadcomments-patch.py 等)、`playlistadd`
# だけがこの検証を欠いていた。
#
# 修正: `new_tracks` 展開直後、combined_tracks 組み立て前に空チェックを追加し
# `MpdNoExistError("No such song")` を送出する (既存プレイリストの誤保存・
# 空プレイリストの誤作成の両方を防止。POSITION の範囲チェックより後に置いても
# 副作用が無い箇所なので順序は変更しない)。

sp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(sp).read()

MARKER = "    if not new_tracks:\n" '        raise exceptions.MpdNoExistError("No such song")\n'
if MARKER in s:
    print("playlistadd already patched for missing-track guard, skip")
else:
    anchor = (
        "    lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "    new_tracks = [\n"
        "        track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "    ]\n"
        "\n"
        "    if position is None:\n"
        "        combined_tracks = old_tracks + new_tracks\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    new_block = (
        "    lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "    new_tracks = [\n"
        "        track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "    ]\n"
        + MARKER
        + "\n"
        "    if position is None:\n"
        "        combined_tracks = old_tracks + new_tracks\n"
    )
    assert new_block != anchor
    s = s.replace(anchor, new_block, 1)
    open(sp, "w").write(s)
    print(
        "patched stored_playlists.py: playlistadd が未解決URIで"
        ' ACK "No such song" を返すよう修正'
    )
