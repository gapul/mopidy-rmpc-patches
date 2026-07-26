# mopidy_ytmusic.library.py の parseSearch() の `elif result["resultType"] == "album":`
# 分岐 (search/find コマンドで検索結果自体がアルバムであるケース) が、result["browseId"]
# の None/欠落チェックを一切せずそのまま self.ALBUMS の辞書キー兼 URI サフィックスとして
# 使っている不具合。
#
# ytmusicapi の parse_search_result() (ytmusicapi/parsers/search.py) は resultType が
# "album" の場合 `search_result["browseId"] = nav(data, NAVIGATION_BROWSE_ID, True)` と
# none_if_absent=True で取得しており (nav() 実装、navigation.py)、該当パスが無ければ例外を
# 投げず None を返す。つまり YouTube Music 側のレスポンスにブラウズリンクが無いアルバム
# (地域制限・カタログ上未リンクの一部リリース等) では browseId is None が実際に起こりうる。
#
# ytartistcache-patch.py (self.ARTISTS) / ytalbumidcache-patch.py (self.ALBUMS、
# playlistToTracks/uploadArtistToTracks/parseSearch song・artist経由songsの4箇所) が
# 既に対処した「id=None を無条件にキャッシュキーへ使ってしまう」のと全く同じバグクラスだが、
# parseSearch() 自身の resultType=="album" 分岐 (検索結果が直接アルバムであるケース) だけは
# この横展開から漏れていた。
# (parseSearch() の artist 分岐配下にある get_artist_albums()/artistq["albums"]["results"]/
# artistq["singles"]["results"] 由来の self.ALBUMS[album["browseId"]] 等は、ytmusicapi の
# parse_album()/parse_single() (parsers/browsing.py) が browseId を none_if_absent 無しで
# 取得しており欠落時は例外化 → 呼び出し元の try/except でアルバム/アーティスト単位ごと
# 丸ごとスキップされるため、browseId=None のまま self.ALBUMS へ到達する経路は無く対象外)
#
# 実害: 検索結果の SearchResult.albums に uri="ytmusic:album:None" という壊れた URI を持つ
# アルバムが返る。rmpc 上ではタイトルが正しく表示されクリックできるように見えるが、選択すると
# browse()/lookup() は bId="None" (文字列) で self.backend.api.get_album("None") を呼び常に
# 失敗し (クラッシュはしないが) サイレントに空フォルダになる。加えて self.ALBUMS は
# ytlibrarycachecap-patch.py 導入の境界付きキャッシュ (_BoundedLibraryCache) として
# プロバイダのライフサイクル全体で共有されるため、browseId=None のアルバムに複数回
# (別の検索呼び出し含む) 遭遇するたびに self.ALBUMS[None] が後勝ちで上書きされ続ける
# (無駄なキャッシュスロットの汚染)。
#
# 対策: ytalbumidcache-patch.py と同じ流儀で、browseId が falsy な場合は self.ALBUMS へ
# キャッシュせず都度その場限りの (uri="" の) Album を作って salbums へ直接足す。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                            self.ALBUMS[result["browseId"]] = Album(
                                uri=f"ytmusic:album:{result['browseId']}",
                                name=result["title"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date=date,
                                musicbrainz_id="",
                            )
                        salbums.add(self.ALBUMS[result["browseId"]])'''

NEW = '''                            if not result.get("browseId"):
                                salbums.add(
                                    Album(
                                        uri="",
                                        name=result["title"],
                                        artists=artists,
                                        num_tracks=None,
                                        num_discs=None,
                                        date=date,
                                        musicbrainz_id="",
                                    )
                                )
                            else:
                                self.ALBUMS[result["browseId"]] = Album(
                                    uri=f"ytmusic:album:{result['browseId']}",
                                    name=result["title"],
                                    artists=artists,
                                    num_tracks=None,
                                    num_discs=None,
                                    date=date,
                                    musicbrainz_id="",
                                )
                                salbums.add(self.ALBUMS[result["browseId"]])'''

if 'if not result.get("browseId"):' in s:
    print("library.py already patched (ytsearchalbumidcache), skip")
else:
    assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch album-branch anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() のresultType==\"album\"分岐がbrowseId=Noneの"
        "非リンクアルバムをself.ALBUMSキャッシュへ汚染混入させ壊れたURI(ytmusic:album:None)を"
        "返してしまう不具合を修正"
    )
