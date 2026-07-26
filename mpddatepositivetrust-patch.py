# フィルタ式 `(Date == "YYYY")` を他タグと併用した複合条件
# (例: `find title "X" date "Y"`, `find artist "X" date "Y"`) が
# mopidy_ytmusic backend では常に実トラックを取りこぼす不具合。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが調査
# サブエージェントに委任し、music_db.py/library.py を突き合わせて
# 新規発見・追加した項目 (mpdgenrepositivetrust-patch.py/
# mpdtrackpositivetrust-patch.py と同根の「backendのベストエフォート
# 結果がローカル再検証で0件へ丸められる」バグを date について発見)。
#
# 経緯: mopidy_ytmusic の Track.date は albumToTracks()/
# uploadAlbumToTracks() (アルバムを実際にブラウズ/lookupした経路) 由来の
# Track にのみ実際のリリース年が入り、search() 経由 (parseSearch()) の
# Track や playlistToTracks()/uploadArtistToTracks() 由来の Track は
# 常に date="0000" 固定 (YouTube Music の検索/プレイリスト/アーティスト
# API レスポンス自体に曲単位の正確な年情報が無いため)。ytsearchdate-patch.py
# が search() に "date" 単独分岐 (any/genre と同じベストエフォートの
# テキスト検索) を追加済みだが、`_mpd_track_matches_positives()`
# (music_db.py) は date を通常フィールドとして扱い
# `_mpd_negative_field_values(track, "date")` (search結果のTrackでは
# 常に ["0000"] 相当) と比較するため、backend が実際に見つけた候補が
# ローカル再検証で無条件却下されてしまう。
#
# 実機確認 (dev mopidy 6601, ytmusic 実アカウント、修正前):
# `find album "THE BOOK 2" date "2021"` (albumブランチはalbumToTracks()
# 経由で実データを持つため正常) → 実トラック8曲がヒット、Date: 2021。
# 一方 `find title "怪物" date "2021"` → `OK` のみ (0件)。
# THE BOOK 2 収録の「怪物」が実際に Date 2021 であることは上記で確認済み
# なのに、title+date の組み合わせでは常に0件になっている。さらに
# `find artist "YOASOBI" date "2021"` → 実トラック0件、アルバム
# プレースホルダ2件のみ (再生不可能な擬似行だけが残る)。
#
# 修正範囲の判断: genre/track_no と全く同じ理由で、date を一律で
# ローカル再検証スキップ扱いにはできない。mopidy_ytmusic の search() は
# query dict に "date" キー以外 (any/track_name/albumartist/artist/
# album/genre/track_no/uri) が1つでも存在すると elif 連鎖で date 分岐へ
# 到達せず date を一切見ないまま検索するため、`find title "X" date "Y"`
# のような複合条件で「backendが実際には見ていないdate条件」を無条件
# 通過させると、AND のはずが title 単体条件へ静かに緩んでしまう新たな
# 不具合を生む。安全に信頼できるのは positives が date 単独 (=query dict
# が {"date": [...]} のみ、実際に backend の date 分岐が実行されたと
# 確定できる) の場合のみ。genre/track_no と同じ設計方針を踏襲し
# "date が唯一の肯定条件のときだけ" ローカル再検証をスキップする。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'field == "date" and len(positives) == 1'
if MARKER in s:
    print("date positive trust already present in music_db.py, skip")
else:
    anchor = (
        '        if field == "track_no" and len(positives) == 1:\n'
        "            continue  # track_no 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic の検索結果 Track は track_no=None 固定のため。\n"
        "            # 他フィールドと併用時はbackendがtrack_noを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        '        if field == "track_no" and len(positives) == 1:\n'
        "            continue  # track_no 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic の検索結果 Track は track_no=None 固定のため。\n"
        "            # 他フィールドと併用時はbackendがtrack_noを見ていないため対象外)\n"
        '        if field == "date" and len(positives) == 1:\n'
        "            continue  # date 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic のsearch()/playlist/artist経由のTrackはdate=\"0000\"固定のため。\n"
        "            # 他フィールドと併用時はbackendがdateを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print("patched music_db.py: sole date positive condition now trusts backend best-effort match")
