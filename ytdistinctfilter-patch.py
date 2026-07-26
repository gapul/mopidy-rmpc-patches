# ytdistinct-patch.py が有効化した get_distinct("album") はライブラリの全アルバムを
# 無条件で返すのみで、引数の query (mpdlist-patch.py が `list Album group AlbumArtist` で
# 各 AlbumArtist ごとに subquery={"albumartist": [artist]} を積んで呼ぶもの) を一切見ない。
# 結果、`list Album group AlbumArtist` は全 AlbumArtist の子に「ライブラリの全アルバム」が
# 丸ごと重複表示されてしまう (rmpc の Album Artists タブが実質使い物にならない)。
# `count group album` (mpdcount-patch.py) も同じ get_distinct 呼び出しを共有するため同様に
# 誤ったグルーピングになる。artist/albumartist (ytmusicapi の album dict が持つ "artists" キー)
# と date (同 "year" キー) でクエリを実際にフィルタするよう修正する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''        elif field == "album":
            try:
                library = self.backend.api.get_library_albums(
                    limit=self.backend.playlist_item_limit
                )
            except Exception:
                logger.exception("YTMusic failed getting albums from library")
                library = []
            for a in library:
                if a.get("title"):
                    ret.add(a["title"])
        return ret'''

NEW = '''        elif field == "album":
            try:
                library = self.backend.api.get_library_albums(
                    limit=self.backend.playlist_item_limit
                )
            except Exception:
                logger.exception("YTMusic failed getting albums from library")
                library = []
            wanted_artists = {
                v.lower()
                for k in ("artist", "albumartist")
                for v in (query or {}).get(k, [])
            }
            wanted_dates = {str(v) for v in (query or {}).get("date", [])}
            for a in library:
                if not a.get("title"):
                    continue
                if wanted_artists:
                    album_artists = {
                        (art.get("name") or "").lower()
                        for art in (a.get("artists") or [])
                    }
                    if not (album_artists & wanted_artists):
                        continue
                if wanted_dates and str(a.get("year") or "") not in wanted_dates:
                    continue
                ret.add(a["title"])
        return ret'''

assert s.count(OLD) == 1, f"expected 1 occurrence of album get_distinct anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print("patched library.py: get_distinct(\"album\") が query の artist/albumartist/date で実際に絞り込むよう修正")
