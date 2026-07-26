# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() (ytplaylistreorder-patch.py
# 適用後の版) には、同じ曲 (videoId) がプレイリスト内に複数回出現するケースの不具合が
# 残っている。TODO 全項目消化済みのため自走エージェントが調査して新規発見・追加した項目。
#
# (1) 【データ欠落】oldIds/newIds/common/remove/add がいずれも `set()` (多重度を持たない
#     集合) で計算されているため、同じ videoId を2回含む目的の並び (newOrder) を渡しても
#     `newIds = set(newOrder)` の時点で2回目が消える。結果 `add = newIds ^ common` が
#     空集合になり、2曲目分の `add_playlist_items()` が一切呼ばれない (実 MPD の m3u
#     ストアドプレイリストは同一 URI の重複を普通に許容するのに、保存すると黙って
#     1曲に減る)。逆に既存側 (oldIds) に重複があり目的側で減らしたい場合も、その
#     videoId が `common` に含まれてしまう限り `remove` には一切入らず、余分な
#     コピーが消えないまま残る。
#
# (2) 【クラッシュ】(1) の症状が出ない場合でも (例えば既存プレイリストが1曲だけの状態で
#     `playlistadd` を同じ URI で2回叩き、2回目の `save()` で newOrder=[V, V] /
#     oldIds={V} になるケース)、`_reorder_playlist()` に渡る newOrder=[V, V] は
#     `setVideoIdByVideoId.get(V)` が1つの値しか返せない (同じ videoId の複数出現を
#     区別できない) ため、既存の `any(svid is None for svid in setVideoIds)` ガードを
#     すり抜けてしまう (None にならず、たまたま解決できてしまうため)。その後
#     `working.remove(a)` (a=b=V) で working から V を1つ除去した直後に
#     `working.insert(working.index(b), a)` (b=V) を呼ぶが、直前の remove で
#     working 中の唯一の V が消えていれば `working.index(b)` が未捕捉の
#     `ValueError: 'V' is not in list` を送出し `save()` 全体が例外で終了する。
#     mopidy core 側はこれを飲み込んで `playlistadd` を `ACK [11@0] {playlistadd}
#     Not able to add ...` として返すため、実際には直前の (無意味な自分自身への)
#     `edit_playlist(moveItem=...)` 呼び出しがYouTube Music側に対して実行されて
#     しまっているにもかかわらず、クライアントには「何も保存されなかった」ように
#     見える不整合も生じる。ytplaylistreorder-patch.py 自身のコメントは「同一 videoId
#     が複数箇所にあるプレイリストは並べ替えも対象外のまま」と明記しており意図的に
#     スキップする設計だったが、実装 (None チェックのみ) がその意図を満たせていなかった。
#
# 修正: (1) は oldIds/newIds を `collections.Counter` (多重集合) で扱い、実際の個数差分
# ぶんだけ remove_playlist_items()/add_playlist_items() を呼ぶよう変更 (削除対象は
# pls["tracks"] を先頭から見て必要数だけ選ぶ)。(2) は `_reorder_playlist()` の冒頭で
# newOrder に重複 videoId があれば (setVideoId で一意に対象を特定できないため)
# 並べ替えを丸ごとスキップするガードを追加 (コメントが元々意図していた挙動を実装で担保)。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "if len(set(newOrder)) != len(newOrder):"
if MARKER in s:
    print("playlist duplicate-videoId handling already patched, skip")
else:
    OLD_SAVE = '''        newOrder = [parse_uri(p.uri) for p in playlist.tracks]
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
                logger.exception("YTMusic failed adding items to playlist")'''

    NEW_SAVE = '''        newOrder = [parse_uri(p.uri) for p in playlist.tracks]
        # Counter (多重集合) で個数差分を取る: 同じ videoId が複数回出現しても、
        # 過不足ぶんだけ正しく remove/add できる (set だと重複が1個に潰れて消える)。
        oldCounts = Counter(t["videoId"] for t in pls["tracks"])
        newCounts = Counter(newOrder)
        removeCounts = oldCounts - newCounts
        addCounts = newCounts - oldCounts
        setVideoIdByVideoId = {
            t["videoId"]: t.get("setVideoId")
            for t in pls["tracks"]
            if t.get("setVideoId")
        }
        # 既存の並び順から remove 分を除いたものが、ytmusicapi の add_playlist_items()
        # が末尾へ追記する (addToTop 未指定=デフォルトfalse) のと合わせて、この時点で
        # YouTube Music 側にあるはずの実際の並び順を再現する (並べ替え要否の判定・
        # 冗長な moveItem 呼び出しの抑制に使うのみで、取得し直しはしない)。
        removeRemaining = dict(removeCounts)
        videos = []
        currentOrder = []
        for t in pls["tracks"]:
            vid = t["videoId"]
            if removeRemaining.get(vid, 0) > 0:
                removeRemaining[vid] -= 1
                videos.append(t)
            else:
                currentOrder.append(vid)
        if videos:
            logger.debug(
                'YTMusic removing items "%s" from playlist',
                [t["videoId"] for t in videos],
            )
            try:
                self.backend.api.remove_playlist_items(bId, videos)
                for t in videos:
                    setVideoIdByVideoId.pop(t["videoId"], None)
            except Exception:
                logger.exception("YTMusic failed removing items from playlist")
        if addCounts:
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

    assert s.count(OLD_SAVE) == 1, f"expected 1 occurrence of save() diff anchor (got {s.count(OLD_SAVE)})"
    s = s.replace(OLD_SAVE, NEW_SAVE, 1)

    OLD_REORDER = '''        if len(newOrder) < 2 or newOrder == currentOrder:
            return
        setVideoIds = [setVideoIdByVideoId.get(videoId) for videoId in newOrder]'''

    NEW_REORDER = '''        if len(newOrder) < 2 or newOrder == currentOrder:
            return
        if len(set(newOrder)) != len(newOrder):
            # 同じ videoId が複数箇所にある目的順序は setVideoId で一意に対象を
            # 特定できず、無理に進めると working.remove()/insert() が
            # ValueError で save() 全体を巻き込んでクラッシュさせる (実際に再現
            # 確認済み)。安全側に倒して並べ替えだけスキップする (add/remove 自体は
            # 既に実行済みなので曲の過不足は正しく反映されている)。
            logger.debug(
                "YTMusic skipping playlist reorder: duplicate videoId in "
                "target order (setVideoId cannot disambiguate which copy to "
                "move)"
            )
            return
        setVideoIds = [setVideoIdByVideoId.get(videoId) for videoId in newOrder]'''

    assert s.count(OLD_REORDER) == 1, f"expected 1 occurrence of reorder anchor (got {s.count(OLD_REORDER)})"
    s = s.replace(OLD_REORDER, NEW_REORDER, 1)

    IMPORT_OLD = "from mopidy import backend\n"
    IMPORT_NEW = "from collections import Counter\n\nfrom mopidy import backend\n"
    assert s.count(IMPORT_OLD) == 1, f"expected 1 occurrence of import anchor (got {s.count(IMPORT_OLD)})"
    s = s.replace(IMPORT_OLD, IMPORT_NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: save() の重複 videoId 処理を Counter 多重集合に変更し "
        "(1曲欠落を修正)、_reorder_playlist() に重複 videoId ガードを追加 "
        "(ValueError クラッシュを修正)"
    )
