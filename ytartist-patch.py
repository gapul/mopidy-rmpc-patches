# ytmusicapi の parse_song_runs(skip_type_spec=True) は "Song • ..." のような
# resultType 表記 (Song/Album/Video/Single/EP/...) を、後続に本物のアーティスト run が
# 続かない場合 (無リンクの曲で subtitle が "Song • 3:23" のように duration がすぐ続く等)
# スキップできず、表記そのものを唯一のアーティスト (id=None) として誤って返す。
# mopidy_ytmusic の parseSearch はこれをそのまま Artist 化するため、rmpc の検索結果で
# Artist: Song / AlbumArtist: Song / Artist: Album のような誤表記になる (実データで再現・
# 確認済み: 例 "UNDEAD"/"セブンティーン" の単曲、"THE BOOK for," のアルバム)。
# 対策: id が None かつ名前が既知の resultType 表記と一致するものは実在しないアーティスト
# として除外する (残った本物のアーティストはそのまま反映、全滅した場合はアーティスト無し
# として空になる — 誤った名前を出すよりは正しい)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '                            for a in result["artists"]:\n' '                                if a["id"] not in self.ARTISTS:'
NEW = (
    '                            for a in result["artists"]:\n'
    '                                if a.get("id") is None and (a.get("name") or "").strip().lower() in {\n'
    '                                    "song", "video", "album", "single", "ep",\n'
    '                                    "episode", "podcast", "station", "playlist", "profile",\n'
    '                                }:\n'
    '                                    continue\n'
    '                                if a["id"] not in self.ARTISTS:'
)
assert s.count(OLD) == 2, f"expected 2 occurrences of: {OLD!r} (got {s.count(OLD)})"
s = s.replace(OLD, NEW)

open(p, "w").write(s)
print("patched library.py: parseSearch の resultType 誤爆アーティスト(Song/Album等)を除外")
