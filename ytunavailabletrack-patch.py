# library.py の playlistToTracks()/uploadArtistToTracks()/albumToTracks()/
# uploadAlbumToTracks() (プレイリスト・アルバム・アップロード楽曲を Track へ変換する
# 4つの中核関数) が1曲もガードせず処理しており、以下の実データで再現しうる不具合がある。
#
# ytmusicapi (parsers/playlists.py) は削除/非公開/地域制限等で再生不能になった楽曲を
# "videoId": None (かつ isAvailable=False) として返す。この4関数はいずれも
# `track["videoId"] not in self.TRACKS` を無条件キャッシュキーとして使うため:
#
# (1) 再生不能曲は "ytmusic:track:None" という無効なURIのTrackとしてそのままキューに
#     混入しうる (再生すればstreamが解決できずエラーになる)。
# (2) さらに深刻なのは self.TRACKS が LibraryProvider インスタンスの寿命全体で共有される
#     キャッシュであること: 最初に遭遇した再生不能曲が self.TRACKS[None] にそのタイトル・
#     アーティストで一度キャッシュされると、そのmopidyプロセスが生きている限り、
#     全く別のプレイリスト/アルバムに含まれる別の再生不能曲であっても
#     `None not in self.TRACKS` が False になり、最初の1件のタイトル・アーティストに
#     化けたまま表示され続ける (データ破損)。
# (3) 加えて1曲でも "title" 等の想定キーを欠くとその関数呼び出し全体が KeyError で
#     失敗し、呼び出し元のtry/except(browse()側)経由でプレイリスト/アルバム全体が
#     0曲になる (ytautoplaylistfix-patch.py/ytmoodgenre-patch.py と同じ
#     「1件の異常が全体を道連れにする」パターン)。
#
# 対策: 4関数とも videoId が無い(再生不能)曲は最初にスキップして self.TRACKS を
# 汚染しないようにし、あわせて1曲単位の try/except で残りの曲の処理を継続する
# (ytautoplaylistfix-patch.py と同じ「1件落ちても全体は継続する」流儀)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "playlistToTracks: skipping malformed track"
if MARKER in s:
    print("library.py already patched (ytunavailabletrack), skip")
