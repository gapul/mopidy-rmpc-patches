# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() (ytaddresultcheck-patch.py/
# ytcreateplaylistcheck-patch.py/ytremoveresultcheck-patch.py 適用後の版) が、リネーム時の
# self.backend.api.edit_playlist(bId, title=...) と、_reorder_playlist() 内の並べ替え時の
# self.backend.api.edit_playlist(bId, moveItem=...) の戻り値をどちらも一切確認せず常に
# 成功扱いする不具合。TODO/既知の残課題を全項目消化済みの自走エージェントが、
# ytremoveresultcheck-patch.py の verified コメントで
# 「add_playlist_items()/remove_playlist_items() は対応済みだが同じ save() 内で使われる
# edit_playlist() はまだ未検証」であることに気付き、ytmusicapi 本体
# (ytmusicapi/mixins/playlists.py の edit_playlist()) を実際に読んで確認・新規発見した項目。
#
# ytmusicapi の edit_playlist() は末尾で
#     return response["status"] if "status" in response else response
# としており、add_playlist_items()/remove_playlist_items() と全く同じ設計: 成功時のみ
# "status" 文字列 (例: "STATUS_SUCCEEDED") を返し、アプリケーションレベルの失敗
# (権限不足・サーバーエラー等) でも例外を投げず "status" キーの無い生レスポンス dict を
# そのまま返す。
#
# 呼び出し側の save() は2箇所でこれを無視している:
# (1) リネーム: 戻り値を一切見ない。edit_playlist() が失敗しても save() は無条件に
#     playlist (新タイトルの Playlist オブジェクト) を返すため、mopidy 側は
#     「リネーム成功」として扱うが実際には YouTube Music 側のタイトルが変わっておらず、
#     次回 as_list() で取得するタイトルと食い違うサイレントな不整合になる。
# (2) 並べ替え (_reorder_playlist): 戻り値を見ずに例外が出なければ即座に
#         working.remove(a); working.insert(working.index(b), a)
#     と「moveItem 成功」の前提で内部追跡状態 working を更新してしまう。実際には
#     moveItem が失敗しているのに working を進めると、後続(ループはi降順で処理)の
#     moveItem 呼び出しが誤った現在順序を前提に setVideoId ペアを算出することになり、
#     1回の失敗が以後の全ての moveItem 呼び出しへ連鎖的に伝播し、プレイリストの
#     曲順が意図しない形で壊れ続ける可能性がある (add/remove 側と同種の
#     「戻り値未検証によるサイレントなデータ不整合」だが、こちらは内部状態の
#     破損が後続処理に連鎖する点がより深刻)。
#
# 修正: ytmusicapi 自身の戻り値仕様 (成功時は "SUCCEEDED" を含む str、失敗時は dict) を
# 呼び出し側でも確認する。(1) は他の失敗系統と同じくログのみ残し例外は投げない
# (save() 全体の「ベストエフォートで進める」既存方針を踏襲)。(2) は失敗を検知したら
# 例外時と同じく直ちに return し、working の更新も後続の moveItem 呼び出しも行わない
# (誤った前提での連鎖破壊を防ぐ)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "edit_playlist (rename) for playlist"
if MARKER in s:
    print("edit_playlist() success-check already patched, skip")
else:
    OLD_RENAME = '''        if pls["title"] != playlist.name:
            logger.debug('Renaming playlist to "%s"', playlist.name)
            try:
                self.backend.api.edit_playlist(bId, title=playlist.name)
            except Exception:
                logger.exception("YTMusic failed renaming playlist")'''

    NEW_RENAME = '''        if pls["title"] != playlist.name:
            logger.debug('Renaming playlist to "%s"', playlist.name)
            try:
                result = self.backend.api.edit_playlist(bId, title=playlist.name)
            except Exception:
                logger.exception("YTMusic failed renaming playlist")
            else:
                # ytmusicapi の edit_playlist() は add/remove_playlist_items() と同じ
                # 設計で、成功時のみ "SUCCEEDED" を含む str を返し、失敗時は例外を
                # 投げず "status" キーの無い生レスポンス dict をそのまま返す。
                if not (isinstance(result, str) and "SUCCEEDED" in result):
                    logger.error(
                        'YTMusic edit_playlist (rename) for playlist "%s" did not '
                        "succeed; playlist title may not have been changed: %s",
                        bId,
                        result,
                    )'''

    assert s.count(OLD_RENAME) == 1, f"expected 1 occurrence of rename anchor (got {s.count(OLD_RENAME)})"
    s = s.replace(OLD_RENAME, NEW_RENAME, 1)

    OLD_REORDER = '''            try:
                self.backend.api.edit_playlist(
                    bId, moveItem=(setVideoIds[i], setVideoIds[i + 1])
                )
            except Exception:
                logger.exception("YTMusic failed reordering playlist item")
                return
            working.remove(a)
            working.insert(working.index(b), a)'''

    NEW_REORDER = '''            try:
                result = self.backend.api.edit_playlist(
                    bId, moveItem=(setVideoIds[i], setVideoIds[i + 1])
                )
            except Exception:
                logger.exception("YTMusic failed reordering playlist item")
                return
            if not (isinstance(result, str) and "SUCCEEDED" in result):
                # working (内部で追跡している「現在の並び」) を進めてしまうと、
                # 以後のループが誤った前提で setVideoId ペアを算出し失敗が連鎖する
                # ため、例外時と同じく直ちに諦める。
                logger.error(
                    'YTMusic edit_playlist (moveItem) for playlist "%s" did not '
                    "succeed; playlist order may be partially incorrect: %s",
                    bId,
                    result,
                )
                return
            working.remove(a)
            working.insert(working.index(b), a)'''

    assert s.count(OLD_REORDER) == 1, f"expected 1 occurrence of reorder anchor (got {s.count(OLD_REORDER)})"
    s = s.replace(OLD_REORDER, NEW_REORDER, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: edit_playlist() の失敗 ('status'キーの無い生レスポンス) を"
        "検知せず、リネームと moveItem 並べ替えの両方で常に成功扱いしていた不具合を修正"
    )
