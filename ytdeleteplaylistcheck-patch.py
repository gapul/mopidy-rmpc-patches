# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.delete() が
# self.backend.api.delete_playlist() の戻り値を一切確認せず、例外さえ出なければ
# 常に成功 (True) を返してしまう不具合。ytcreateplaylistcheck-patch.py/
# ytremoveresultcheck-patch.py/ytplaylisteditcheck-patch.py で save()/create() 側の
# 「戻り値未検証」を潰した自走エージェントが、同じ playlist.py 内に残る
# delete_playlist() だけが未対応であることに気付き、ytmusicapi 本体
# (ytmusicapi/mixins/playlists.py の delete_playlist()) を実際に読んで確認・
# 新規発見・追加した項目。
#
# ytmusicapi の delete_playlist() は末尾で
#     return response["status"] if "status" in response else response
# としており、create_playlist()/remove_playlist_items() と同型の設計: 成功時のみ
# "status" 文字列 (例: "STATUS_SUCCEEDED") を返し、アプリケーションレベルの失敗
# (存在しない/既に削除済みのplaylistId、権限エラー、サーバーエラー等) でも例外を
# 投げず "status" キーの無い生レスポンス dict をそのまま返す。呼び出し側の
# delete() は
#     self.backend.api.delete_playlist(bId)
#     return True
# と戻り値を完全に無視しており、例外が出ない限り常に True を返す。
#
# 実害: mopidy core の Playlists.delete() (mopidy/core/playlists.py) は
# backend.playlists.delete(uri).get() が真なら "playlist_deleted" イベントを
# 発火して True を返し、mopidy_mpd の rm コマンド
# (mopidy_mpd/protocol/stored_playlists.py) は
#     if not context.core.playlists.delete(uri).get():
#         raise exceptions.MpdSystemError("Failed to delete playlist")
# としているため、実際には YouTube Music 側でプレイリストが削除されていない
# (dict が返っている) 場合でも rm は OK を返してしまう。rmpc 等のクライアントは
# これを見て自分のプレイリスト一覧からも消してしまうため、次回同期時に
# 「削除したはずのプレイリストが listplaylists に復活する」というユーザーから
# 見て不可解なサイレントなデータ不整合になる (create/remove/edit 側の
# 一連の戻り値未検証バグと同型)。
#
# 修正: delete_playlist() の成功判定を ytmusicapi 自身の型 ("SUCCEEDED" を含む
# str が返ったか) で行う。失敗時は False を返す (delete() の既存の例外系と同じ
# 戻り値仕様を維持)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "YTMusic delete_playlist did not succeed"
if MARKER in s:
    print("delete_playlist() success-check already patched, skip")
else:
    OLD = '''    def delete(self, uri):
        logger.debug('YTMusic deleting playlist "%s"', uri)
        bId = parse_uri(uri)
        try:
            self.backend.api.delete_playlist(bId)
            return True
        except Exception:
            logger.exception("YTMusic failed to delete playlist")
            return False'''

    NEW = '''    def delete(self, uri):
        logger.debug('YTMusic deleting playlist "%s"', uri)
        bId = parse_uri(uri)
        try:
            result = self.backend.api.delete_playlist(bId)
        except Exception:
            logger.exception("YTMusic failed to delete playlist")
            return False
        # ytmusicapi の delete_playlist() は create_playlist()/remove_playlist_items()
        # と同型: 成功時のみ "SUCCEEDED" を含む str を返し、失敗時は例外を投げず
        # "status" キーの無い生レスポンス dict をそのまま返す。
        if isinstance(result, str) and "SUCCEEDED" in result:
            return True
        logger.error(
            'YTMusic delete_playlist did not succeed for "%s": %s',
            bId,
            result,
        )
        return False'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of delete() anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: delete_playlist() の失敗 ('status'キーの無い生"
        "レスポンス) を確認せず常に成功(True)扱いしていた不具合を修正"
    )
