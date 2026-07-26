# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() には2つの問題がある。
#
# (1) 【重大・実データで実害あり】newIds の計算が
#     `set([parse_uri(p.uri)[0] for p in playlist.tracks])` になっており、
#     `parse_uri(uri)` は "ytmusic:track:{videoId}" (3 コロン区切り) から
#     videoId 文字列そのものを返す (library.py の Ref.track(uri=f"ytmusic:track:{videoId}")
#     が生成する実際の URI 形式で確認済み) にも関わらず、その戻り値へさらに `[0]` で
#     添字アクセスしているため videoId の「先頭1文字」だけが newIds に入ってしまう
#     (例: videoId "dQw4w9WgXcQ" → "d" のみ)。一方 oldIds は
#     `set([t["videoId"] for t in pls["tracks"]])` で正しくフル videoId を使っている
#     ため、oldIds (11文字) と newIds (1文字) の共通集合 (common) は実質的に常に空になる。
#     結果として `common`/`remove`/`add` の計算が全て壊れ、`remove = oldIds ^ common`
#     が実質 `oldIds` 全体 (プレイリスト内の既存曲全て) になり、`playlistadd`/
#     `playlistdelete`/`playlistmove`/`rename` 等 core.playlists.save() を経由する
#     あらゆる MPD コマンドが、既存の実 YouTube Music プレイリストを保存するたびに
#     現在の全曲を remove_playlist_items() で実際に削除してしまうデータ破壊的な不具合。
#     (add側は1文字の偽videoIdなのでadd_playlist_itemsは失敗するだけで実害はないが、
#     remove側は本物の既存videoIdの集合そのものなので実際に消える)。
#     オフラインの単体テストで実際に再現・確認済み (test_reorder.py 相当、videoIdが
#     "NEW" 等の複数文字の場合に truncate される様子を実証)。単純に `[0]` を外し
#     `parse_uri(p.uri)` の戻り値をそのまま使うよう修正する。
#
# (2) 既存プレイリストと新しいトラック列を「videoId の集合」の差分 (remove/add) としか
#     見ておらず、曲順の変化は一切 YouTube Music 側へ反映しない。MPD の
#     `playlistmove` (mopidy_mpd stored_playlists.py) は Playlist.tracks を並べ替えた
#     上で core.playlists.save() を呼ぶだけの実装のため、(1) を修正しても
#     `playlistmove` 自体は「OK は返るが実際の並び順は変化しない」ままになる
#     (再度 `listplaylistinfo` すると save() 前と同じ順序に戻って見える)。
#
#     ytmusicapi.edit_playlist(moveItem=(setVideoId, successor_setVideoId)) で
#     「setVideoId のアイテムを successor_setVideoId の直前へ移動」できる (実際に
#     ytmusicapi 本体 tests/mixins/test_playlists.py test_edit_playlist で
#     moveItem=(tracks[1].setVideoId, tracks[0].setVideoId) が2曲を入れ替える形で
#     使われていることを確認済み)。これを使い、末尾のペアから先頭へ向かって順に
#     「1つ前の曲を次の曲の直前へ移動」させることで、任意の初期順序から目的の順序を
#     組み立てられる (末尾から処理することで、すでに確定した後方の並びを崩さない)。
#
#     新規追加された曲の setVideoId は add_playlist_items() のレスポンス
#     (playlistEditResults、各要素が videoId/setVideoId を持つ) から取得する。取得
#     できない曲があれば並べ替えは諦めて従来通り (add/remove のみ) に留める
#     (クラッシュしない)。同一 videoId が複数箇所にあるプレイリストは
#     videoId->setVideoId が1対1にならない既知の限界のため、並べ替えも対象外のまま。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "_reorder_playlist"
if MARKER in s:
    print("playlist reorder already patched, skip")
