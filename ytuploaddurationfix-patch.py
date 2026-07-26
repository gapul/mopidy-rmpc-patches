# mopidy_ytmusic.library.py の uploadArtistToTracks()/uploadAlbumToTracks()、および
# parseSearch() の artist 分岐 (artistq["songs"]["results"] ループ、search filter="artists"
# 等でヒットしたアーティストのトップソングを取り込む経路) の計3箇所が、曲の長さを
# 一切パースせず `length=None` を決め打ちで Track に渡しており、Uploads (自分の
# アップロード曲) のアーティスト/アルバムブラウズ、および検索でヒットしたアーティストの
# トップソング一覧のいずれも Time/duration が常に 0 になる不具合を発見。
# TODO 全項目消化済みのため自走エージェントが rmpc 側の未実装コマンド調査 (新規ギャップ
# なしと確認済み) に続き、mopidy_ytmusic のコード品質を再調査して発見した項目。
# ytduration-patch.py が playlistToTracks()/albumToTracks()/parseSearch() (song 分岐) の
# 3箇所を H:MM:SS 対応の `_yt_track_length_ms()` ヘルパーに置き換え済みだが、この3箇所は
# 対象に入っておらず旧来のまま `length=None` だった。
#
# ytmusicapi 1.12.1 のソースを実際に確認したところ、この3箇所が受け取る track/song dict は
# いずれも "duration"/"duration_seconds" を実際に含みうると判明:
# - uploadArtistToTracks(): get_library_upload_artist() が内部で
#   parsers/uploads.py の parse_uploaded_items() を経由し、各曲に
#   "duration"/"duration_seconds" (fixedColumns から実際にパース、mixins/uploads.py の
#   get_library_upload_album() docstring 例でも "duration": "4:15",
#   "duration_seconds": 255 が実例として明記) を含む。
# - uploadAlbumToTracks(): get_library_upload_album() も同じ parse_uploaded_items() を
#   経由するため同様。
# - parseSearch() 内 artistq["songs"]["results"]: mixins/browsing.py get_artist() が
#   `artist["songs"]["results"] = parse_playlist_items(musicShelf["contents"])`
#   (parsers/playlists.py) で構築しており、playlistToTracks が受け取るのと同じ
#   parse_playlist_items() 経由のため duration truthy 時に "duration"/"duration_seconds"
#   を含む (parsers/playlists.py 299-301行)。
#
# いずれも length=None を決め打ちにする理由が無いにもかかわらず既に取得済みのデータを
# 一切使わず捨てており、静かに Time/duration が失われるバグ。対策: 既存の
# `_yt_track_length_ms()` ヘルパー (ytduration-patch.py で追加済み、H:MM:SS/秒優先/
# コロン無し文字列いずれも安全に処理) をこの3箇所でも呼び出し、length=None を置き換える。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "length=track_length_ms,\n                bitrate=0,\n                comment=\"\",\n                musicbrainz_id=\"\",\n                last_modified=None,\n            )\n            ret.append(self.TRACKS[track[\"videoId\"]])"
if MARKER in s:
    print("library.py already patched (upload/artist-songs duration), skip")
else:
    assert "def _yt_track_length_ms(track):" in s, (
        "_yt_track_length_ms helper not found - ytduration-patch.py must run first"
    )

    # (1) uploadArtistToTracks()
    OLD_ARTIST = '''            self.TRACKS[track["videoId"]] = Track(
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
            ret.append(self.TRACKS[track["videoId"]])'''
    NEW_ARTIST = '''            track_length_ms = _yt_track_length_ms(track)
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
            ret.append(self.TRACKS[track["videoId"]])'''
    assert s.count(OLD_ARTIST) == 1, (
        f"expected 1 occurrence of uploadArtistToTracks anchor (got {s.count(OLD_ARTIST)})"
    )
    s = s.replace(OLD_ARTIST, NEW_ARTIST, 1)

    # (2) uploadAlbumToTracks()
    OLD_ALBUM = '''                self.TRACKS[track["videoId"]] = Track(
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
                ret.append(self.TRACKS[track["videoId"]])'''
    NEW_ALBUM = '''                track_length_ms = _yt_track_length_ms(track)
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
                ret.append(self.TRACKS[track["videoId"]])'''
    assert s.count(OLD_ALBUM) == 1, (
        f"expected 1 occurrence of uploadAlbumToTracks anchor (got {s.count(OLD_ALBUM)})"
    )
    s = s.replace(OLD_ALBUM, NEW_ALBUM, 1)

    # (3) parseSearch() artist 分岐: artistq["songs"]["results"] ループ
    OLD_ARTISTSONGS = '''                                        if song["videoId"] not in self.TRACKS:
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
                                                length=None,
                                                bitrate=0,
                                                comment="",
                                                musicbrainz_id="",
                                                last_modified=None,
                                            )
                                        tracks.add(self.TRACKS[song["videoId"]])'''
    NEW_ARTISTSONGS = '''                                        if song["videoId"] not in self.TRACKS:
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
                                        tracks.add(self.TRACKS[song["videoId"]])'''
    assert s.count(OLD_ARTISTSONGS) == 1, (
        f"expected 1 occurrence of parseSearch artist-songs anchor (got {s.count(OLD_ARTISTSONGS)})"
    )
    s = s.replace(OLD_ARTISTSONGS, NEW_ARTISTSONGS, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: uploadArtistToTracks/uploadAlbumToTracks/parseSearch(artist分岐) の "
        "length=None決め打ちを _yt_track_length_ms() 経由の実長さへ修正"
    )
