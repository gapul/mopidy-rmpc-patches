# mopidy_ytmusic.library.py の uploadAlbumToTracks() (YouTube Music の
# 「Uploads」= 自分でアップロードした楽曲をアルバム単位でブラウズする際に呼ばれる) が、
# アルバム内の全トラックの track_no を無条件で None にしており、find/search/lsinfo/
# playlistinfo/currentsong いずれの MPD 応答でも Uploads 経由のアルバムだけ Track タグ
# (mopidy_mpd/translator.py track_to_mpd_format() は track.track_no is not None の
# ときのみ Track 行を出力) が常に欠落する不具合を発見。TODO 全項目消化済みのため
# 自走エージェントが再調査して発見した項目。
#
# 構造的に全く同一の処理を行う姉妹関数 albumToTracks() (通常のライブラリ登録アルバム用)
# は `for index, song in enumerate(album["tracks"], start=1):` で列挙し
# `track_no=index` を正しく設定している。ytmusicapi の get_library_upload_album()
# (mixins/uploads.py) も get_album() と同じく parse_uploaded_items() 経由でアルバム
# ページの表示順そのままのリストを返すため「リスト順=トラック順」という前提は同じで
# あり、albumToTracks() と同じ enumerate 手法がそのまま使えるにもかかわらず
# uploadAlbumToTracks() だけ実装が漏れていた。
#
# ytuploaddurationfix-patch.py が同じ関数の length=None 決め打ちを修正済み
# (track_length_ms 変数を導入済み) なので、そのパッチ適用後のソースを前提にアンカーを
# 取る。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'track_no=index,\n                        disc_no=None,\n                        date=album_date,'
if MARKER in s:
    print("library.py already patched (uploadAlbumToTracks track_no), skip")
else:
    OLD = '''        if "tracks" in album:
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
                    ret.append(self.TRACKS[track["videoId"]])'''
    NEW = '''        if "tracks" in album:
            for index, track in enumerate(album["tracks"], start=1):
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
                        track_no=index,
                        disc_no=None,
                        date=album_date,
                        length=track_length_ms,
                        bitrate=0,
                        comment="",
                        musicbrainz_id="",
                        last_modified=None,
                    )
                    ret.append(self.TRACKS[track["videoId"]])'''
    assert s.count(OLD) == 1, (
        f"expected 1 occurrence of uploadAlbumToTracks anchor (got {s.count(OLD)})"
    )
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: uploadAlbumToTracks() の track_no=None決め打ちを "
        "enumerate(start=1) 経由の実トラック番号へ修正"
    )
