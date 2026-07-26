# mopidy_ytmusic/library.py の parseSearch() (search()経由、"any"/genre/date/track_no/
# _META_SEARCH_FIELDS 等 filter=None で呼ぶ全ての検索パスが通る共通パーサ) の
# if/elif チェーンが resultType "song"/"video"/"album"/"artist" の4種類しか処理しておらず、
# ytmusicapi 1.12.0 の ALL_RESULT_TYPES に含まれる resultType "episode" (ポッドキャストの
# 個別エピソード) を素通しし黙って捨てている不具合。ytsearchvideoresult-patch.py が
# "video" 分岐を追加した時と全く同じ穴が別の resultType にも存在していた。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実害確認: ytmusicapi/parsers/search.py の parse_search_result() は resultType "episode"
# に対して "song"/"video" と同じ経路(175行目 `if result_type in ["song", "video",
# "episode"]:`)で実在・再生可能な videoId を設定する(199行目以降で date/podcast情報も
# 付与)。つまりエピソードは即再生可能なTrackとして扱えるデータを持つが、
# mopidy_ytmusic/library.py の parseSearch() には resultType "episode" 用の分岐が無く、
# if/elif チェーンをどれにも一致せず素通りし例外も出さず黙って捨てられる(既存の
# try/except (1652行目付近) にも捕捉されない)。実機確認(dev mopidy、実ytmusicアカウント、
# TCP 6601): ytmusicapi.search(filter=None) 直接呼び出しで実在エピソード
# (videoType="MUSIC_VIDEO_TYPE_PODCAST_EPISODE"、実videoId付き)がヒットする検索語
# ("NHKラジオ ニュース")で `search any "NHKラジオ ニュース"` を送ると `OK` (file: 行0件)
# となり、直接APIでは見えているエピソードがMPD経由では一切発見できないことを確認。
#
# 対策: video分岐 (ytsearchvideoresult-patch.py) と同じ構造で episode 分岐を追加するが、
# episode の実データ構造は song/video とは異なる点に注意して複製ではなく個別実装する:
#   - result["artists"] は episode には存在しない(parse_search_result()が
#     resultType=="episode"の場合に設定するのは title/videoId/videoType/live/date/podcast/
#     thumbnailsのみ、artistsは無い)。代わりに result["podcast"] = {"id","name"}
#     (parse_id_name()が返す、番組の browseId+表示名) があるので、番組名を
#     アーティスト欄相当の表示テキストとして使う。ただし podcast の browseId
#     (MPSPプレフィックス) は mopidy_ytmusic の ytmusic:artist: 名前空間が期待する
#     アーティストIDではない(実際はポッドキャスト番組のID)ため、self.ARTISTSキャッシュに
#     ytmusic:artist:<podcastId> という誤った型のURIで登録すると、rmpc側でその
#     アーティスト名をクリックしてブラウズした際に不正なbrowse結果になる実害がある
#     (home-patch.py が同じ理由でポッドキャスト番組を素通しせず除外しているのと同種の
#     配慮)。そのため uri無し・id無しの名前だけのArtistとして追加し、クリック不可能な
#     ただのテキスト表示に留める(既存コードが artist id 不明時に行っている
#     `Artist(name=..., sortname=..., musicbrainz_id="")` パターンと同じ)。
#   - album も同様の理由(podcast番組をalbum型URIとしてキャッシュすると誤ったbrowseに
#     繋がる)で None のまま据え置く。エピソードをアルバムの一種として扱う実データが
#     無い以上、捏造よりは album=None の方が安全。
#   - result["duration"]/["duration_seconds"] は episode には設定されない
#     (parse_search_result()の "song"/"video"/"album" 用ブロックのみが対象)ため、
#     _yt_track_length_ms() は該当キーが無ければ0を返す既存の安全なフォールバックに任せる
#     (video分岐と同じ関数を再利用するだけで新規のtry/except等は不要)。
#   - date は実際の値(例 "Apr 4, 2025")を保持しているが、Trackのdateフィールドは
#     このコードベースの他の全箇所で不明時は "0000" プレースホルダを使う一貫した
#     慣習になっている(video分岐もこれに従う)ため、新たなフォーマット処理を増やさず
#     同じ "0000" を使う。
#   - field=="track" によるタイトル完全一致フィルタは video分岐同様に複製しない —
#     episode が field="track" 経由(filter="songs" の exact検索)で渡ってくることは無く
#     (filter="songs" はytmusicapi側でresultTypeをsongに絞る)、field は常にNoneのまま
#     呼ばれる経路(any/genre/date/track_no/meta-tag、いずれもfilter=None)でしか
#     episode分岐に到達しないため。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif result["resultType"] == "episode":'
if MARKER in s:
    print("library.py already patched (ytsearchepisoderesult), skip")
else:
    OLD = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "album":'''

    NEW = '''                    tracks.add(self.TRACKS[result["videoId"]])
                elif result["resultType"] == "episode":
                    if result.get("videoId") is None:
                        continue
                    track_length_ms = _yt_track_length_ms(result)
                    artists = []
                    podcast = result.get("podcast") or {}
                    if podcast.get("name"):
                        artists.append(
                            Artist(
                                name=podcast["name"],
                                sortname=podcast["name"],
                                musicbrainz_id="",
                            )
                        )
                    self.TRACKS[result["videoId"]] = Track(
                        uri=f"ytmusic:track:{result['videoId']}",
                        name=result["title"],
                        artists=artists,
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

    assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch video/album boundary anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() が resultType \"episode\" を無視し検索結果から "
        "黙って落としていた不具合を修正。番組名を名前のみのArtistとして使いTrackとして拾うよう追加"
    )
