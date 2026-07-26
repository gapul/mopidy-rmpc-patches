# フィルタ式 `(Track == "N")` (単独条件) が mopidy_ytmusic backend では
# 常に0件になる不具合。TODO/既知の軽微な残課題を全項目消化済みのため
# 自走エージェントが調査サブエージェントに委任し、music_db.py/library.py を
# 突き合わせて新規発見・追加した項目 (mpdgenrepositivetrust-patch.py が
# genre で対処した「backendのベストエフォート結果がローカル再検証で0件へ
# 丸められる」のと同種のバグを track (内部フィールド名 track_no) について
# 発見)。
#
# 経緯: ytsearchtrack-patch.py が search() の "track_no" 分岐 (query に
# "track_no" キーのみが立っている場合) に、any/genre/date 分岐と同じ
# ベストエフォートのテキスト検索 (self.backend.api.search(term,
# filter=None) -> self.parseSearch(res)) を実装済み。ところが
# parseSearch() が生成する Track は track_no を一切設定せず常に None
# 固定 (track_no に実データが入るのは albumToTracks() 経由でアルバムを
# ブラウズ/lookupした場合のみ)。
#
# `_mpd_track_matches_positives()` (music_db.py) は演算子の種類に関わらず
# 全ての肯定条件を無条件で positives へ積む実装のため、backend から返った
# best-effort な検索結果 (track_no=None) に対し
# `_mpd_negative_field_values(track, "track_no")` (=常に `[]`) を見て
# `if not values: return False` により無条件却下してしまい、backend が
# 実際に見つけた候補が最終的に0件へ丸められてしまう。genre は既に
# `if field == "genre" and len(positives) == 1: continue` で対処済みだが
# track_no は対象外のままだった。
#
# 実機確認 (dev mopidy 6601, ytmusic 実アカウント、修正前):
# `find "(Track == \"1\")"` は `OK` のみ (0件応答)。同時に
# 旧来形式 `find track "1"` (フィルタ式でなくpositivesを経由しないため
# ローカル再検証自体が発生しない) はヒットしており、フィルタ式経由の
# ローカル再検証だけがこの経路を機能不全にしていることを確認した。
#
# 修正範囲の判断: mopidy_ytmusic の search() は query dict に "track_no"
# キー以外 (any/track_name/albumartist/artist/album/genre/date/uri) が
# 1つでも存在すると elif 連鎖で track_no 分岐へ到達せず track_no を一切
# 見ないまま検索する (mpdfindmultitag-patch.py/mpdgenrepositivetrust-patch.py
# が対処した既知の制約と同根)。そのため track_no を一律で "any" と同様
# ローカル再検証スキップ扱いにすると、`find track "1" artist "Y"` の
# ような複合条件で「backendが実際には見ていない track_no 条件」を無条件
# 通過させてしまい、AND のはずが artist 単体条件へ静かに緩んでしまう
# 新たな不具合を生む。安全に信頼できるのは positives が track_no 単独
# (=query dict が {"track_no": [...]} のみ、実際に backend の track_no
# 分岐が実行されたと確定できる) の場合のみ。genre と全く同じ設計方針を
# 踏襲し "track_no が唯一の肯定条件のときだけ" ローカル再検証をスキップする。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'field == "track_no" and len(positives) == 1'
if MARKER in s:
    print("track_no positive trust already present in music_db.py, skip")
else:
    anchor = (
        '        if field == "genre" and len(positives) == 1:\n'
        "            continue  # genre 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic 等 Track.genre を常に持たないbackend向け。\n"
        "            # 他フィールドと併用時はbackendがgenreを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        '        if field == "genre" and len(positives) == 1:\n'
        "            continue  # genre 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic 等 Track.genre を常に持たないbackend向け。\n"
        "            # 他フィールドと併用時はbackendがgenreを見ていないため対象外)\n"
        '        if field == "track_no" and len(positives) == 1:\n'
        "            continue  # track_no 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic の検索結果 Track は track_no=None 固定のため。\n"
        "            # 他フィールドと併用時はbackendがtrack_noを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print("patched music_db.py: sole track_no positive condition now trusts backend best-effort match")
