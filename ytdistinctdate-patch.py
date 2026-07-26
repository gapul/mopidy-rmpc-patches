# YTMusicLibraryProvider.get_distinct() は "artist"/"albumartist"/"album" しか分岐を
# 持たず、MPD の `list` コマンドが公式に仕様化している残り2つのTYPE ("date"/"genre" —
# mopidy_mpd/protocol/music_db.py の list() docstringが "TYPE should be album, artist,
# albumartist, date, or genre." と明記) のうち "date" を渡すとどの分岐にも一致せず
# 初期化直後の空の ret がそのまま返る (例外なし・ACKエラーなし、常に0件のサイレントな
# 機能欠落)。`list date` は勿論、同じ get_distinct を共有する `count ... group date`
# (mpdcount-patch.py) / `searchcount ... group date` (mpdsearchcount-patch.py) /
# `list Album group Date` 等のネスト group にも波及する。
# search() 側の date 分岐は既に ytsearchdate-patch.py で修正済みだが、get_distinct()
# 側 (list/count groupの列挙経路) は一度も手当てされていなかった。
# album 分岐 (ytdistinctfilter-patch.py) が既に album dict の "year" キーを
# wanted_dates フィルタで参照しており、"year" が有効なデータソースであることは
# 実証済みのため、同じ get_library_albums() から distinct な year を集める分岐を追加する
# (genre はライブラリ album/artist dict にトラック単位のジャンル情報が無く distinct
# 値を正しく列挙する術が無いため対象外とする)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                if wanted_dates and str(a.get("year") or "") not in wanted_dates:
                    continue
                ret.add(a["title"])
        return ret'''

NEW = '''                if wanted_dates and str(a.get("year") or "") not in wanted_dates:
                    continue
                ret.add(a["title"])
        elif field == "date":
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
            wanted_albums = {str(v).lower() for v in (query or {}).get("album", [])}
            for a in library:
                if wanted_artists:
                    album_artists = {
                        (art.get("name") or "").lower()
                        for art in (a.get("artists") or [])
                    }
                    if not (album_artists & wanted_artists):
                        continue
                if wanted_albums and (a.get("title") or "").lower() not in wanted_albums:
                    continue
                ret.add(str(a.get("year") or ""))
        return ret'''

assert s.count(OLD) == 1, f"expected 1 occurrence of get_distinct album-tail anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print('patched library.py: get_distinct("date") を追加 (list date / count group date が常に0件になる不具合を修正)')
