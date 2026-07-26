# フィルタ式 `(Genre == "X")` (単独条件) が mopidy_ytmusic backend では
# 常に0件になる不具合。TODO/既知の軽微な残課題を全項目消化済みのため
# 自走エージェントが調査サブエージェントに委任し、music_db.py/library.py を
# 突き合わせて新規発見・追加した項目。
#
# 経緯: ytsearchgenre-patch.py が `search()` の "genre" 分岐 (query に
# "genre" キーのみが立っている場合) に、"any" 分岐と同じベストエフォートの
# テキスト検索 (self.backend.api.search(term, filter=None)) を実装済み
# (コメント: "any分岐と同じベストエフォートのテキスト検索へフォールバック")。
# ところが mopidy_ytmusic の Track は7箇所全て genre="" 固定
# (library.py の全 Track(...) 生成箇所。YouTube Music のトラックメタデータに
# 曲単位のジャンルタグ自体が存在しないため取得しようがない)。
#
# `_query_from_mpd_filter_expression()` (music_db.py) は演算子の種類に関わらず
# 全ての肯定条件を無条件で positives へ積む実装のため、backend から返った
# best-effort な検索結果に対し `_mpd_track_matches_positives()` が
# `_mpd_negative_field_values(track, "genre")` (=常に `[]`) を見て
# `if not values: return False` により無条件却下してしまい、backend が
# 実際に見つけた候補が最終的に0件へ丸められてしまう。"any" フィールドは
# 同種の「backend の関連度マッチをローカルでは検証できない」問題に対し
# 既に `if field == "any": continue` (ローカル再検証をスキップしbackendを
# 信頼する) で対処済みだが、genre は対象外のままだった。
#
# 実機確認 (dev mopidy 6601, ytmusic 実アカウント、修正前):
# `find "(Genre == \"pop\")"` / `find "(Genre == \"rock\")"` は共に
# `OK` のみ (0件応答)。同時に `find "(Artist == \"YOASOBI\")"` は多数の
# アルバム/曲がヒットしており、genre フィールドだけがこの経路で機能不全に
# なっていることを確認した。
#
# 修正範囲の判断: `_mpd_track_matches_positives()` は複数の positives 条件
# (AND) を1トラックずつ順に検証する汎用関数で、mopidy_ytmusic の
# `library.search()` は query dict に "genre" キー以外 (any/track_name/
# albumartist/artist/album) が1つでも存在すると elif 連鎖で genre 分岐へ
# 到達せず genre を一切見ないまま検索する (mpdfindmultitag-patch.py が
# 対処した「複数タグのAND条件で後続フィールドが黙殺される」既知の制約と
# 同根)。そのため genre を一律で "any" と同様にローカル再検証スキップ扱い
# にすると、`find genre "X" artist "Y"` のような複合条件で「backendが実際
# には見ていない genre 条件」を無条件通過させてしまい、AND のはずが
# artist 単体条件へ静かに緩んでしまう新たな不具合を生む。安全に信頼できる
# のは positives が genre 単独 (=query dict が {"genre": [...]} のみ、
# 実際に backend の genre 分岐が実行されたと確定できる) の場合のみ。
# よって "genre が唯一の肯定条件のときだけ" ローカル再検証をスキップする。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'field == "genre" and len(positives) == 1'
if MARKER in s:
    print("genre positive trust already present in music_db.py, skip")
else:
    anchor = (
        "    for field, kind, needle in positives:\n"
        '        if field == "any":\n'
        "            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        "    for field, kind, needle in positives:\n"
        '        if field == "any":\n'
        "            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する\n"
        '        if field == "genre" and len(positives) == 1:\n'
        "            continue  # genre 単独条件のみ backend のベストエフォート結果を信頼する\n"
        "            # (mopidy_ytmusic 等 Track.genre を常に持たないbackend向け。\n"
        "            # 他フィールドと併用時はbackendがgenreを見ていないため対象外)\n"
        "        values = _mpd_negative_field_values(track, field)\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print("patched music_db.py: sole genre positive condition now trusts backend best-effort match")
