# mopidy_listenbrainz/frontend.py の ListenbrainzFrontend._collect_playlist_tracks()
# が MusicBrainz本家APIから曲情報を補完するフォールバック検索で常にKeyErrorを送出し
# actorをクラッシュさせる不具合。
#
# musicbrainzngs.get_recording_by_id(track_mbid, includes=["artists"]) の
# includes=["artists"] は recording の artist-relation (作曲者/演奏者クレジット等の
# 関係グラフ) を追加する include であり、"artist-credit-phrase"/"artist-credit" を
# レスポンスに含めるのに必要なのは別の include である "artist-credits" (末尾s、複数形が
# 異なる) である (musicbrainzngs/musicbrainz.py の VALID_INCLUDES["recording"] は
# "artists" と "artist-credits" を別々の要素として列挙、mbxml.py の parse_recording()
# は "artist-credit" が結果に含まれる場合のみ if "artist-credit" in result: の分岐で
# "artist-credit-phrase" を合成する)。実際の MusicBrainz Web Service の recording
# lookup も inc=artist-credits を明示しない限りレスポンスに artist-credit を含めない
# (デフォルトでは付与されない)。
#
# そのため lbmbidguard-patch.py 適用後 (get_recording_by_id() 自体はネットワーク層
# エラーからガード済み) でも、200応答が返り mb_recording_query["recording"] が存在する
# 正常系では mb_recording に "artist-credit-phrase" キーが実質常に欠落しており、
# 直後の mb_recording["artist-credit-phrase"] (素の dict インデックスアクセス) が
# 無条件で KeyError を送出する。この KeyError は import_playlists() まで未捕捉のまま
# 伝播し、lbmbidguard-patch.py/lbplaylistguard-patch.py 等が既に修正した他の箇所と
# 全く同じ実害 (on_start() 経由なら actor が起動直後にクラッシュしListenBrainz連携
# 全体がプロセス生涯にわたり無効化、週次再インポートのTimer経由ならimport_playlists()
# が中断し末尾のself._schedule_playlists_import()に到達せず次回の再インポートが
# 二度とスケジュールされなくなる) を招く。ローカルライブラリ検索(self.library.search)
# で見つからない曲を1件でもMusicBrainz補完しようとするたび (found_tracks が空の
# track_mbidごと) に必ず踏む経路のため、lbmbidguard-patch.py が守ったネットワーク層
# エラーより高頻度 (実質確実) に発生する。
#
# 修正: includes を正しい "artist-credits" へ変更する。加えて mb_recording_query["recording"]/
# mb_recording["artist-credit-phrase"]/mb_recording["title"] の素インデックスアクセスを
# .get() ベースへ変更し、万一 MusicBrainz 側のレスポンス形状が想定と異なっても
# (release無しrecording等) KeyErrorで再度クラッシュしないよう防御する。artist_name/
# track_name のいずれかが得られない場合はフォールバック検索自体をスキップし
# (呼び出し元の found_tracks 判定へそのまま合流、その1曲だけがimport対象から漏れる)、
# import_playlists() 全体は正常終了まで到達する。
p = "mopidy_listenbrainz/frontend.py"
s = open(p).read()

anchor = (
    "                try:\n"
    "                    mb_recording_query = musicbrainzngs.get_recording_by_id(\n"
    "                        track_mbid, includes=[\"artists\"]\n"
    "                    )\n"
    "                except musicbrainzngs.WebServiceError:\n"
    "                    mb_recording_query = None\n"
    "                if mb_recording_query and mb_recording_query[\"recording\"]:\n"
    "                    mb_recording = mb_recording_query[\"recording\"]\n"
    "\n"
    "                    # try again with album artist name and track title\n"
    "                    artist_name = mb_recording[\"artist-credit-phrase\"]\n"
    "                    track_name = mb_recording[\"title\"]\n"
    "                    query = self.library.search(\n"
    "                        {\n"
    "                            # very few backends support artist+track name queries,\n"
    "                            # so we use a keyword search, although it will be less precise\n"
    "                            \"any\": [artist_name, track_name]\n"
    "                        },\n"
    "                        uris=search_schemes_fallback,\n"
    "                    )\n"
    "                    results = query.get()\n"
)

if anchor not in s:
    if 'includes=["artist-credits"]' in s:
        print("_collect_playlist_tracks() already patched, skip")
    else:
        raise AssertionError("anchor not found: unexpected frontend.py content")
else:
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        "                try:\n"
        "                    mb_recording_query = musicbrainzngs.get_recording_by_id(\n"
        "                        track_mbid, includes=[\"artist-credits\"]\n"
        "                    )\n"
        "                except musicbrainzngs.WebServiceError:\n"
        "                    mb_recording_query = None\n"
        "                mb_recording = (\n"
        "                    mb_recording_query.get(\"recording\")\n"
        "                    if mb_recording_query\n"
        "                    else None\n"
        "                )\n"
        "                # try again with album artist name and track title\n"
        "                artist_name = (\n"
        "                    mb_recording.get(\"artist-credit-phrase\") if mb_recording else None\n"
        "                )\n"
        "                track_name = mb_recording.get(\"title\") if mb_recording else None\n"
        "                if artist_name and track_name:\n"
        "                    query = self.library.search(\n"
        "                        {\n"
        "                            # very few backends support artist+track name queries,\n"
        "                            # so we use a keyword search, although it will be less precise\n"
        "                            \"any\": [artist_name, track_name]\n"
        "                        },\n"
        "                        uris=search_schemes_fallback,\n"
        "                    )\n"
        "                    results = query.get()\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print(
        "patched frontend.py: _collect_playlist_tracks() の MusicBrainz "
        "get_recording_by_id() の includes を artist-credits へ修正し、"
        "recording/artist-credit-phrase/title の素インデックスアクセスを .get() 化"
    )
