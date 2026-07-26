# Liked Songs (ytmusic:liked) を開くと mopidy_ytmusic.library.playlistToTracks() が
# TypeError: 'NoneType' object is not iterable で丸ごとクラッシュし空フォルダになる。
#
# 実機で再現・ログのトレースバックで確認した原因: get_liked_songs() (= get_playlist("LM")) 自体は
# 成功しているが、Liked Songs プレイリストにポッドキャストのエピソード等の非音楽アイテムが
# 含まれていると ytmusicapi の parse_playlist_items (ytmusicapi/parsers/playlists.py, コメント
# 「Non music videos, for example: podcast episodes」) が artist_index を解決できず
# `"artists": None` (キー自体は存在するが値が None) を返す。playlistToTracks 側は
# `if "artists" in track:` でキーの有無しか見ておらず、値が None のまま
# `for a in track["artists"]:` に突入してクラッシュしていた。
#
# 修正: キー存在チェックを真偽値チェックに変え、値が None/空でも既存の「artists 情報なし」経路
# (elif "byline" / else: artists = None) に自然にフォールバックさせる (Track(artists=None) は
# 同関数の他分岐で既に使われている経路であり安全)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                artists = []
                if "artists" in track:
                    for a in track["artists"]:'''

NEW = '''                artists = []
                if track.get("artists"):
                    for a in track["artists"]:'''

assert s.count(OLD) == 1, f"expected 1 occurrence of artists-key anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print("patched library.py: playlistToTracks が artists=None (ポッドキャスト等の非音楽アイテム) でクラッシュする不具合を修正")
