# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.save() が、実際の YouTube Music
# プレイリストを削除/非公開化/地域制限で再生不能になった曲 (videoId が偽値。ytmusicapi は
# こうした曲を "videoId": None 等として返す。ytunavailabletrack-patch.py の library.py 側の
# 修正で library.playlistToTracks() が `if not track.get("videoId"): continue` により
# こうした曲を最初から Mopidy 側の Track 列 (= Playlist.tracks) へ一切含めないことを確認済み)
# を、ユーザーが「取り除いた曲」と誤認し、無関係に実際の YouTube Music プレイリストから
# 削除してしまう不具合 (実データ破壊)。
#
# save() は現在の実プレイリストを再取得した生レスポンス `pls["tracks"]` (再生不能曲も含む)
# から `oldCounts = Counter(t["videoId"] for t in pls["tracks"])` を作る一方、
# 目的の並び `newOrder` は `playlist.tracks` (= playlistToTracks() でフィルタ済み、
# 再生不能曲は含まれ得ない) から作る。この非対称性のため、`removeCounts = oldCounts -
# newCounts` は再生不能曲の videoId (None) を必ず「除去対象」として含んでしまい、
# 続く for ループが該当曲の生トラック dict (setVideoId 込み) を `videos` に積み、
# `remove_playlist_items(bId, videos)` が実行される。つまり `playlistadd`/`playlistdelete`/
# `playlistmove`/`rename` など core.playlists.save() を経由するどの MPD コマンドを実行
# しても、そのプレイリストに1曲でも再生不能曲が含まれていれば、ユーザーが一切意図して
# いないのにその曲が実際に YouTube Music 側から削除されてしまう。
#
# 修正: 差分計算・削除候補列挙のいずれも、videoId を持つ「利用可能な」曲
# (`playlist.tracks` 側に現れ得る集合と揃える) だけを対象にする。再生不能曲は
# newOrder 側に最初から存在せず、Mopidy から見て「そこにある」ことにもならないため、
# save() の add/remove/reorder どの判断にも関与させない (触れずにそのまま実プレイリストに
# 残す) のが正しい。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "availableTracks"
if MARKER in s:
    print("playlist unavailable-track guard already patched, skip")
else:
    OLD = '''        newOrder = [parse_uri(p.uri) for p in playlist.tracks]
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
                currentOrder.append(vid)'''

    NEW = '''        newOrder = [parse_uri(p.uri) for p in playlist.tracks]
        # playlistToTracks() 等 (ytunavailabletrack-patch.py) は videoId が偽値
        # (削除/非公開/地域制限で再生不能) のトラックを最初から Mopidy 側へ渡さない
        # ため、そもそも newOrder には出現し得ない。差分計算・削除候補の列挙も同じ
        # 「利用可能な曲」の集合に揃えないと、再生不能曲がユーザーの意図に関係なく
        # 除去対象と誤認され実際に YouTube Music から削除されてしまう。
        availableTracks = [t for t in pls["tracks"] if t.get("videoId")]
        # Counter (多重集合) で個数差分を取る: 同じ videoId が複数回出現しても、
        # 過不足ぶんだけ正しく remove/add できる (set だと重複が1個に潰れて消える)。
        oldCounts = Counter(t["videoId"] for t in availableTracks)
        newCounts = Counter(newOrder)
        removeCounts = oldCounts - newCounts
        addCounts = newCounts - oldCounts
        setVideoIdByVideoId = {
            t["videoId"]: t.get("setVideoId")
            for t in availableTracks
            if t.get("setVideoId")
        }
        # 既存の並び順から remove 分を除いたものが、ytmusicapi の add_playlist_items()
        # が末尾へ追記する (addToTop 未指定=デフォルトfalse) のと合わせて、この時点で
        # YouTube Music 側にあるはずの実際の並び順を再現する (並べ替え要否の判定・
        # 冗長な moveItem 呼び出しの抑制に使うのみで、取得し直しはしない)。
        removeRemaining = dict(removeCounts)
        videos = []
        currentOrder = []
        for t in availableTracks:
            vid = t["videoId"]
            if removeRemaining.get(vid, 0) > 0:
                removeRemaining[vid] -= 1
                videos.append(t)
            else:
                currentOrder.append(vid)'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of save() diff anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: save() が再生不能曲(videoId無し)を除去対象と誤認し"
        "実プレイリストから削除してしまう不具合を修正"
    )
