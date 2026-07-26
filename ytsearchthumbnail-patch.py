# search 経由 (parseSearch()) で得たトラックのアート (get_images) が一切キャッシュされず、
# 検索結果の曲だけ albumart/readpicture が常に失敗する不具合を修正。
#
# ytimages-patch.py が playlistToTracks() (ブラウズ経路) 向けに導入した「応答に既に含まれる
# track["thumbnails"] を追加API呼び出し無しで self.IMAGES へキャッシュする」対策は、
# parseSearch() (search/find コマンド経由、search-patch.py が担う any 検索等の実処理) には
# 一度も横展開されていなかった。ytmusicapi の parse_search_result()/parse_top_result()
# (ytmusicapi/parsers/search.py) はいずれも resultType 共通で無条件に
# search_result["thumbnails"] = nav(data, THUMBNAILS, True) をセットしており、
# search() が返す "song" タイプの結果にも get_artist()["songs"]["results"] 由来の
# アーティストページ内の曲一覧 (artist 分岐の songs サブループ) にも thumbnails は
# 確実に含まれているが、parseSearch() の Track 登録箇所2箇所 (song 分岐 / artist 分岐配下の
# songs サブループ) はどちらもこれを読み捨てている。
#
# 実害: 検索 (search any/track 等) で最初に触れた曲は self.IMAGES に一切登録されず、
# get_images() は track.album が無ければ空、album があっても get_album() を毎回追加で
# 叩く非効率な経路にしかならない (album 自体が無い曲は get_images() が完全に空のまま返す)。
# 同じ曲を先にアルバム/プレイリスト経由でブラウズしていれば self.IMAGES にヒットするため、
# 検索経由か否かで albumart/readpicture の成否が変わる非一貫な挙動になっていた。
#
# 対策: ytimages-patch.py と全く同じ流儀 (解像度小→大の並びを反転して大きい順に) で、
# song 分岐 / artist 分岐 songs サブループの両方の Track 登録直後に
# self.IMAGES[videoId] へキャッシュする処理を追加する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD_SONG = '''                        musicbrainz_id="",
                        last_modified=None,
                    )
                    tracks.add(self.TRACKS[result["videoId"]])'''

NEW_SONG = '''                        musicbrainz_id="",
                        last_modified=None,
                    )
                    if result.get("thumbnails") and result["videoId"] not in self.IMAGES:
                        self.IMAGES[result["videoId"]] = [
                            Image(
                                uri=th["url"],
                                width=th.get("width"),
                                height=th.get("height"),
                            )
                            for th in result["thumbnails"]
                            if "url" in th
                        ][::-1]
                    tracks.add(self.TRACKS[result["videoId"]])'''

assert s.count(OLD_SONG) == 1, (
    f"expected 1 occurrence of parseSearch song anchor (got {s.count(OLD_SONG)})"
)
s = s.replace(OLD_SONG, NEW_SONG, 1)

OLD_ARTIST_SONG = '''                                            musicbrainz_id="",
                                            last_modified=None,
                                        )
                                        tracks.add(self.TRACKS[song["videoId"]])'''

NEW_ARTIST_SONG = '''                                            musicbrainz_id="",
                                            last_modified=None,
                                        )
                                        if song.get("thumbnails") and song["videoId"] not in self.IMAGES:
                                            self.IMAGES[song["videoId"]] = [
                                                Image(
                                                    uri=th["url"],
                                                    width=th.get("width"),
                                                    height=th.get("height"),
                                                )
                                                for th in song["thumbnails"]
                                                if "url" in th
                                            ][::-1]
                                        tracks.add(self.TRACKS[song["videoId"]])'''

assert s.count(OLD_ARTIST_SONG) == 1, (
    f"expected 1 occurrence of parseSearch artist-songs anchor (got {s.count(OLD_ARTIST_SONG)})"
)
s = s.replace(OLD_ARTIST_SONG, NEW_ARTIST_SONG, 1)

open(p, "w").write(s)
print(
    "patched library.py: parseSearch() の song分岐/artist分岐songsサブループが "
    "result/song['thumbnails'] を self.IMAGES にキャッシュし、検索経由のトラックでも "
    "get_images が確実にヒットするよう修正"
)
