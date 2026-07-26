# アルバム/プレイリストのブラウズ時にトラックのアート(get_images)を確実に載せる。
#
# albumToTracks() は末尾で addThumbnails(bId, album) を呼び、album の "thumbnails" を
# self.IMAGES[album_bId] だけでなく "tracks" 中の各 videoId にも複製して積んでいるため、
# アルバム経由のトラックは get_images() で既にヒットする。
#
# 一方 playlistToTracks() (ytmusic:playlist:* のブラウズ、Liked Songs、Recently Played、
# Similar to last played が共有) は ytmusicapi の各トラック dict に既に含まれている
# "thumbnails" (ytmusicapi/parsers/playlists.py の parse_playlist_item が
# THUMBNAILS を per-track で積んでいる) を一切見ておらず、self.IMAGES に何も登録しない。
# 結果 get_images() は func=="track" の分岐に落ち、track.album が無い (アルバム未紐付けの
# 曲やポッドキャスト由来アイテム等) 場合は空、album がある場合でも get_album() を毎回追加で
# 叩く非効率な経路にしかならず、rmpc 側でジャケットが確実に出ない不具合になっていた。
#
# 対策: playlistToTracks で各トラックを初めて登録するタイミングで、既に応答に含まれている
# track["thumbnails"] を addThumbnails と同じ流儀 (解像度小→大の並びを反転して大きい順に)
# self.IMAGES[videoId] へ直接キャッシュする。追加の API 呼び出し無しで get_images() が
# 確実にヒットするようになる。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                        last_modified=None,
                    )
                ret.append(self.TRACKS[track["videoId"]])'''

NEW = '''                        last_modified=None,
                    )
                if track.get("thumbnails") and track["videoId"] not in self.IMAGES:
                    self.IMAGES[track["videoId"]] = [
                        Image(
                            uri=th["url"],
                            width=th.get("width"),
                            height=th.get("height"),
                        )
                        for th in track["thumbnails"]
                        if "url" in th
                    ][::-1]
                ret.append(self.TRACKS[track["videoId"]])'''

assert s.count(OLD) == 1, f"expected 1 occurrence of playlistToTracks anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print("patched library.py: playlistToTracks が track['thumbnails'] を self.IMAGES にキャッシュし、プレイリスト/Liked Songs/履歴経由のトラックでも get_images が確実にヒットするよう修正")
