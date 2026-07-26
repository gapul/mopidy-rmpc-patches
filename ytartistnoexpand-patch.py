# mopidy_ytmusic.library.py の artistToTracks() (browse ytmusic:artist:<id> / lookup の
# 非アップロード経路が使う唯一の変換関数) は、artist["songs"]["browseId"] が None だと
# 無条件に None を返し、その artist の曲を丸ごと欠落させる。
#
# ytmusicapi (mixins/browsing.py get_artist()) を実際にソース確認したところ:
#   artist["songs"] = {"browseId": None}
#   if "musicShelfRenderer" in results[0]:
#       if "navigationEndpoint" in nav(musicShelf, TITLE):
#           artist["songs"]["browseId"] = nav(musicShelf, TITLE + NAVIGATION_BROWSE_ID)
#       artist["songs"]["results"] = parse_playlist_items(musicShelf["contents"])
# browseId は「曲一覧を全部表示 (More)」の展開リンクがある場合のみ設定される。
# 曲数が少なく展開リンクが無いアーティスト (小規模/インディーズ系で頻出) では
# browseId が None のまま = artistToTracks() が None を返し、browse()/lookup() 両方で
# 曲が0件になる。だが songs["results"] 自体には parse_playlist_items() 済み
# (playlistToTracks が期待するのと同じ videoId/title/artists/album/duration_seconds
# 形式) の曲リストが既に入っており、みすみす捨てている。
#
# 対策: browseId が無い場合は songs["results"] を {"tracks": ...} として
# playlistToTracks() にそのまま渡すフォールバックを追加する (getHistory() が
# 同じ {"tracks": [...]} 形式で playlistToTracks() を呼ぶのと同じ流儀)。
# songs 自体が無い/results も無い (ytmusicapi docstring 曰く "API sometimes does not
# return songs") 場合のみ、従来通り None を返す。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "browseId が無いアーティストのフォールバック"
if MARKER in s:
    print("library.py already patched (ytartistnoexpand), skip")
else:
    OLD = '''    def artistToTracks(self, artist):
        if (
            "songs" in artist
            and "browseId" in artist["songs"]
            and artist["songs"]["browseId"] is not None
        ):
            res = self.backend.api.get_playlist(
                artist["songs"]["browseId"],
                limit=self.backend.playlist_item_limit,
            )
            tracks = self.playlistToTracks(res)
            logger.debug(
                "YTMusic found %d tracks for %s", len(tracks), artist["name"]
            )
            return tracks
        return None'''
    NEW = '''    def artistToTracks(self, artist):
        songs = artist.get("songs") or {}
        if songs.get("browseId") is not None:
            res = self.backend.api.get_playlist(
                songs["browseId"],
                limit=self.backend.playlist_item_limit,
            )
            tracks = self.playlistToTracks(res)
            logger.debug(
                "YTMusic found %d tracks for %s", len(tracks), artist["name"]
            )
            return tracks
        # browseId が無いアーティストのフォールバック: 曲数が少なく「もっと見る」の
        # 展開リンクが無い場合、get_artist() の songs["results"] に既にパース済みの
        # 曲リストが入っているのでそれをそのまま使う (0件にしない)。
        if songs.get("results"):
            tracks = self.playlistToTracks({"tracks": songs["results"]})
            logger.debug(
                "YTMusic found %d tracks for %s (no expand browseId)",
                len(tracks),
                artist["name"],
            )
            return tracks
        return None'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of artistToTracks anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: artistToTracks() が browseId(曲一覧展開リンク)欠落時に"
        "songs['results']へフォールバックせず曲を丸ごと0件にしていた不具合を修正"
    )
