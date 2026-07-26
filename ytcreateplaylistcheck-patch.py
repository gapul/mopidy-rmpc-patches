# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.create() が
# self.backend.api.create_playlist() の戻り値を「truthy かどうか」でしか判定しておらず
# 常に成功扱いしてしまう不具合。ytaddresultcheck-patch.py (save()のadd_playlist_items()
# 戻り値未検証バグ) のverifiedコメントで「create_playlist()の同種の曖昧戻り値問題も
# 併せて調査したが今回のBACKLOG追加は影響範囲がより明確なadd側のみ、create側は
# 別途調査の余地あり」と自走エージェント自身が残していたフォローアップを、TODO/既知の
# 残課題を全項目消化済みの自走エージェントが実際に着手・新規発見・追加した項目。
#
# ytmusicapi/mixins/playlists.py の create_playlist() は末尾で
#     return response["playlistId"] if "playlistId" in response else response
# としており、成功時は playlistId (str) を返すが、失敗時 (タイトルに無効文字、
# サーバーエラー、クォータ超過等で応答に playlistId キーが無い場合) は例外を投げず
# 生レスポンスの dict をそのまま返す。呼び出し側の create() は
#     bId = self.backend.api.create_playlist(name, "")
#     ...
#     if bId:
#         uri = f"ytmusic:playlist:{bId}"
#         return Playlist(uri=uri, name=name, tracks=[], last_modified=None)
# としており、非空 dict も Python の truthy 判定を通過してしまうため、失敗時の
# 生レスポンス dict がそのまま bId として使われ `uri = f"ytmusic:playlist:{bId}"`
# で dict の repr (`ytmusic:playlist:{'error': ...}` 等) を含む壊れた URI を持つ
# 「作成成功したように見える」Playlist オブジェクトが返ってしまう。MPD の
# save/searchaddpl (mopidy.core.playlists.create() 経由) はこれを「作成成功」として
# 扱い後続の save() 処理へ進むため、実際にはYouTube Music側でプレイリストが
# 作られていないにもかかわらず OK が返り、後続のURI解決やlookupが壊れたbIdで
# 静かに失敗し続ける「サイレントなデータ欠落」になる (ytaddresultcheck-patch.pyが
# add_playlist_items()に対して修正したのと同型のバグ)。
#
# 修正: create_playlist() の成功判定は「文字列 (playlistId) が返ったか」であり、
# 失敗時は dict が返るという ytmusicapi 自身の型で判定する (truthy dict も弾かれる)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "YTMusic playlist creation did not succeed"
if MARKER in s:
    print("create_playlist() success-check already patched, skip")
else:
    OLD = '''    def create(self, name):
        logger.debug('YTMusic creating playlist "%s"', name)
        try:
            bId = self.backend.api.create_playlist(name, "")
        except Exception:
            logger.exception("YTMusic playlist creation failed")
            bId = None
        if bId:
            uri = f"ytmusic:playlist:{bId}"
            logger.debug('YTMusic created playlist "%s"', uri)
            return Playlist(
                uri=uri,
                name=name,
                tracks=[],
                last_modified=None,
            )
        return None'''

    NEW = '''    def create(self, name):
        logger.debug('YTMusic creating playlist "%s"', name)
        try:
            bId = self.backend.api.create_playlist(name, "")
        except Exception:
            logger.exception("YTMusic playlist creation failed")
            bId = None
        # ytmusicapi の create_playlist() は成功時のみ playlistId (str) を返し、
        # 失敗時は例外を投げず生レスポンスの dict をそのまま返す。非空 dict も
        # truthy になるため isinstance で明示的に str のみ成功として扱う。
        if isinstance(bId, str) and bId:
            uri = f"ytmusic:playlist:{bId}"
            logger.debug('YTMusic created playlist "%s"', uri)
            return Playlist(
                uri=uri,
                name=name,
                tracks=[],
                last_modified=None,
            )
        if bId is not None:
            logger.error(
                'YTMusic playlist creation did not succeed for "%s": %s',
                name,
                bId,
            )
        return None'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of create() anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: create_playlist() の失敗 (playlistIdを含まない生"
        "レスポンスdict) をtruthy判定で成功扱いしていた不具合を修正"
    )
