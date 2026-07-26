# mopidy_ytmusic.library.py の self.TRACKS (videoId -> Track のプロセス内キャッシュ) が、
# 一度でも簡易版 (album=None、artistにURIなし) で書き込まれると、それ以降 playlistToTracks()/
# parseSearch() が同じ曲に遭遇しても二度と豊富なメタデータで上書きされない不具合を発見。
#
# 簡易版の出所は getTrack(bId) (self.lookup() が生の ytmusic:track:<id> URI を解決する際の
# フォールバック、mpdlsinfouri-patch.py の `lsinfo <生URI>` がまさにこの経路を叩く): album=None、
# artists=[Artist(name=...)] (URIなし) の最小限の Track しか組み立てない。
#
# 一方 playlistToTracks() は `if track["videoId"] not in self.TRACKS:` で、parseSearch() の
# song分岐は `if result["videoId"] in self.TRACKS: <再利用>` で、同分岐内のartist経由songs
# ("songs" in artistq の分岐) も `if song["videoId"] in self.TRACKS: <再利用>` で、いずれも
# 既にキャッシュ済みなら中身の質を問わず無条件に再利用してしまう。姉妹関数の
# uploadArtistToTracks()/uploadAlbumToTracks()/albumToTracks() は同種のガードが
# ytuploadfix-patch.py/ytalbumfix-patch.py で既に無条件上書きに修正済みだが、
# playlistToTracks()/parseSearch() だけ取り残されていた (対称性の欠落)。
#
# 実害: rmpc の Rating/Liked 検索は sticker (sqlite永続化、mopidy再起動をまたいで残る) に
# 保存した曲URIへ `lsinfo` を command-list で一括送信する。mopidy再起動直後は self.TRACKS が
# 空のため、この最初の lsinfo が getTrack() 経由で簡易版を作り永久にキャッシュへ焼き付ける。
# 以後、同じ曲が本来のプレイリスト一覧や検索結果に (album/artistURI付きの豊富なデータで)
# 現れても、playlistToTracks()/parseSearch() は「もうキャッシュにあるから」と簡易版を
# 返し続け、Album タグ・AlbumArtist・ブラウズ可能な Artist URI が mopidy プロセスの
# 残り寿命ずっと欠落したままになり、rmpc の Album/Artist によるグルーピング・ナビゲーション
# が壊れる。
#
# 修正: playlistToTracks() のガード、parseSearch() のsong分岐の外側ガード+内側の冗長な
# 二重ガード、同関数のartist経由songs分岐の外側ガード、計4箇所を撤去し (comment-outの流儀は
# uploadAlbumToTracks() 等と同じ)、常に最新の情報で self.TRACKS を再構築するよう統一。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD_PLAYLIST = '''                    if track["videoId"] not in self.TRACKS:
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
                    if track.get("thumbnails") and track["videoId"] not in self.IMAGES:'''

NEW_PLAYLIST = '''                    # if track["videoId"] not in self.TRACKS:
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
                    if track.get("thumbnails") and track["videoId"] not in self.IMAGES:'''

assert s.count(OLD_PLAYLIST) == 1, (
    f"expected 1 occurrence of playlistToTracks TRACKS-guard anchor (got {s.count(OLD_PLAYLIST)})"
)
s = s.replace(OLD_PLAYLIST, NEW_PLAYLIST, 1)

OLD_SONG = '''                if result["resultType"] == "song":
                    if field == "track" and not any(
                        q.casefold() == result["title"].casefold() for q in queries
                    ):
                        continue
                    if result["videoId"] in self.TRACKS:
                        tracks.add(self.TRACKS[result["videoId"]])
                    else:
                        track_length_ms = _yt_track_length_ms(result)
                        if result["videoId"] is None:
                            continue
                        if result["videoId"] not in self.TRACKS:
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
                            album = None
                            if result.get("album"):
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
                        tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

NEW_SONG = '''                if result["resultType"] == "song":
                    if field == "track" and not any(
                        q.casefold() == result["title"].casefold() for q in queries
                    ):
                        continue
                    if result["videoId"] is None:
                        continue
                    # 既存キャッシュがgetTrack()由来の簡易版(album/artists欠落)でも
                    # 常に上書きし最新の詳細情報で補完する (playlistToTracks等と同じ流儀)
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
                    album = None
                    if result.get("album"):
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
                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

assert s.count(OLD_SONG) == 1, f"expected 1 occurrence of parseSearch song-branch anchor (got {s.count(OLD_SONG)})"
s = s.replace(OLD_SONG, NEW_SONG, 1)

OLD_ARTISTSONGS = '''                        if "songs" in artistq:
                            if "results" in artistq["songs"]:
                                for song in artistq["songs"]["results"]:
                                    if song["videoId"] in self.TRACKS:
                                        tracks.add(self.TRACKS[song["videoId"]])
                                    else:
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
                                        if song["videoId"] not in self.TRACKS:
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
                    except Exception:'''

NEW_ARTISTSONGS = '''                        if "songs" in artistq:
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
                    except Exception:'''

assert s.count(OLD_ARTISTSONGS) == 1, (
    f"expected 1 occurrence of parseSearch artist->songs anchor (got {s.count(OLD_ARTISTSONGS)})"
)
s = s.replace(OLD_ARTISTSONGS, NEW_ARTISTSONGS, 1)

open(p, "w").write(s)
print(
    "patched library.py: playlistToTracks()/parseSearch() (song分岐・artist経由songs分岐) が"
    "getTrack()由来の簡易キャッシュを二度と上書きしない不具合を修正 (常に最新情報で再構築)"
)
