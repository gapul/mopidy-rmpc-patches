# mopidy_ytmusic/library.py の parseSearch() (search()経由、"any"/genre/date/track_no/
# _META_SEARCH_FIELDS 等 filter=None で呼ぶ全ての検索パスが通る共通パーサ) の
# if/elif チェーンが resultType "song"/"video"/"episode"/"album"/"artist" の5種類しか
# 処理しておらず、ytmusicapi 1.12.0 の ALL_RESULT_TYPES に含まれる resultType "station"
# (再生シード曲付きのラジオ/ミックス局) を素通しし黙って捨てている不具合。
# ytsearchvideoresult-patch.py/ytsearchepisoderesult-patch.py が別のresultTypeに同種の穴を
# 見つけて直した時と全く同じパターン。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任・再検証を経て)新規発見。
#
# 実害確認: ytmusicapi/parsers/search.py の parse_search_result() は resultType "station"
# に対して136-138行目 `elif result_type == "station": search_result["videoId"] = nav(data,
# NAVIGATION_VIDEO_ID); search_result["playlistId"] = nav(data, NAVIGATION_PLAYLIST_ID)`
# で実在・再生可能な videoId(実watchEndpointのシード曲)を設定する(title/thumbnailsは
# 116-117行/209行の全resultType共通ロジックで付与)。つまりstationは即再生可能なTrackとして
# 扱えるデータ(実videoId)を持つが、mopidy_ytmusic/library.py の parseSearch() には
# resultType "station" 用の分岐が無く、if/elif チェーンをどれにも一致せず素通りし例外も
# 出さず黙って捨てられる(既存の try/except (1778行目付近) にも捕捉されない、resultTypeの
# 除外名リストに既に "station" という文字列自体は含まれていた(artist名誤表記フィルタ用)が、
# resultType自体の分岐は一度も実装されていなかった)。
# 対象: search()の filter=None (query["any"]) 経路 = rmpcのsearch any/find anyが実際に
# 発行する主要検索。station はfilterで個別指定できないため無フィルタ検索でのみ出現する。
#
# 対策: episode分岐 (ytsearchepisoderesult-patch.py) と同じ構造で station 分岐を追加するが、
# station の実データ構造は episode ともまた異なる点に注意して複製ではなく個別実装する:
#   - result["artists"] は station には存在しない(parse_search_result()の55行目
#     `if result_type in ["song", "video", "album"]:` にも175行目
#     `if result_type in ["song", "video", "episode"]:` にも station は含まれない)。
#     episodeの podcast名 のような代替の表示名情報も無いため、artists=[] のまま
#     (video/episode同様、空でもTrack自体は成立する)。
#   - result["duration"] も同じ理由で station には設定されない。_yt_track_length_ms() は
#     該当キーが無ければ0を返す既存の安全なフォールバックに任せる(video/episode分岐と
#     同じ関数を再利用するだけで新規のtry/except等は不要)。
#   - album は捏造データが無い以上 None のまま据え置く(episode分岐と同じ判断: stationを
#     アルバムの一種として扱う実データが無い)。
#   - result["playlistId"] (ラジオの継続queueを表す実際のプレイリストID) は今回は使わない
#     ―― stationのvideoIdはシード曲そのものの再生に使えば十分であり、playlistIdを
#     ytmusic:playlist:<id> 型のURIとしてbrowse対象に追加すると別の設計判断(ラジオを
#     ブラウズ可能なプレイリストとして扱うか)が必要になり1件のスコープを超えるため、
#     video/episode分岐と同じ「即再生可能な1曲のTrackとして拾う」最小修正に留める。
#   - date は不明なため、他の全箇所と同じ "0000" プレースホルダを使う。
#   - field=="track" によるタイトル完全一致フィルタは video/episode分岐同様に複製しない ―
#     station が field="track" 経由(filter="songs" の exact検索)で渡ってくることは無く
#     (filter="songs" はytmusicapi側でresultTypeをsongに絞る)、field は常にNoneのまま
#     呼ばれる経路(any/genre/date/track_no/meta-tag、いずれもfilter=None)でしか
#     station分岐に到達しないため。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif result["resultType"] == "station":'
if MARKER in s:
    print("library.py already patched (ytsearchstationresult), skip")
else:
    OLD = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

    NEW = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "station":
                    if result.get("videoId") is None:
                        continue
                    track_length_ms = _yt_track_length_ms(result)
                    self.TRACKS[result["videoId"]] = Track(
                        uri=f"ytmusic:track:{result['videoId']}",
                        name=result["title"],
                        artists=[],
                        album=None,
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
                    if result.get("thumbnails") and result["videoId"] not in self.IMAGES:
                        self.IMAGES[result["videoId"]] = [
                            Image(
                                uri=th["url"],
                                width=th.get("width"),
                                height=th.get("height"),
                            )
                            for th in result["thumbnails"]
                            if "url" in th
                        ][::-1]
                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

    assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch episode/album boundary anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() が resultType \"station\" を無視し検索結果から "
        "黙って落としていた不具合を修正。シード曲のvideoIdをTrackとして拾うよう追加"
    )