else:
    # (1) playlistToTracks
    OLD1 = '''    def playlistToTracks(self, pls):
        ret = []
        if "tracks" in pls:
            for track in pls["tracks"]:
                track_length_ms = _yt_track_length_ms(track)
                artists = []
                if track.get("artists"):
                    for a in track["artists"]:
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
                elif "byline" in track:
                    artists = [
                        Artist(
                            name=track["byline"],
                            sortname=track["byline"],
                            musicbrainz_id="",
                        )
                    ]
                else:
                    artists = None

                if "album" in track and track["album"] is not None:
                    if track["album"]["id"] not in self.ALBUMS:
                        self.ALBUMS[track["album"]["id"]] = Album(
                            uri=f"ytmusic:album:{track['album']['id']}",
                            name=track["album"]["name"],
                            artists=artists,
                            num_tracks=None,
                            num_discs=None,
                            date="0000",
                            musicbrainz_id="",
                        )
                    album = self.ALBUMS[track["album"]["id"]]
                else:
                    album = None

                if track["videoId"] not in self.TRACKS:
                    self.TRACKS[track["videoId"]] = Track(
                        uri=f"ytmusic:track:{track['videoId']}",
                        name=track["title"],
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
                ret.append(self.TRACKS[track["videoId"]])
        return ret
'''
    NEW1 = '''    def playlistToTracks(self, pls):
        ret = []
        if "tracks" in pls:
            for track in pls["tracks"]:
                if not track.get("videoId"):
                    continue
                try:
                    track_length_ms = _yt_track_length_ms(track)
                    artists = []
                    if track.get("artists"):
                        for a in track["artists"]:
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
                    elif "byline" in track:
                        artists = [
                            Artist(
                                name=track["byline"],
                                sortname=track["byline"],
                                musicbrainz_id="",
                            )
                        ]
                    else:
                        artists = None

                    if "album" in track and track["album"] is not None:
                        if track["album"]["id"] not in self.ALBUMS:
                            self.ALBUMS[track["album"]["id"]] = Album(
                                uri=f"ytmusic:album:{track['album']['id']}",
                                name=track["album"]["name"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date="0000",
                                musicbrainz_id="",
                            )
                        album = self.ALBUMS[track["album"]["id"]]
                    else:
                        album = None

                    if track["videoId"] not in self.TRACKS:
                        self.TRACKS[track["videoId"]] = Track(
                            uri=f"ytmusic:track:{track['videoId']}",
                            name=track["title"],
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
                    ret.append(self.TRACKS[track["videoId"]])
                except Exception:
                    logger.debug(
                        "YTMusic playlistToTracks: skipping malformed track",
                        exc_info=True,
                    )
                    continue
        return ret
'''
    assert s.count(OLD1) == 1, f"playlistToTracks anchor count={s.count(OLD1)}"
    s = s.replace(OLD1, NEW1, 1)

    # (2) uploadArtistToTracks
    OLD2 = '''    def uploadArtistToTracks(self, artist):
        ret = []
        for track in artist:
            artists = []
            for a in track.get("artists") or []:
                if not a.get("id"):
                    artists.append(
                        Artist(name=a["name"], sortname=a["name"], musicbrainz_id="")
                    )
                    continue
                if a["id"] not in self.ARTISTS:
                    self.ARTISTS[a["id"]] = Artist(
                        uri=f"ytmusic:artist:{a['id']}:upload",
                        name=a["name"],
                        sortname=a["name"],
                        musicbrainz_id="",
                    )
                artists.append(self.ARTISTS[a["id"]])
            if track.get("album"):
                if track["album"]["id"] not in self.ALBUMS:
                    self.ALBUMS[track["album"]["id"]] = Album(
                        uri=f"ytmusic:album:{track['album']['id']}:upload",
                        name=track["album"]["name"],
                        artists=artists,
                        num_tracks=None,
                        num_discs=None,
                        date="0000",
                        musicbrainz_id="",
                    )
                album = self.ALBUMS[track["album"]["id"]]
            else:
                album = None
            track_length_ms = _yt_track_length_ms(track)
            self.TRACKS[track["videoId"]] = Track(
                uri=f"ytmusic:track:{track['videoId']}",
                name=track["title"],
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
            ret.append(self.TRACKS[track["videoId"]])
        return ret
'''
    NEW2 = '''    def uploadArtistToTracks(self, artist):
        ret = []
        for track in artist:
            if not track.get("videoId"):
                continue
            try:
                artists = []
                for a in track.get("artists") or []:
                    if not a.get("id"):
                        artists.append(
                            Artist(name=a["name"], sortname=a["name"], musicbrainz_id="")
                        )
                        continue
                    if a["id"] not in self.ARTISTS:
                        self.ARTISTS[a["id"]] = Artist(
                            uri=f"ytmusic:artist:{a['id']}:upload",
                            name=a["name"],
                            sortname=a["name"],
                            musicbrainz_id="",
                        )
                    artists.append(self.ARTISTS[a["id"]])
                if track.get("album"):
                    if track["album"]["id"] not in self.ALBUMS:
                        self.ALBUMS[track["album"]["id"]] = Album(
                            uri=f"ytmusic:album:{track['album']['id']}:upload",
                            name=track["album"]["name"],
                            artists=artists,
                            num_tracks=None,
                            num_discs=None,
                            date="0000",
                            musicbrainz_id="",
                        )
                    album = self.ALBUMS[track["album"]["id"]]
                else:
                    album = None
                track_length_ms = _yt_track_length_ms(track)
                self.TRACKS[track["videoId"]] = Track(
                    uri=f"ytmusic:track:{track['videoId']}",
                    name=track["title"],
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
                ret.append(self.TRACKS[track["videoId"]])
            except Exception:
                logger.debug(
                    "YTMusic uploadArtistToTracks: skipping malformed track",
                    exc_info=True,
                )
                continue
        return ret
'''
    assert s.count(OLD2) == 1, f"uploadArtistToTracks anchor count={s.count(OLD2)}"
    s = s.replace(OLD2, NEW2, 1)

    # (3) uploadAlbumToTracks (tracksループ部分のみ置換)
    OLD3 = '''        if "tracks" in album:
            for track in album["tracks"]:
                # if track["videoId"] not in self.TRACKS:
                track_length_ms = _yt_track_length_ms(track)
                self.TRACKS[track["videoId"]] = Track(
                    uri=f"ytmusic:track:{track['videoId']}",
                    name=track["title"],
                    artists=artists,
                    album=self.ALBUMS[bId],
                    composers=[],
                    performers=[],
                    genre="",
                    track_no=None,
                    disc_no=None,
                    date=album_date,
                    length=track_length_ms,
                    bitrate=0,
                    comment="",
                    musicbrainz_id="",
                    last_modified=None,
                )
                ret.append(self.TRACKS[track["videoId"]])
        return ret
'''
    NEW3 = '''        if "tracks" in album:
            for track in album["tracks"]:
                if not track.get("videoId"):
                    continue
                try:
                    # if track["videoId"] not in self.TRACKS:
                    track_length_ms = _yt_track_length_ms(track)
                    self.TRACKS[track["videoId"]] = Track(
                        uri=f"ytmusic:track:{track['videoId']}",
                        name=track["title"],
                        artists=artists,
                        album=self.ALBUMS[bId],
                        composers=[],
                        performers=[],
                        genre="",
                        track_no=None,
                        disc_no=None,
                        date=album_date,
                        length=track_length_ms,
                        bitrate=0,
                        comment="",
                        musicbrainz_id="",
                        last_modified=None,
                    )
                    ret.append(self.TRACKS[track["videoId"]])
                except Exception:
                    logger.debug(
                        "YTMusic uploadAlbumToTracks: skipping malformed track",
                        exc_info=True,
                    )
                    continue
        return ret
'''
    assert s.count(OLD3) == 1, f"uploadAlbumToTracks anchor count={s.count(OLD3)}"
    s = s.replace(OLD3, NEW3, 1)

    # (4) albumToTracks (tracksループ部分のみ置換)
    OLD4 = '''        for index, song in enumerate(album["tracks"], start=1):
            # if song["videoId"] not in self.TRACKS:
            song_length_ms = _yt_track_length_ms(song)
            # Annoying workaround for Various Artists
            if (
                "artists" not in song
                or song["artists"] == artistname
                or song["artists"] is None
            ):
                songartists = artists
            else:
                songartists = [Artist(name=artistname)]
            self.TRACKS[song["videoId"]] = Track(
                uri=f"ytmusic:track:{song['videoId']}",
                name=song["title"],
                artists=songartists,
                album=self.ALBUMS[bId],
                composers=[],
                performers=[],
                genre="",
                track_no=index,
                disc_no=None,
                date=date,
                length=song_length_ms,
                bitrate=0,
                comment="",
                musicbrainz_id="",
                last_modified=None,
            )
            ret.append(self.TRACKS[song["videoId"]])
        self.addThumbnails(bId, album)
        return ret
'''
    NEW4 = '''        for index, song in enumerate(album["tracks"], start=1):
            if not song.get("videoId"):
                continue
            try:
                # if song["videoId"] not in self.TRACKS:
                song_length_ms = _yt_track_length_ms(song)
                # Annoying workaround for Various Artists
                if (
                    "artists" not in song
                    or song["artists"] == artistname
                    or song["artists"] is None
                ):
                    songartists = artists
                else:
                    songartists = [Artist(name=artistname)]
                self.TRACKS[song["videoId"]] = Track(
                    uri=f"ytmusic:track:{song['videoId']}",
                    name=song["title"],
                    artists=songartists,
                    album=self.ALBUMS[bId],
                    composers=[],
                    performers=[],
                    genre="",
                    track_no=index,
                    disc_no=None,
                    date=date,
                    length=song_length_ms,
                    bitrate=0,
                    comment="",
                    musicbrainz_id="",
                    last_modified=None,
                )
                ret.append(self.TRACKS[song["videoId"]])
            except Exception:
                logger.debug(
                    "YTMusic albumToTracks: skipping malformed track",
                    exc_info=True,
                )
                continue
        self.addThumbnails(bId, album)
        return ret
'''
    assert s.count(OLD4) == 1, f"albumToTracks anchor count={s.count(OLD4)}"
    s = s.replace(OLD4, NEW4, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: playlistToTracks()/uploadArtistToTracks()/"
        "albumToTracks()/uploadAlbumToTracks() の videoId=None(再生不能曲)を"
        "self.TRACKSキャッシュへ汚染混入させる不具合と、1曲の想定外データが"
        "呼び出し全体を巻き込むKeyErrorを修正"
    )
