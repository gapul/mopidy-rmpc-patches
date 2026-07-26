# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() (ytplaylistdup-patch.py
# 適用後の版) が、曲追加 self.backend.api.add_playlist_items() の戻り値を一切確認せず
# 常に成功扱いする不具合。TODO/既知の残課題を全項目消化済みの自走エージェントが
# ytmusicapi 本体 (ytmusicapi/mixins/playlists.py の add_playlist_items()) を実際に
# 読んで新規発見・追加した項目。
#
# ytmusicapi の add_playlist_items() は末尾で
#     if "status" in response and "SUCCEEDED" in response["status"]:
#         return {"status": ..., "playlistEditResults": [...]}
#     else:
#         return response
# としており、失敗時 (duplicates=False という既定値のまま、追加先プレイリストに
# 既に同じ videoId が存在する「重複」とみなされた場合、その他のサーバーエラー等)
# も例外を投げず生レスポンスをそのまま返す。呼び出し側の save() はこの結果を
# `result.get("playlistEditResults", [])` (失敗時は通常キーが無く空リストになるだけ)
# としか見ておらず、成功したかどうかの判定が一切無いまま
#     currentOrder += addList
# を無条件実行してしまう。これにより実際には1曲も追加されていないのに、以後の
# 並べ替え判断材料 (currentOrder/setVideoIdByVideoId) が「追加成功した」前提で
# 汚染される。playlistadd/save 経由でYouTube Music側は無変更のまま MPD クライアント
# へは OK が返る「サイレントなデータ欠落」になる (例: 既にプレイリストに入っている
# 曲をもう1コピー追加しようとするケース、rmpc でよくある操作)。
#
# 修正: ytmusicapi 自身が成功判定に使っているのと同じ条件 ("status" に "SUCCEEDED" を
# 含むか) を呼び出し側でも確認し、成功時のみ setVideoIdByVideoId/currentOrder を
# 更新する。失敗時は (他の失敗系統と同じく) ログのみ残し例外は投げない
# (save() 全体の「ベストエフォートで進める」既存方針を踏襲)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "add_playlist_items for playlist"
if MARKER in s:
    print("add_playlist_items() success-check already patched, skip")
else:
    OLD = '''        if addCounts:
            addList = list(addCounts.elements())
            logger.debug('YTMusic adding items "%s" to playlist', addList)
            try:
                result = self.backend.api.add_playlist_items(bId, addList)
                for videoId, added in zip(addList, result.get("playlistEditResults", [])):
                    if added and added.get("setVideoId"):
                        setVideoIdByVideoId[videoId] = added["setVideoId"]
                currentOrder += addList
            except Exception:
                logger.exception("YTMusic failed adding items to playlist")'''

    NEW = '''        if addCounts:
            addList = list(addCounts.elements())
            logger.debug('YTMusic adding items "%s" to playlist', addList)
            try:
                result = self.backend.api.add_playlist_items(bId, addList)
            except Exception:
                logger.exception("YTMusic failed adding items to playlist")
            else:
                # ytmusicapi の add_playlist_items() は失敗時 (既定 duplicates=False
                # のまま追加先に既に同じ videoId がある「重複」とみなされた場合や
                # その他のサーバーエラー) も例外を投げず、"status" に "SUCCEEDED" を
                # 含まない生レスポンスをそのまま返す (成功判定はytmusicapi自身の
                # add_playlist_items()内の条件と同一のものをここでも使う)。
                if isinstance(result, dict) and "SUCCEEDED" in str(result.get("status", "")):
                    for videoId, added in zip(addList, result.get("playlistEditResults", [])):
                        if added and added.get("setVideoId"):
                            setVideoIdByVideoId[videoId] = added["setVideoId"]
                    currentOrder += addList
                else:
                    logger.error(
                        'YTMusic add_playlist_items for playlist "%s" did not '
                        "succeed (likely rejected as duplicate or a server "
                        "error); items may not have been added: %s",
                        bId,
                        result,
                    )'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of add_playlist_items anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: add_playlist_items() の失敗 (SUCCEEDEDを含まない生"
        "レスポンス) を検知せず常に成功扱いしていた不具合を修正"
    )
