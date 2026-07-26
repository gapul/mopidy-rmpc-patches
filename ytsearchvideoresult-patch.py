# mopidy_ytmusic/library.py の parseSearch() (search()経由、"any"/genre/date/track_no/
# _META_SEARCH_FIELDS 等 filter=None で呼ぶ全ての検索パスが通る共通パーサ) の
# if/elif チェーンが resultType "song"/"album"/"artist" の3種類しか処理しておらず、
# ytmusicapi 1.12.0 の検索結果に頻出する resultType "video" (ytmusicapi/parsers/
# search.py の ALL_RESULT_TYPES に "video" が既に列挙されており、"song"/"video"/"album"
# 共通で videoId/artists/duration を parse_song_runs() 経由でパースする「songとほぼ
# 同一構造」の結果) を素通しし黙って捨てている不具合。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# 実害・実機確認 (dev mopidy、実ytmusicアカウント、TCP 6601): YouTube Music上で公式
# ミュージックビデオが強く優勢な人気曲だと、"search any"/"find any" (rmpcの検索UIが
# 実際に発行するのはこの any 検索) の無フィルタ結果が resultType "video" のみで占められ
# 一致する "song"/"album" が1件も無いことがあり、その場合 parseSearch() は空の
# SearchResult を返す。`search any "打上花火"`/`"紅蓮華"`/`"despacito"`/`"wonderwall"`は
# いずれも `OK` (0件) だったが、同じ曲は `search title "打上花火"` (filter="songs"、
# resultTypeがsongに絞られる別経路) では20件ヒットする — 曲自体は存在し再生可能なのに
# any検索という主要経路でだけ発見不能になる非一貫なコンテンツ欠落。mopidy.logに
# エラー/例外は一切出ない(if/elifチェーンがどの分岐にもマッチせずthrough-する、
# 例外を投げない黙殺なので既存のtry/except (1652行目) にも捕捉されない)ため、
# ログからは原因が全く分からない。
#
# 対策: song分岐 (result["resultType"] == "song") と全く同じロジック
# (artists解決・self.ARTISTSキャッシュ・album有無の処理・Track登録・self.TRACKS
# キャッシュ) を resultType "video" にも複製する。field=="track" によるタイトル
# 完全一致フィルタは複製しない — video が field="track" 経由 (filter="songs" の
# exact検索、search()のtrack_name分岐) で渡ってくることは無く(filter="songs"は
# ytmusicapi側でresultTypeをsongに絞る)、field は常にNoneのまま呼ばれる経路
# (any/genre/date/track_no/meta-tag、いずれもfilter=None)でしか video 分岐に
# 到達しないため。album有無の判定はsong分岐と同じ result.get("album") を使う
# (video結果はparse_song_runs()のalbum-runがあれば album キーを持ちうるため、
# 無条件のNone決め打ちにはしない)。ytparsegaps-patch.py 同様 result.get("artists")
# or [] でフォールバックし artists 欠落時の KeyError も踏まない。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif result["resultType"] == "video":'
if MARKER in s:
    print("library.py already patched (ytsearchvideoresult), skip")
else:
    OLD = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

    NEW = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "video":
                    if result.get("videoId") is None:
                        continue
                    track_length_ms = _yt_track_length_ms(result)
                    artists = []
                    for a in result.get("artists") or []:
                        if a.get("id") is None and (a.get("name") or "").strip().lower() in {
                            "song", "video", "album", "single", "ep",
                            "episode", "podcast", "station", "playlist", "profile",
                        }:
                            continue
                        if not a.get("id"):
                            artists.append(
                                Artist(name=a["name"], sortname=a["name"], musicbrainz_id="")
                            )
                            continue
                        if a["id"] not in self.ARTISTS:
                            self.ARTISTS[a["id"]] = Artist(
                                uri=f"ytmusic:artist:{a['id']}",
                                name=a["name"],
                                sortname=a["name"],
                                musicbrainz_id="",
                            )
                        artists.append(self.ARTISTS[a["id"]])
                    if not artists:
                        try:
                            artists = self.getTrack(result["videoId"]).artists
                        except Exception:
                            logger.debug(
                                "YTMusic parseSearch: failed to backfill video artist via getTrack",
                                exc_info=True,
                            )
                    album = None
                    if result.get("album"):
                        if not result["album"].get("id"):
                            album = Album(
                                uri="",
                                name=result["album"]["name"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date="0000",
                                musicbrainz_id="",
                            )
                        else:
                            if result["album"]["id"] not in self.ALBUMS:
                                self.ALBUMS[result["album"]["id"]] = Album(
                                    uri=f"ytmusic:album:{result['album']['id']}",
                                    name=result["album"]["name"],
                                    artists=artists,
                                    num_tracks=None,
                                    num_discs=None,
                                    date="0000",
                                    musicbrainz_id="",
                                )
                            album = self.ALBUMS[result["album"]["id"]]
                    self.TRACKS[result["videoId"]] = Track(
                        uri=f"ytmusic:track:{result['videoId']}",
                        name=result["title"],
                        artists=artists,
                        album=album,
                        composers=[],
                        performers=[],
                        genre="",
                        track_no=None,
                        disc_no=None,
                        date="0000",
                        length=track_length_ms,
                        bitrate=0,
                        comment="",
                        musicbrainz_id="",
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
                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch song/album boundary anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() が resultType \"video\" を無視し検索結果から "
        "黙って落としていた不具合を修正。song分岐と同じロジックでTrackとして拾うよう追加"
    )
