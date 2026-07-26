# mopidy_ytmusic.library.py の playlistToTracks()/uploadArtistToTracks()/parseSearch() (song/
# album 分岐) は共通してこのパターンを使っている:
#   for a in track["artists"]:
#       if a["id"] not in self.ARTISTS:
#           self.ARTISTS[a["id"]] = Artist(...)
#       artists.append(self.ARTISTS[a["id"]])
#
# ytmusicapi の parse_artists_runs() (ytmusicapi/parsers/artists.py) は各アーティスト run に
# navigationEndpoint (browseId) が無い場合 `{"name": <表示名>, "id": None}` を返す実装であり、
# これは実データで起こりうる (例: "Various Artists" のようなクリック不可のアーティスト
# クレジット表記を持つコンピレーション曲)。ytartist-patch.py は id=None のうち名前が
# "Song"/"Album" 等の resultType 誤爆表記と一致するものだけを除外したが、正当な名前を持つ
# id=None のケースは4箇所とも未対応のまま残っていた。
#
# 実害: self.ARTISTS はキー(id)でグローバルにキャッシュされる辞書のため、id=None のアーティストに
# 最初に遭遇したトラックの名前で self.ARTISTS[None] が一度だけ作られ、以後同じセッション内で
# id=None の別アーティスト(実際には全く別の名前)を持つ全ての曲が誤って同じ Artist オブジェクト
# (最初の曲の名前のまま)を共有してしまう。クラッシュはしないが、rmpc の Artist/AlbumArtist
# 表示が無関係な別トラックのアーティスト名で汚染される (ytliked-patch.py/ytuploadfix-patch.py/
# ytalbumfix-patch.py が発見したのと同種の「ytmusicapi が返しうる欠落値を未ガードで扱う」クラスの
# バグだが、こちらはクラッシュではなく静かなデータ汚染)。lsinfo/search/add 等、プレイリスト・
# 検索結果をブラウズする通常経路全てで到達しうる。
#
# 対策: a.get("id") が falsy な場合は self.ARTISTS へキャッシュせず、都度その場限りの
# (uri無し) Artist を作る (albumToTracks の artist.get("id") ガードと同じ流儀)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'if not a.get("id"):'
if MARKER in s:
    print("library.py already patched (ytartistcache), skip")
else:
    # 1) playlistToTracks()
    OLD1 = '''                    for a in track["artists"]:
                        if a["id"] not in self.ARTISTS:
                            self.ARTISTS[a["id"]] = Artist(
                                uri=f"ytmusic:artist:{a['id']}",
                                name=a["name"],
                                sortname=a["name"],
                                musicbrainz_id="",
                            )
                        artists.append(self.ARTISTS[a["id"]])'''
    NEW1 = '''                    for a in track["artists"]:
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
                        artists.append(self.ARTISTS[a["id"]])'''
    assert s.count(OLD1) == 1, f"expected 1 occurrence of playlistToTracks anchor (got {s.count(OLD1)})"
    s = s.replace(OLD1, NEW1, 1)

    # 2) uploadArtistToTracks()
    OLD2 = '''            for a in track.get("artists") or []:
                if a["id"] not in self.ARTISTS:
                    self.ARTISTS[a["id"]] = Artist(
                        uri=f"ytmusic:artist:{a['id']}:upload",
                        name=a["name"],
                        sortname=a["name"],
                        musicbrainz_id="",
                    )
                artists.append(self.ARTISTS[a["id"]])'''
    NEW2 = '''            for a in track.get("artists") or []:
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
                artists.append(self.ARTISTS[a["id"]])'''
    assert s.count(OLD2) == 1, f"expected 1 occurrence of uploadArtistToTracks anchor (got {s.count(OLD2)})"
    s = s.replace(OLD2, NEW2, 1)

    # 3&4) parseSearch() の song/album 両分岐 (ytartist-patch.py 適用後は同一テキストが2箇所)
    OLD3 = '''                            for a in result["artists"]:
                                if a.get("id") is None and (a.get("name") or "").strip().lower() in {
                                    "song", "video", "album", "single", "ep",
                                    "episode", "podcast", "station", "playlist", "profile",
                                }:
                                    continue
                                if a["id"] not in self.ARTISTS:'''
    NEW3 = '''                            for a in result["artists"]:
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
                                if a["id"] not in self.ARTISTS:'''
    assert s.count(OLD3) == 2, f"expected 2 occurrences of parseSearch anchor (got {s.count(OLD3)})"
    s = s.replace(OLD3, NEW3)

    open(p, "w").write(s)
    print(
        "patched library.py: id=None の非リンクアーティスト(Various Artists等)が"
        "self.ARTISTS[None]を汚染し無関係な別トラックのアーティスト名を共有してしまう"
        "不具合を修正 (playlistToTracks/uploadArtistToTracks/parseSearch song・album の4箇所)"
    )
