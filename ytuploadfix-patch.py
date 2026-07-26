# mopidy_ytmusic.library.uploadArtistToTracks()/uploadAlbumToTracks() (YouTube Music の
# 「Uploads」= ユーザー自身がアップロードした曲のライブラリブラウズ、library.py の
# browse()/lookup() が `upload` フラグ付き URI で実際に呼んでいる生きた経路) が、
# artists/album/year 等の付随メタデータが欠けているアップロード曲に対して未ガードの
# 添字アクセスをしており、Liked Songs (ytliked-patch.py) と同種の
# TypeError/KeyError/IndexError でクラッシュする不具合を発見。
#
# アップロード曲はユーザーが手元のファイルをそのまま上げたものであり、Liked Songs に
# 混ざるポッドキャスト等の非音楽アイテム以上に artists/album タグが欠落しやすい
# (ID3 タグ未設定の音源、シングルファイル等は album を持たない、アーティスト名が
# 空/不明なアップロードも珍しくない)。呼び出し元の browse()/lookup() は
# try/except Exception で囲んでいるため MPD セッション自体は落ちないが、例外発生時は
# 該当アーティスト/アルバムのブラウズ結果が丸ごと空になる (Liked Songs バグと同じ
# 実害のクラス)。
#
# uploadArtistToTracks(): `for a in track["artists"]:` (キー欠落/値Noneで例外) と
# `track["album"]["id"]` (album欠落曲で例外、playlistToTracks は既に
# `"album" in track and track["album"] is not None` でガード済みだがこちらは未対応)
# の2箇所を修正。
#
# uploadAlbumToTracks(): `album["artists"][0]["id"]` (artistsが空リスト/欠落でIndexError/
# KeyError) と `album["year"]`/`album["trackCount"]` (欠落でKeyError、trackCountは
# 既存コードも `str(...)` でラップしていたため欠落時のみ未対応) を修正。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD_ARTIST = '''    def uploadArtistToTracks(self, artist):
        ret = []
        for track in artist:
            artists = []
            for a in track["artists"]:
                if a["id"] not in self.ARTISTS:
                    self.ARTISTS[a["id"]] = Artist(
                        uri=f"ytmusic:artist:{a['id']}:upload",
                        name=a["name"],
                        sortname=a["name"],
                        musicbrainz_id="",
                    )
                artists.append(self.ARTISTS[a["id"]])
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
            self.TRACKS[track["videoId"]] = Track(
                uri=f"ytmusic:track:{track['videoId']}",
                name=track["title"],
                artists=artists,
                album=self.ALBUMS[track["album"]["id"]],
                composers=[],
                performers=[],
                genre="",
                track_no=None,
                disc_no=None,
                date="0000",
                length=None,
                bitrate=0,
                comment="",
                musicbrainz_id="",
                last_modified=None,
            )
            ret.append(self.TRACKS[track["videoId"]])
        return ret'''

NEW_ARTIST = '''    def uploadArtistToTracks(self, artist):
        ret = []
        for track in artist:
            artists = []
            for a in track.get("artists") or []:
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
                length=None,
                bitrate=0,
                comment="",
                musicbrainz_id="",
                last_modified=None,
            )
            ret.append(self.TRACKS[track["videoId"]])
        return ret'''

assert s.count(OLD_ARTIST) == 1, f"expected 1 occurrence of uploadArtistToTracks anchor (got {s.count(OLD_ARTIST)})"
s = s.replace(OLD_ARTIST, NEW_ARTIST, 1)

OLD_ALBUM = '''    def uploadAlbumToTracks(self, album, bId):
        ret = []
        # if album["artists"][0]["id"] not in self.ARTISTS:
        self.ARTISTS[album["artists"][0]["id"]] = Artist(
            uri=f"ytmusic:artist:{album['artists'][0]['id']}:upload",
            name=album["artists"][0]["name"],
            sortname=album["artists"][0]["name"],
            musicbrainz_id="",
        )
        artists = [self.ARTISTS[album["artists"][0]["id"]]]
        # if bId not in self.ALBUMS:
        self.ALBUMS[bId] = Album(
            uri=f"ytmusic:album:{bId}:upload",
            name=album["title"],
            artists=artists,
            num_tracks=int(album["trackCount"])
            if str(album["trackCount"]).isnumeric()
            else None,
            num_discs=None,
            date=f"{album['year']}",
            musicbrainz_id="",
        )
        if "tracks" in album:
            for track in album["tracks"]:
                # if track["videoId"] not in self.TRACKS:
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
                    date=f"{album['year']}",
                    length=None,
                    bitrate=0,
                    comment="",
                    musicbrainz_id="",
                    last_modified=None,
                )
                ret.append(self.TRACKS[track["videoId"]])
        return ret'''

NEW_ALBUM = '''    def uploadAlbumToTracks(self, album, bId):
        ret = []
        album_artists = album.get("artists") or []
        first_artist = album_artists[0] if album_artists else None
        if first_artist and first_artist.get("id"):
            # if first_artist["id"] not in self.ARTISTS:
            self.ARTISTS[first_artist["id"]] = Artist(
                uri=f"ytmusic:artist:{first_artist['id']}:upload",
                name=first_artist.get("name", ""),
                sortname=first_artist.get("name", ""),
                musicbrainz_id="",
            )
            artists = [self.ARTISTS[first_artist["id"]]]
        else:
            artists = []
        album_date = f"{album.get('year', '0000')}"
        # if bId not in self.ALBUMS:
        self.ALBUMS[bId] = Album(
            uri=f"ytmusic:album:{bId}:upload",
            name=album["title"],
            artists=artists,
            num_tracks=int(album["trackCount"])
            if str(album.get("trackCount")).isnumeric()
            else None,
            num_discs=None,
            date=album_date,
            musicbrainz_id="",
        )
        if "tracks" in album:
            for track in album["tracks"]:
                # if track["videoId"] not in self.TRACKS:
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
                    length=None,
                    bitrate=0,
                    comment="",
                    musicbrainz_id="",
                    last_modified=None,
                )
                ret.append(self.TRACKS[track["videoId"]])
        return ret'''

assert s.count(OLD_ALBUM) == 1, f"expected 1 occurrence of uploadAlbumToTracks anchor (got {s.count(OLD_ALBUM)})"
s = s.replace(OLD_ALBUM, NEW_ALBUM, 1)

open(p, "w").write(s)
print(
    "patched library.py: uploadArtistToTracks/uploadAlbumToTracks が artists/album/year 欠落の"
    "アップロード曲でクラッシュする不具合を修正 (ytliked-patch と同種)"
)
