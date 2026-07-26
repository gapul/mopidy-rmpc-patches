# mopidy_ytmusic/library.py の get_distinct() が field=="artist"/"albumartist"の分岐
# だけ query 引数を一切見ず、常にライブラリの全アーティストを返す不具合。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが調査・発見した項目。
#
# mopidy_mpd/protocol/music_db.py の list_() のdocstring (MPDプロトコル公式仕様の
# 引用) 自身が挙げる典型例 `list "artist" "artist" "ABBA"` は「artist名がABBAの
# ものだけ列挙し、Artist: ABBA / OK を返すべき」と明記している。実装は
# query={"artist": ["ABBA"]}を素通しして self.backend.api.get_library_artists()
# の全件をそのままretへ入れるため、この最も基本的な等値フィルタすら効かず
# ライブラリの全フォロー中アーティストが返る。album分岐(ytdistinctfilter-patch.py)/
# date分岐(ytdistinctdate-patch.py)は既にquery内のartist/albumartist/dateキーで
# 絞り込む実装になっており、artist/albumartist分岐だけ取り残されていた非対称。
#
# rmpc本体 (mierak/rmpc) の list コマンド呼び出しは全て list_tag()/list_tag_grouped()
# (rmpc-mpd) 経由であり、AddRandomModal (グローバルアクション「ランダム追加」) の
# Artist/AlbumArtistタブは list artist [query]/list albumartist [query] の応答を
# そのまま候補一覧として使う。query が無視されフィルタが効かないと、本来1件に
# 絞り込まれるべき応答が常にライブラリ全件になり、rmpc側での絞り込み前提の
# 処理(グループ化ブラウズの内側 subquery 等)が実質機能しない。
#
# 修正: album/date分岐と同じ流儀で、query の artist/albumartist キーの値を
# (アーティスト名自身の等値マッチとして) wanted_artists に集約し、
# ライブラリ側アーティスト名(小文字比較)がそこに含まれる場合のみ ret に加える
# (wanted_artists が空、すなわちフィルタ無し呼び出しの場合は従来通り全件)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "get_distinct(\"artist\"/\"albumartist\")もqueryで絞り込む"

OLD_ANCHOR = '''        if field == "artist" or field == "albumartist":
            # try:
            #     uploads = self.backend.api.get_library_upload_artists(limit=100)
            # except Exception:
            #     logger.exception("YTMusic failed getting uploaded artists")
            #     uploads = []
            #     pass
            try:
                library = self.backend.api.get_library_artists(limit=None)
            except Exception:
                logger.exception("YTMusic failed getting artists from library")
                library = []
                pass
            # for a in uploads:
            #     ret.add(a["artist"])
            for a in library:
                ret.add(a["artist"])'''

if MARKER in s:
    print("get_distinct() artist/albumartist query絞り込みは既に適用済み、skip")
else:
    NEW = '''        if field == "artist" or field == "albumartist":
            # get_distinct("artist"/"albumartist")もqueryで絞り込む
            # try:
            #     uploads = self.backend.api.get_library_upload_artists(limit=100)
            # except Exception:
            #     logger.exception("YTMusic failed getting uploaded artists")
            #     uploads = []
            #     pass
            try:
                library = self.backend.api.get_library_artists(limit=None)
            except Exception:
                logger.exception("YTMusic failed getting artists from library")
                library = []
                pass
            # for a in uploads:
            #     ret.add(a["artist"])
            wanted_artists = {
                v.lower()
                for k in ("artist", "albumartist")
                for v in (query or {}).get(k, [])
            }
            for a in library:
                if not a.get("artist"):
                    continue
                if wanted_artists and a["artist"].lower() not in wanted_artists:
                    continue
                ret.add(a["artist"])'''

    assert s.count(OLD_ANCHOR) == 1, (
        f"expected 1 occurrence of get_distinct artist/albumartist anchor (got {s.count(OLD_ANCHOR)})"
    )
    s = s.replace(OLD_ANCHOR, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: get_distinct(\"artist\"/\"albumartist\") が query の"
        "artist/albumartist キーで実際に絞り込むよう修正 (album/date分岐と同じ流儀に統一)"
    )
