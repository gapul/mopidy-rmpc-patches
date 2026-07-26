# mopidy_ytmusic.library.albumToTracks() (アルバムをブラウズ/検索/lookupで展開する
# 主経路、ytalbumfix-patch.py が既にクラッシュ系の不具合を修正済み) に残っていた
# 「静かなデータ破損」不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# 横断調査 (ytartistcache-patch.py等、他のTrack変換関数 playlistToTracks() の
# per-track artist組み立てロジックと比較) して新規発見・追加した項目。
#
# 実データでの発火条件と実害:
#   ytmusicapi 1.12.1 (mixins/browsing.py get_album, 実ソース確認済み) は
#   `album["tracks"][i]["artists"] = album["tracks"][i]["artists"] or album["artists"]`
#   により、各トラックの "artists" キーを常に (dictのリスト、例:
#   `[{"name": "Eminem", "id": "UC..."}]`) として設定する。すなわちアルバム経由の
#   全トラックで "artists" キーは常に存在し、常にlistであり、常にNoneにはならない。
#
#   ところが旧実装の分岐:
#     if ("artists" not in song or song["artists"] == artistname
#         or song["artists"] is None):
#         songartists = artists          # 曲固有アーティストはこの分岐に来ない
#     else:
#         songartists = [Artist(name=artistname)]   # 常にここに来る
#   は、`song["artists"]`(list) と `artistname`(str) を `==` 比較しており型が
#   異なるため恒常的に False、"artists" キーも常に存在しNoneにもならないため、
#   3条件は事実上全て成立せず**必ず else 分岐に落ちる**。結果として:
#   (1) 曲ごとの実際のアーティスト情報 (feat.曲の複数アーティストや、
#       オムニバス盤で曲毎にアーティストが異なるケース) が握り潰され、
#       常にアルバムの代表アーティスト名 (artistname) に一律で誤表示される。
#   (2) さらにこの `Artist(name=artistname)` はuri無しで毎回新規生成される
#       ため、本来 self.ARTISTS[artist['id']] 経由でuri (`ytmusic:artist:<id>`)
#       付きのアーティストが得られていたはずが、常にuri無しのアーティストに
#       化ける (アーティストページへのブラウズ導線が失われる)。
#   これはクラッシュではなく毎回発火する静的なメタデータ破損で、
#   playlistToTracks() (同ファイル、正しく song["artists"] を self.ARTISTS
#   キャッシュ付きで組み立てている) との非対称性からも実装漏れと判断できる。
#
# 修正: playlistToTracks() と同じ流儀 (a["id"] があれば self.ARTISTS へ
# uri付きでキャッシュ、無ければ Artist(name=a["name"]) を都度生成) で
# song["artists"] から songartists を正しく組み立て、曲側にアーティスト情報が
# 無い場合のみアルバムの artists へフォールバックする。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "# ytalbumtrackartist-patch: per-track artists"
if MARKER in s:
    print("library.py already patched (ytalbumtrackartist), skip")
else:
    OLD = '''                # if song["videoId"] not in self.TRACKS:
                song_length_ms = _yt_track_length_ms(song)
                # Annoying workaround for Various Artists
                if (
                    "artists" not in song
                    or song["artists"] == artistname
                    or song["artists"] is None
                ):
                    songartists = artists
                else:
                    songartists = [Artist(name=artistname)]'''

    NEW = '''                # if song["videoId"] not in self.TRACKS:
                song_length_ms = _yt_track_length_ms(song)
                # ytalbumtrackartist-patch: per-track artists
                # (playlistToTracks()と同じ組み立て。曲固有アーティストが
                # 無ければアルバムの artists へフォールバック)
                songartists = []
                if song.get("artists"):
                    for a in song["artists"]:
                        if not a.get("id"):
                            songartists.append(
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
                        songartists.append(self.ARTISTS[a["id"]])
                if not songartists:
                    songartists = artists'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of albumToTracks songartists anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: albumToTracks() が song['artists'](list) と "
        "artistname(str) を==比較する型不一致により常にelse分岐へ落ち、"
        "曲固有アーティスト情報とuriを毎回失っていた不具合を修正 "
        "(playlistToTracks()と同じper-track artist組み立てに統一)"
    )
