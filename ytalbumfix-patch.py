# mopidy_ytmusic.library.albumToTracks() (通常の—アップロードでない—アルバムを
# ブラウズ/検索結果から展開する経路。browse()/lookup()/search() の計4箇所から
# 呼ばれる、Uploads (:upload) より遥かに高頻度で通る主経路) に、未ガードの
# 添字アクセスによる TypeError/KeyError クラッシュを発見。ytuploadfix-patch.py が
# 同種のバグを uploadArtistToTracks/uploadAlbumToTracks (Uploads経路) で修正済みだが、
# 主経路である albumToTracks 自体は未対応のまま残っていた。
#
# ytmusicapi 1.12.1 (mixins/browsing.py get_album -> parsers/albums.py
# parse_album_header_2024) を実際にソース確認し、以下2点が実データで起こりうる
# ことを確認した:
#
# (1) `album["artists"]`: parse_album_header_2024 は常にこのキーを設定するが、
#     `strapline_runs` (アーティスト名表示欄) が無いアルバム (例: strapline を
#     持たない一部のシングル/リリース) では `album["artists"] = None` を
#     明示的にセットする (parsers/albums.py: `album_info["artists"] =
#     parse_artists_runs(strapline_runs) if strapline_runs else None`)。
#     旧実装は `if "artists" in album:` (キー存在のみ確認、値がNoneでも真) の後
#     `artist = album["artists"]` (Noneのまま) → `artist["id"]` で
#     `TypeError: 'NoneType' object is not subscriptable`。
#
# (2) `album["trackCount"]`: parse_album_header_2024 は
#     `secondSubtitle.runs` が1件以下 (トラック数表示欄が無く再生時間のみの
#     アルバムページ) の場合、`trackCount` キー自体を一切セットしない。
#     旧実装は `str(album["trackCount"]).isnumeric()` で直接添字アクセスして
#     おり、キー欠落時に `KeyError: 'trackCount'` でクラッシュする。
#
# 呼び出し元の browse()/lookup()/search() は try/except Exception で囲んでいる
# ため MPD セッション自体は落ちないが、例外発生時は該当アルバムのブラウズ結果/
# 検索結果への反映が丸ごと欠落する (ytliked-patch.py/ytuploadfix-patch.py と
# 同じ実害のクラス)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "artist = album_artists[0] if type(album_artists) is list else album_artists"
if MARKER in s:
    print("library.py already patched (albumToTracks), skip")
else:
    OLD = '''        artists = []
        artistname = ""
        if "artists" in album:
            if type(album["artists"]) is list:
                artist = album["artists"][0]
            else:
                artist = album["artists"]
            # if artist["id"] not in self.ARTISTS:
            self.ARTISTS[artist["id"]] = Artist(
                uri=f"ytmusic:artist:{artist['id']}",
                name=artist["name"],
                sortname=artist["name"],
                musicbrainz_id="",
            )
            artists.append(self.ARTISTS[artist["id"]])
            artistname = artist["name"]
        # if bId not in self.ALBUMS:
        self.ALBUMS[bId] = Album(
            uri=f"ytmusic:album:{bId}",
            name=album["title"],
            artists=artists,
            num_tracks=int(album["trackCount"])
            if str(album["trackCount"]).isnumeric()
            else None,
            num_discs=None,
            date=date,
            musicbrainz_id="",
        )'''

    NEW = '''        artists = []
        artistname = ""
        album_artists = album.get("artists")
        if album_artists:
            artist = album_artists[0] if type(album_artists) is list else album_artists
            if artist.get("id"):
                # if artist["id"] not in self.ARTISTS:
                self.ARTISTS[artist["id"]] = Artist(
                    uri=f"ytmusic:artist:{artist['id']}",
                    name=artist.get("name", ""),
                    sortname=artist.get("name", ""),
                    musicbrainz_id="",
                )
                artists.append(self.ARTISTS[artist["id"]])
                artistname = artist.get("name", "")
        # if bId not in self.ALBUMS:
        self.ALBUMS[bId] = Album(
            uri=f"ytmusic:album:{bId}",
            name=album["title"],
            artists=artists,
            num_tracks=int(album["trackCount"])
            if str(album.get("trackCount")).isnumeric()
            else None,
            num_discs=None,
            date=date,
            musicbrainz_id="",
        )'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of albumToTracks anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: albumToTracks が artists=None/trackCount欠落の"
        "アルバムでクラッシュする不具合を修正 (ytuploadfix-patch と同種、主経路)"
    )
