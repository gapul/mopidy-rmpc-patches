# mopidy_ytmusic.library.py の playlistToTracks()/uploadArtistToTracks()/parseSearch() (song
# 分岐、および artist 経由 songs 分岐) は共通してこのパターンを使っている:
#   if X["album"]["id"] not in self.ALBUMS:
#       self.ALBUMS[X["album"]["id"]] = Album(...)
#   album = self.ALBUMS[X["album"]["id"]]
#
# ytmusicapi の parse_song_album() (ytmusicapi/parsers/songs.py) は album のテキスト run に
# navigationEndpoint (browseId) が無い場合 `{"name": <表示名>, "id": None}` を返す実装であり、
# これは実データで起こりうる (プレイリスト/Liked Songs/History内のリンク不可なアルバム表記を
# 持つ曲、シングル等)。ytartistcache-patch.py が self.ARTISTS について既に発見・修正した
# 「id=None を素のままキャッシュキーに使ってしまう」のと全く同じバグクラスが、兄弟キャッシュ
# self.ALBUMS の側には一切対応されないまま4箇所とも残っていた。
#
# 実害: self.ALBUMS はキー(id)でグローバルにキャッシュされる辞書のため、id=None のアルバムに
# 最初に遭遇したトラックの名前で self.ALBUMS[None] が一度だけ作られ、以後同じプロセス寿命の
# 間、id=None の別アルバム(実際には全く別の名前)を持つ全ての曲が誤って同じ Album オブジェクト
# (最初の曲のアルバム名のまま)を共有してしまう。クラッシュはしないが、rmpc の Album/AlbumUri
# 表示・グルーピングが無関係な別トラックのアルバム名で汚染される。プレイリスト・Liked Songs・
# History・検索結果をブラウズする通常経路全てで到達しうる。
#
# 対策: X["album"].get("id") が falsy な場合は self.ALBUMS へキャッシュせず、都度その場限りの
# (uri無し) Album を作る (ytartistcache-patch.py の self.ARTISTS への対策と同じ流儀)。

p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'if not track["album"].get("id"):'
if MARKER in s:
    print("library.py already patched (ytalbumidcache), skip")
else:
    # 1) playlistToTracks()
    OLD1 = '''                    if "album" in track and track["album"] is not None:
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
                        album = self.ALBUMS[track["album"]["id"]]'''
    NEW1 = '''                    if "album" in track and track["album"] is not None:
                        if not track["album"].get("id"):
                            album = Album(
                                uri="",
                                name=track["album"]["name"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date="0000",
                                musicbrainz_id="",
                            )
                        else:
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
                            album = self.ALBUMS[track["album"]["id"]]'''
    assert s.count(OLD1) == 1, f"expected 1 occurrence of playlistToTracks album-cache anchor (got {s.count(OLD1)})"
    s = s.replace(OLD1, NEW1, 1)

    # 2) uploadArtistToTracks()
    OLD2 = '''                if track.get("album"):
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
                    album = self.ALBUMS[track["album"]["id"]]'''
    NEW2 = '''                if track.get("album"):
                    if not track["album"].get("id"):
                        album = Album(
                            uri="",
                            name=track["album"]["name"],
                            artists=artists,
                            num_tracks=None,
                            num_discs=None,
                            date="0000",
                            musicbrainz_id="",
                        )
                    else:
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
                        album = self.ALBUMS[track["album"]["id"]]'''
    assert s.count(OLD2) == 1, f"expected 1 occurrence of uploadArtistToTracks album-cache anchor (got {s.count(OLD2)})"
    s = s.replace(OLD2, NEW2, 1)

    # 3) parseSearch() song分岐 (ytsongalbumcache-patch.py 適用後のテキストが前提)
    OLD3 = '''                    album = None
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
                    self.TRACKS[result["videoId"]] = Track('''
    NEW3 = '''                    album = None
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
                    self.TRACKS[result["videoId"]] = Track('''
    assert s.count(OLD3) == 1, f"expected 1 occurrence of parseSearch song-branch album-cache anchor (got {s.count(OLD3)})"
    s = s.replace(OLD3, NEW3, 1)

    # 4) parseSearch() artist経由songs分岐
    OLD4 = '''                                        album = None
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
                                            album = self.ALBUMS[song["album"]["id"]]'''
    NEW4 = '''                                        album = None
                                        if "album" in song:
                                            if not song["album"].get("id"):
                                                album = Album(
                                                    uri="",
                                                    name=song["album"]["name"],
                                                    artists=[
                                                        self.ARTISTS[
                                                            result["browseId"]
                                                        ]
                                                    ],
                                                    date="0000",
                                                    musicbrainz_id="",
                                                )
                                            else:
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
                                                album = self.ALBUMS[song["album"]["id"]]'''
    assert s.count(OLD4) == 1, f"expected 1 occurrence of parseSearch artist->songs album-cache anchor (got {s.count(OLD4)})"
    s = s.replace(OLD4, NEW4, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: id=Noneの非リンクアルバムがself.ALBUMSキャッシュを汚染し"
        "無関係な別トラックのアルバム名を共有してしまう不具合を修正 "
        "(playlistToTracks/uploadArtistToTracks/parseSearch song・artist経由songsの4箇所)"
    )
