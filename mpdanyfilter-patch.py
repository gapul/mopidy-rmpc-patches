# mpdfilterkind-patch.py が実装した `_mpd_track_matches_positives` (music_db.py) は、
# `(any contains "X")` のような field="any" の肯定条件も、`(Artist == "X")` 等の具体的
# タグと全く同じロジックで「取得済み Track の全タグ値のいずれかが needle を文字列として
# 満たすか」を判定する。実 MPD (ローカルファイル backend) ではこれで正しいが、
# mopidy-ytmusic backend の library.search() は field="any" のとき YouTube Music の
# 関連度検索 (`filter=None`、リテラルなタグ一致ではなく緩い関連度マッチ) に丸投げして
# おり、返ってくる Track の露出タグ (特に parseSearch() の一部経路で artists が空になる
# ことがある) が検索語を文字列として含まないことが普通にある。TODO/既知の軽微な残課題を
# 全項目消化済みのため自走エージェントが dev mopidy(6601, ytmusic 実アカウント) で
# `search "(any contains \"X\")"` を実際に叩いて発見: `search any "BTS"` (旧来構文、
# post-filter 無し) は "NORMAL (Korean Ver.)" 等の実トラックを正しく返すのに対し、
# `search "(any contains \"BTS\")"` (フィルタ式、mpdfilterkind-patch.py 適用後) は
# 同じ実データに対し常に0件になることを確認した。原因: 上記トラックの Track
# オブジェクトは artists が空 (露出タグのどれにも文字列 "BTS" が含まれない) にも
# かかわらず backend の関連度マッチでは正しくヒットしており、
# `_mpd_track_matches_positives` の field="any" 判定 (全タグ値の文字列一致を要求) が
# これを機械的に弾いてしまう。`(Artist contains "BTS")` 等の具体的タグでは backend
# 自体がタグ一致する候補だけを返す (`filter="artists"` 等) ため同じ問題は起きず、
# mpdfilterkind-patch.py 自身の実機検証 (YOASOBI, Artist/Title 固有フィールドのみ)
# では any 未検証だったため見落とされていた。rmpc 本体の `Tag::Any`
# (rmpc-mpd/src/filter.rs) は検索ペインの既定フィールドであり、実害は
# 「検索ペインでデフォルトのまま何か検索すると常に0件になる」という最も基本的な
# 検索操作の破壊。
#
# 対策: field="any" の positives 条件だけは後段フィルタを適用せず (backend の
# 関連度マッチをそのまま信頼する) 常に合格させる。これは mpdfilterkind-patch.py
# 適用前の挙動 (`(any contains "X")` は backend 丸投げのみ、`search any "X"` と同じ)
# に相当する。具体的タグ (Artist/Title 等) の positives 判定はこれまで通り厳密に
# 行われ無変更 (count/find/findadd/search/searchadd/searchaddpl が経由する
# `_mpd_track_matches_positives` 一箇所の修正で全コマンドに反映される)。
# playlistfind/playlistsearch (current_playlist.py `_pf_matches`) は対象外のまま:
# 既にキューに追加済みのトラックに対する判定であり、backend の関連度検索を
# 経由しないため同じ問題は起きず、field="any"の厳密フィルタはむしろ正しく機能する。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'if field == "any":\n            continue  # backend'
if MARKER in s:
    print("any-field positives skip already present in music_db.py, skip")
else:
    old = (
        "    for field, kind, needle in positives:\n"
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            return False\n"
        '        if kind == "regex":\n'
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "    for field, kind, needle in positives:\n"
        '        if field == "any":\n'
        "            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する\n"
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            return False\n"
        '        if kind == "regex":\n'
    )
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: フィルタ式 (any contains ...) 等 field=any の"
        " positives 後段フィルタを無効化 (backend の関連度マッチ丸投げへ復帰)"
    )
