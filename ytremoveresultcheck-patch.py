# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() (ytaddresultcheck-patch.py
# 適用後の版) が、曲削除 self.backend.api.remove_playlist_items() の戻り値を一切確認せず
# 常に成功扱いする不具合。TODO/既知の残課題を全項目消化済みの自走エージェントが
# ytaddresultcheck-patch.py の verified コメントで add 側のみを対象にしていたことを踏まえ、
# 直後の remove_playlist_items() 呼び出しも同種の未検証のままであることに気付き、
# ytmusicapi 本体 (ytmusicapi/mixins/playlists.py の remove_playlist_items()) を実際に
# 読んで確認・新規発見した項目。
#
# ytmusicapi の remove_playlist_items() は末尾で
#     return response["status"] if "status" in response else response
# としており、成功時は "status" 文字列 (例: "STATUS_SUCCEEDED") を返す一方、
# アプリケーションレベルの失敗 (setVideoId が古い等の並行編集競合、その他サーバー
# エラー) でも例外を投げず、"status" キーの無い生レスポンス dict をそのまま返す
# (add_playlist_items() と対をなす同一設計。dict/str のどちらが返るかで成功/失敗を
# 判別する必要がある点が add 側の「"status" キーの有無」だけの判定と異なる)。
# 呼び出し側の save() はこの戻り値を一切見ておらず、
#     self.backend.api.remove_playlist_items(bId, videos)
#     for t in videos:
#         setVideoIdByVideoId.pop(t["videoId"], None)
# と無条件に「削除成功した」前提で setVideoIdByVideoId から該当エントリを消してしまう。
# 実際にはYouTube Music側で曲が削除されていない場合、次回の listplaylistinfo で
# 消えたはずの曲が残っている「サイレントなデータ不整合」になる
# (playlistdelete/playlistmove/rename 経由の save() で発生しうる)。
#
# 修正: ytmusicapi 自身の戻り値仕様 (成功時は "SUCCEEDED" を含む str、失敗時は
# dict) を呼び出し側でも確認し、成功時のみ setVideoIdByVideoId を更新する。
# 失敗時は (他の失敗系統と同じく) ログのみ残し例外は投げない (save() 全体の
# 「ベストエフォートで進める」既存方針を踏襲)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "remove_playlist_items for playlist"
if MARKER in s:
    print("remove_playlist_items() success-check already patched, skip")
else:
    OLD = '''            try:
                self.backend.api.remove_playlist_items(bId, videos)
                for t in videos:
                    setVideoIdByVideoId.pop(t["videoId"], None)
            except Exception:
                logger.exception("YTMusic failed removing items from playlist")'''

    NEW = '''            try:
                result = self.backend.api.remove_playlist_items(bId, videos)
            except Exception:
                logger.exception("YTMusic failed removing items from playlist")
            else:
                # ytmusicapi の remove_playlist_items() は成功時のみ "status" 文字列
                # ("STATUS_SUCCEEDED" 等) を返し、アプリレベルの失敗 (並行編集による
                # setVideoId失効やサーバーエラー) では例外を投げず "status" キーの
                # 無い生レスポンス dict をそのまま返す (add_playlist_items() と対の
                # 設計。ただし成功/失敗の型そのものが str/dict で異なる点に注意)。
                if isinstance(result, str) and "SUCCEEDED" in result:
                    for t in videos:
                        setVideoIdByVideoId.pop(t["videoId"], None)
                else:
                    logger.error(
                        'YTMusic remove_playlist_items for playlist "%s" did not '
                        "succeed; items may not have been removed: %s",
                        bId,
                        result,
                    )'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of remove_playlist_items anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: remove_playlist_items() の失敗 ('status'キーの無い"
        "生レスポンス) を検知せず常に成功扱いしていた不具合を修正"
    )
