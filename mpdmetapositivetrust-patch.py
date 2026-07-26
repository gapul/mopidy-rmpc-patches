# フィルタ式 `(Composer == "X")`/`(Performer == "X")`/`(Comment == "X")`/
# `(Disc == "N")`/`(MUSICBRAINZ_TRACKID == "X")`/`(MUSICBRAINZ_ALBUMID == "X")`/
# `(MUSICBRAINZ_ARTISTID == "X")` (単独条件) が mopidy_ytmusic backend では
# 常に0件になる不具合。TODO/既知の軽微な残課題を全項目消化済みのため自走
# エージェントが調査サブエージェントに委任し、mpdgenrepositivetrust-patch.py/
# mpdtrackpositivetrust-patch.py/mpddatepositivetrust-patch.pyと同根の
# 「backendのベストエフォート結果がローカル再検証で0件へ丸められる」バグを
# 残り7フィールドについて発見。
#
# 経緯: mopidy_ytmusic の Track は composers/performers/comment/disc_no/
# musicbrainz_id を(search()/album/playlist/artist経由いずれの構築箇所でも)
# 常に composers=[]/performers=[]/comment=""/disc_no=None/musicbrainz_id=""
# 固定で返す(YouTube Music APIにこれらの概念自体が無いため)。一方
# ytsearchmetatag-patch.py が search() に追加した _META_SEARCH_FIELDS
# ("composer"/"performer"/"comment"/"disc_no"/"musicbrainz_albumid"/
# "musicbrainz_artistid"/"musicbrainz_trackid") 単独分岐は any/genre と
# 同じベストエフォートのテキスト検索を行い実トラックを返す。しかし
# `_mpd_track_matches_positives()` (music_db.py) はこれらを通常フィールド
# として扱い `_mpd_negative_field_values()` (常に空リスト) と比較するため、
# backend が実際に見つけた候補がローカル再検証で無条件却下されてしまう。
#
# 実機確認 (dev mopidy 6601, ytmusic 実アカウント、修正前):
# `find composer "yoasobi"` → 実トラック2件 (オリオン/夜に駆ける) がヒット。
# `find "(Composer == \"yoasobi\")"` → `OK` のみ (0件、同じ条件なのに矛盾)。
# `find "(Performer == \"yoasobi\")"` → `OK` のみ (0件)。
# `search "(Composer == \"yoasobi\")"` → `OK` のみ (0件)。
# `count "(Composer == \"yoasobi\")"` → `songs: 0`。
#
# 修正範囲の判断: genre/track_no/date と全く同じ理由で、これら7フィールドも
# 一律でローカル再検証スキップ扱いにはできない。mopidy_ytmusic の search()
# は query dict に他のキーが1つでも存在すると elif 連鎖でこれらの分岐へ
# 到達せず該当フィールドを一切見ないまま検索するため、他タグと併用した
# 複合条件で「backendが実際には見ていない条件」を無条件通過させると AND の
# はずが緩んでしまう新たな不具合を生む。安全に信頼できるのは positives が
# 該当フィールド単独 (backendの該当分岐が実際に実行されたと確定できる)
# の場合のみ。genre/track_no/date と同じ設計方針を踏襲する。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'field == "composer" and len(positives) == 1'
if MARKER in s:
    print("composer/performer/comment/disc_no/musicbrainz_* positive trust already present in music_db.py, skip")
else:
    anchor = (
        '        if field == "date" and len(positives) == 1:\n'
        "            continue  # date 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic のsearch()/playlist/artist経由のTrackはdate=\"0000\"固定のため。\n"
        "            # 他フィールドと併用時はbackendがdateを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    meta_fields = (
        "composer",
        "performer",
        "comment",
        "disc_no",
        "musicbrainz_trackid",
        "musicbrainz_albumid",
        "musicbrainz_artistid",
    )
    meta_branches = "".join(
        f'        if field == "{field}" and len(positives) == 1:\n'
        f"            continue  # {field} 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic の Track は composers/performers/comment/disc_no/\n"
        "            # musicbrainz_id を常に空固定で返すため。他フィールドと併用時は\n"
        "            # backendが該当フィールドを見ていないため対象外)\n"
        for field in meta_fields
    )
    replacement = (
        '        if field == "date" and len(positives) == 1:\n'
        "            continue  # date 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic のsearch()/playlist/artist経由のTrackはdate=\"0000\"固定のため。\n"
        "            # 他フィールドと併用時はbackendがdateを見ていないため対象外)\n"
        f"{meta_branches}"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: sole composer/performer/comment/disc_no/musicbrainz_* "
        "positive condition now trusts backend best-effort match"
    )
