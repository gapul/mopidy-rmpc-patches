# library.py の parseSearch() のうち artist 分岐 (resultType=="artist") が
# get_artist(browseId)["songs"]["results"] からTrackを作る唯一のループだけ、
# 同じ関数内の song 分岐 (`if result["videoId"] is None: continue`,
# ytparsegaps-patch.py以前から存在) や playlistToTracks/uploadArtistToTracks/
# albumToTracks/uploadAlbumToTracks (ytunavailabletrack-patch.py) と違い
# videoId 欠落曲のガードを一切持たない。
#
# ytmusicapi は削除/非公開/地域制限などで再生不能になった曲を
# "videoId": None (isAvailable=False) として返す (ytunavailabletrack-patch.py
# が同じ現象を playlistToTracks 等で確認済み)。このループがそれを踏むと:
# (1) self.TRACKS[None] = Track(uri="ytmusic:track:None", ...) が
#     LibraryProvider寿命全体で共有される self.TRACKS キャッシュを汚染し、
#     以後 self.TRACKS に None キーが存在する間、別のアーティストの別の
#     再生不能曲でも同じキャッシュエントリ (最初に遭遇した曲のタイトル・
#     アーティストのまま) を共有してしまう。
# (2) 再生不能な "ytmusic:track:None" が search 結果 (rmpc の
#     `search artist "X"` 等) にそのまま混入し、選択すると再生に失敗する。
#
# 対策: ytunavailabletrack-patch.py と同じ流儀で、videoId が無い曲は
# ループ先頭でスキップして self.TRACKS を汚染しないようにし、
# 1曲単位の try/except で残りの曲の処理を継続する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "YTMusic parseSearch(artist songs): skipping malformed track"
if MARKER in s:
    print("library.py already patched (ytartistsongsvideoid), skip")
else:
    OLD = '''                        if "songs" in artistq:
                            if "results" in artistq["songs"]:
                                for song in artistq["songs"]["results"]:
                                    album = None
                                    if "album" in song:
                                        if (
                                            song["album"]["id"]
                                            not in self.ALBUMS
                                        ):
                                            self.ALBUMS[
                                                song["album"]["id"]
                                            ] = Album(
                                                uri=f"ytmusic:album:{song['album']['id']}",
                                                name=song["album"]["name"],
                                                artists=[
                                                    self.ARTISTS[
                                                        result["browseId"]
                                                    ]
                                                ],
                                                date="0000",
                                                musicbrainz_id="",
                                            )
                                        album = self.ALBUMS[song["album"]["id"]]
                                    # 既存キャッシュがgetTrack()由来の簡易版でも常に上書きする
                                    # (playlistToTracks等と同じ流儀)
                                    song_length_ms = _yt_track_length_ms(song)
                                    self.TRACKS[song["videoId"]] = Track(
                                        uri=f"ytmusic:track:{song['videoId']}",
                                        name=song["title"],
                                        artists=[
                                            self.ARTISTS[result["browseId"]]
                                        ],
                                        album=album,
                                        composers=[],
                                        performers=[],
                                        genre="",
                                        track_no=None,
                                        disc_no=None,
                                        date="0000",
                                        length=song_length_ms,
                                        bitrate=0,
                                        comment="",
                                        musicbrainz_id="",
                                        last_modified=None,
                                    )
                                    tracks.add(self.TRACKS[song["videoId"]])
'''
    NEW = '''                        if "songs" in artistq:
                            if "results" in artistq["songs"]:
                                for song in artistq["songs"]["results"]:
                                    if not song.get("videoId"):
                                        continue
                                    try:
                                        album = None
                                        if "album" in song:
                                            if (
                                                song["album"]["id"]
                                                not in self.ALBUMS
                                            ):
                                                self.ALBUMS[
                                                    song["album"]["id"]
                                                ] = Album(
                                                    uri=f"ytmusic:album:{song['album']['id']}",
                                                    name=song["album"]["name"],
                                                    artists=[
                                                        self.ARTISTS[
                                                            result["browseId"]
                                                        ]
                                                    ],
                                                    date="0000",
                                                    musicbrainz_id="",
                                                )
                                            album = self.ALBUMS[song["album"]["id"]]
                                        # 既存キャッシュがgetTrack()由来の簡易版でも常に上書きする
                                        # (playlistToTracks等と同じ流儀)
                                        song_length_ms = _yt_track_length_ms(song)
                                        self.TRACKS[song["videoId"]] = Track(
                                            uri=f"ytmusic:track:{song['videoId']}",
                                            name=song["title"],
                                            artists=[
                                                self.ARTISTS[result["browseId"]]
                                            ],
                                            album=album,
                                            composers=[],
                                            performers=[],
                                            genre="",
                                            track_no=None,
                                            disc_no=None,
                                            date="0000",
                                            length=song_length_ms,
                                            bitrate=0,
                                            comment="",
                                            musicbrainz_id="",
                                            last_modified=None,
                                        )
                                        tracks.add(self.TRACKS[song["videoId"]])
                                    except Exception:
                                        logger.debug(
                                            "YTMusic parseSearch(artist songs): skipping malformed track",
                                            exc_info=True,
                                        )
                                        continue
'''
    assert s.count(OLD) == 1, f"artist songs loop anchor count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch()のartist分岐(get_artist songs)が"
        "videoId=None(再生不能曲)をself.TRACKSキャッシュへ汚染混入させる"
        "不具合を修正 (playlistToTracks等ytunavailabletrack-patch.pyと同じ対策)"
    )
