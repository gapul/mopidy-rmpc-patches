# mopidy_ytmusic/library.py の search() は "album" タグを含むクエリでも
# filter="albums" を叩いた結果を parseSearch() に渡すのみで、parseSearch() の
# resultType=="album" 分岐はマッチしたアルバムを SearchResult.albums (ブラウズ用の
# プレースホルダ) へ積むだけで SearchResult.tracks には一切何も追加しない。
# 一方 mopidy_mpd/protocol/music_db.py の find() は「"album" が query にある時は
# _album_as_track() によるプレースホルダ変換をせず _get_tracks(results) の実トラックを
# 返す」設計 (docstring 通り GMPC の `find album "X" artist "Y"` でアルバムの曲一覧を
# 取得する用途)。実トラックが一切供給されないため `find album "X"` は該当アルバムが
# 実在してもコマンド自体は成功(OK)しつつ常に0件を返してしまう不具合。
#
# 加えて query に "album" と "artist"/"albumartist" が両方含まれる場合、既存の分岐順序
# (elif "albumartist"/"artist" が "album" より先)により artist 側 (filter="artists") が
# 優先され、アルバム名は一切バックエンド検索に使われない。アーティスト名の名義解決に
# 失敗する場合や、対象アルバムが get_artist() のalbums/singles/songs一覧に載らない場合
# (参加アルバムのみ等)、`find album "X" artist "Y"` は本来ヒットするはずのアルバムでも
# 0件になりうる。album 分岐を artist 分岐より先に判定するよう順序を入れ替え、
# album 起点の検索を優先する。
#
# 修正: album 分岐で parseSearch() が返した SearchResult.albums のうち、実際に
# query["album"] へ一致するもの (exact時はcasefold完全一致、非exact時はcasefold部分
# 一致 — search()の"WHAT"を含む、の仕様に合わせる) だけを対象に、既存の
# albumToTracks() (browse() での ytmusic:album:<id> 展開と同じ関数、
# ytalbumtrackartist-patch 適用済みで曲別アーティストも正しく持つ) を使って実際の
# 曲一覧を取得し、SearchResult.tracks へ追加する。これにより find/search 双方で
# "album" タグ検索が実トラックを返すようになる (search album の既存のプレースホルダ
# エントリ自体は互換のため維持)。
# 一致判定を挟まず全SearchResult.albumsを無条件展開すると、非exact(search)時は
# parseSearch(res)がfield指定無し(=一切の絞り込み無し)でYTMusicのfilter="albums"
# 検索結果を丸ごとSearchResult.albumsへ積むため、"the book for,"のような部分一致
# クエリでは無関係な十数アルバム分の全曲(数百曲)を無駄にget_album()展開し、かつ
# それらが実際にはWHATを含まない誤った曲まで結果に混入する重大な回帰になる。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "ytfindalbumtracks-patch: parseSearch()"
if MARKER in s:
    print("library.py already patched (find album tracks), skip")
    raise SystemExit(0)

OLD = '''        elif "albumartist" in query or "artist" in query:
            q1 = ("albumartist" in query and query["albumartist"]) or []
            q2 = ("artist" in query and query["artist"]) or []
            try:
                res = self.backend.api.search(
                    " ".join(q1 + q2), filter="artists"
                )
                if exact:
                    results = self.parseSearch(res, "artist", q1 + q2)
                else:
                    results = self.parseSearch(res)
            except Exception:
                logger.exception(
                    'YTMusic search failed for query "artist"="%s"',
                    " ".join(q1 + q2),
                )
        elif "album" in query:
            try:
                res = self.backend.api.search(
                    " ".join(query["album"]), filter="albums"
                )
                if exact:
                    results = self.parseSearch(res, "album", query["album"])
                else:
                    results = self.parseSearch(res)
            except Exception:
                logger.exception(
                    'YTMusic search failed for query "album"="%s"',
                    " ".join(query["album"]),
                )
        elif "genre" in query:'''

NEW = '''        elif "album" in query:
            try:
                res = self.backend.api.search(
                    " ".join(query["album"]), filter="albums"
                )
                if exact:
                    results = self.parseSearch(res, "album", query["album"])
                else:
                    results = self.parseSearch(res)
            except Exception:
                logger.exception(
                    'YTMusic search failed for query "album"="%s"',
                    " ".join(query["album"]),
                )
            else:
                # ytfindalbumtracks-patch: parseSearch()のalbum分岐はブラウズ用の
                # プレースホルダをSearchResult.albumsへ積むのみでtracksは常に空の
                # ままのため、find album "X" が実トラック0件になる不具合を修正
                # (albumToTracks()はbrowse()のytmusic:album:<id>展開と同じ関数)。
                # 展開対象はquery["album"]に実際に一致するアルバムのみに絞り込み、
                # 無関係なアルバムの全曲展開・誤混入を避ける。
                terms = query["album"]

                def _album_name_matches(name):
                    name_cf = (name or "").casefold()
                    if exact:
                        return any(t.casefold() == name_cf for t in terms)
                    return any(t.casefold() in name_cf for t in terms)

                expanded_tracks = list(results.tracks)
                for album in results.albums:
                    if not _album_name_matches(album.name):
                        continue
                    bId, _ = parse_uri(album.uri)
                    if not bId:
                        continue
                    try:
                        data = self.backend.api.get_album(bId)
                        expanded_tracks.extend(self.albumToTracks(data, bId))
                    except Exception:
                        logger.exception(
                            "YTMusic failed expanding album tracks for %s",
                            album.uri,
                        )
                results = SearchResult(
                    uri=results.uri,
                    tracks=expanded_tracks,
                    artists=results.artists,
                    albums=results.albums,
                )
        elif "albumartist" in query or "artist" in query:
            q1 = ("albumartist" in query and query["albumartist"]) or []
            q2 = ("artist" in query and query["artist"]) or []
            try:
                res = self.backend.api.search(
                    " ".join(q1 + q2), filter="artists"
                )
                if exact:
                    results = self.parseSearch(res, "artist", q1 + q2)
                else:
                    results = self.parseSearch(res)
            except Exception:
                logger.exception(
                    'YTMusic search failed for query "artist"="%s"',
                    " ".join(q1 + q2),
                )
        elif "genre" in query:'''

assert s.count(OLD) == 1, f"expected 1 occurrence of album/artist search branch anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print("patched library.py: search()のalbumタグ検索がalbumToTracks()で実トラックを返すよう修正し、album分岐をartist分岐より優先するよう順序変更")