else:
    OLD = '''    def save(self, playlist):
        bId = parse_uri(playlist.uri)
        logger.debug('YTMusic saving playlist "%s" "%s"', playlist.name, bId)
        try:
            pls = self.backend.api.get_playlist(
                bId, limit=self.backend.playlist_item_limit
            )
        except Exception:
            logger.exception("YTMusic saving playlist failed")
            return None
        oldIds = set([t["videoId"] for t in pls["tracks"]])
        newIds = set([parse_uri(p.uri)[0] for p in playlist.tracks])
        common = oldIds & newIds
        remove = oldIds ^ common
        add = newIds ^ common
        if len(remove):
            logger.debug('YTMusic removing items "%s" from playlist', remove)
            try:
                videos = [t for t in pls["tracks"] if t["videoId"] in remove]
                self.backend.api.remove_playlist_items(bId, videos)
            except Exception:
                logger.exception("YTMusic failed removing items from playlist")
        if len(add):
            logger.debug('YTMusic adding items "%s" to playlist', add)
            try:
                self.backend.api.add_playlist_items(bId, list(add))
            except Exception:
                logger.exception("YTMusic failed adding items to playlist")
        if pls["title"] != playlist.name:
            logger.debug('Renaming playlist to "%s"', playlist.name)
            try:
                self.backend.api.edit_playlist(bId, title=playlist.name)
            except Exception:
                logger.exception("YTMusic failed renaming playlist")
        return playlist'''

    NEW = '''    def save(self, playlist):
        bId = parse_uri(playlist.uri)
        logger.debug('YTMusic saving playlist "%s" "%s"', playlist.name, bId)
        try:
            pls = self.backend.api.get_playlist(
                bId, limit=self.backend.playlist_item_limit
            )
        except Exception:
            logger.exception("YTMusic saving playlist failed")
            return None
        newOrder = [parse_uri(p.uri) for p in playlist.tracks]
        oldIds = set([t["videoId"] for t in pls["tracks"]])
        newIds = set(newOrder)
        common = oldIds & newIds
        remove = oldIds ^ common
        add = newIds ^ common
        setVideoIdByVideoId = {
            t["videoId"]: t.get("setVideoId")
            for t in pls["tracks"]
            if t.get("setVideoId")
        }
        # 既存の並び順から remove 分を除いたものが、ytmusicapi の add_playlist_items()
        # が末尾へ追記する (addToTop 未指定=デフォルトfalse) のと合わせて、この時点で
        # YouTube Music 側にあるはずの実際の並び順を再現する (並べ替え要否の判定・
        # 冗長な moveItem 呼び出しの抑制に使うのみで、取得し直しはしない)。
        currentOrder = [
            t["videoId"] for t in pls["tracks"] if t["videoId"] not in remove
        ]
        if len(remove):
            logger.debug('YTMusic removing items "%s" from playlist', remove)
            try:
                videos = [t for t in pls["tracks"] if t["videoId"] in remove]
                self.backend.api.remove_playlist_items(bId, videos)
                for videoId in remove:
                    setVideoIdByVideoId.pop(videoId, None)
            except Exception:
                logger.exception("YTMusic failed removing items from playlist")
        if len(add):
            logger.debug('YTMusic adding items "%s" to playlist', add)
            addList = list(add)
            try:
                result = self.backend.api.add_playlist_items(bId, addList)
                for videoId, added in zip(addList, result.get("playlistEditResults", [])):
                    if added and added.get("setVideoId"):
                        setVideoIdByVideoId[videoId] = added["setVideoId"]
                currentOrder += addList
            except Exception:
                logger.exception("YTMusic failed adding items to playlist")
        if pls["title"] != playlist.name:
            logger.debug('Renaming playlist to "%s"', playlist.name)
            try:
                self.backend.api.edit_playlist(bId, title=playlist.name)
            except Exception:
                logger.exception("YTMusic failed renaming playlist")
        self._reorder_playlist(bId, newOrder, currentOrder, setVideoIdByVideoId)
        return playlist

    def _reorder_playlist(self, bId, newOrder, currentOrder, setVideoIdByVideoId):
        # 目的順序 [A, B, C, D] の全曲の setVideoId が判明していれば、末尾のペアから
        # 先頭へ向かって「1つ前の曲を次の曲の直前へ移動」を繰り返し、任意の初期順序から
        # 目的順序を復元できる (末尾から処理することですでに確定させた後方の並びを
        # 崩さない)。currentOrder (推定される現在の並び) 上で隣接済みのペアは
        # moveItem を送らずスキップし、実際に順序が変わる箇所だけ呼び出す。
        if len(newOrder) < 2 or newOrder == currentOrder:
            return
        setVideoIds = [setVideoIdByVideoId.get(videoId) for videoId in newOrder]
        if any(svid is None for svid in setVideoIds):
            logger.debug(
                "YTMusic skipping playlist reorder: could not resolve setVideoId "
                "for all tracks"
            )
            return
        working = list(currentOrder)
        for i in range(len(newOrder) - 2, -1, -1):
            a, b = newOrder[i], newOrder[i + 1]
            if a not in working or b not in working:
                continue
            if working.index(a) == working.index(b) - 1:
                continue  # 既に目的の隣接関係になっている
            try:
                self.backend.api.edit_playlist(
                    bId, moveItem=(setVideoIds[i], setVideoIds[i + 1])
                )
            except Exception:
                logger.exception("YTMusic failed reordering playlist item")
                return
            working.remove(a)
            working.insert(working.index(b), a)'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of save() anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: save() の newIds truncation バグ ([0]で先頭1文字化) を修正し、"
        "曲順の変化 (playlistmove) も edit_playlist(moveItem=...) で反映するように"
    )
