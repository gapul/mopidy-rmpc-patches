# mopidy_ytmusic.library.py の parseSearch() (resultType=="song"分岐) が、rmpc の既定検索
# (Tag::Any、MPD の `search any`/`find any` に対応) 経由で得た曲の Artist を丸ごと欠落させて
# しまう不具合。実データ(dev mopidy, ytmusic実アカウント)で `search any "yoasobi"`/`"Ado"`/
# `"Kenshi Yonezu"` を実際に送信して確認したところ、返る song 系レコード全件で Artist/
# AlbumArtist 行が完全に無い一方、同じ曲・同じ環境で `search title "Idol"`/`find artist
# "Ado"`(tag指定=filter="songs"/"artists"経由)は正しく Artist/Album を返す。
#
# 原因: `search any`/`find any` は ytmusicapi の `search(filter=None)` (「トップリザルト」
# 形状の応答) を経由するが、この形状の song エントリは実データで artists が
# `[{"name": "Song", "id": None}]` のような resultType 誤表記のダミーのみ、または空になる
# ケースが再現時点で恒常的に発生していた (ytartist-patch.py が既にこのダミー除外を実装
# 済みだが、除外した後の代替取得手段が無く、除外後 artists=[] のまま Track が作られる)。
# `filter="songs"` 経由の通常検索はこの誤表記自体が発生しない別の応答形状のため無関係。
#
# 実害: rmpc の検索ペインは既定タグが Any (Tag::Any) のため、通常の検索操作で返る曲の
# Artist/AlbumArtist 列が常に空白になる。加えて lookup() (stored_playlists.py 等の editing
# 系コマンドが経由) は self.TRACKS にヒットすればそれを最優先で返すため、一度でも
# search 経由で登録された曲は同一プロセスの残り寿命ずっと Artist 欠落のまま (getTrack() の
# api.get_song() フォールバックへは二度と到達しない)。
#
# 対策: 除外後 artists が空になった場合のみ、getTrack() (内部で api.get_song() を呼び
# videoDetails.author を返す、実データで動作確認済み) へフォールバックしその artists を
# 採用する。search結果自体にartistsが十分にあるケース(通常検索)は従来通り追加API呼び出し
# 無し。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "failed to backfill song artist via getTrack"
if MARKER in s:
    print("parseSearch() song-branch artist fallback already patched, skip")
else:
    OLD = '''                        artists.append(self.ARTISTS[a["id"]])
                    album = None
                    if result.get("album"):'''

    NEW = '''                        artists.append(self.ARTISTS[a["id"]])
                    if not artists:
                        try:
                            artists = self.getTrack(result["videoId"]).artists
                        except Exception:
                            logger.debug(
                                "YTMusic parseSearch: failed to backfill song artist via getTrack",
                                exc_info=True,
                            )
                    album = None
                    if result.get("album"):'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch song-branch artists-empty anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch()のsong分岐でsearch any/find any経由のArtist欠落を"
        "getTrack()(api.get_song())フォールバックで補完するよう修正"
    )
