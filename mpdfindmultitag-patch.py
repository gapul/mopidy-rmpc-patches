# mopidy_mpd/protocol/music_db.py の `_query_from_mpd_search_parameters()` (旧来の
# 空白区切りTYPE/WHAT複数ペア形式、例: `find artist "A" album "B"`) が、複数の
# TYPE/WHAT ペアを渡しても query dict に全フィールドを積むだけで __mpd_positives__
# (新フィルタ式 `(Tag == "x")` 用に導入済みの、find/search/count/findadd/searchadd/
# searchaddpl 共通のローカルpost-filterへ渡す肯定条件リスト) を一切生成しない不具合を
# 発見・修正。TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが調査して
# 新規発見・追加した項目。
#
# find() 自身のdocstringが「GMPC: also uses find album [ALBUM] artist [ARTIST] to
# list album tracks」と明記している、まさに公式に想定された使い方が壊れている。
# mopidy_ytmusic.library.search() は `if "any" in query: ... elif "track_name" in
# query: ... elif "albumartist" in query or "artist" in query: ... elif "album" in
# query: ... elif "genre" in query: ... elif "uri" in query: ... else: ...` という
# 単一フィールドのみを見るelif連鎖であり、query dict に複数フィールドが同時に
# 入っていても優先順位が最も高い1つだけが使われ他のキーは完全に無視される。
# 旧来形式は __mpd_positives__ を作らないため _mpd_pop_positives() が返す positives が
# 常に空リストとなり、find()/count()/findadd()/search()/searchadd()/searchaddpl() が
# 呼ぶ _mpd_filter_positives() は「no positives→フィルタなしでそのまま通す」ため
# ローカル側でも救済されない。結果、`find artist "特定のアーティスト" album
# "特定のアルバム"` は album 条件が黙殺され、そのアーティストの全曲がalbum問わず
# 返ってしまう (件数が多すぎるだけで、エラーにも0件にもならずサイレントに壊れるため
# 発見しづらい)。
#
# 対策: 新フィルタ式と同じ __mpd_positives__ 機構を旧来形式にも配線する。全フィールドが
# ちょうど1値ずつ (通常のGMPC的な使い方) の場合のみ、各 (field, "exact", value) を
# positives へ積む (同一フィールドに複数値が渡された場合はbackendへの結合テキスト検索
# という従来の挙動をそのまま維持し、誤って過剰制約しないよう対象外とする)。これにより
# _mpd_backend_search_exact() が既存ロジックのまま positives 有り→backend側の
# exact=True narrowing を無効化しローカルの _mpd_filter_positives (exact/大文字小文字
# 区別はfind=True/search系=Falseで既存のまま) に委ねるため、backend が1フィールドしか
# 見ていなくても残りのフィールドがローカルで正しくAND絞り込みされる。find/search/count/
# findadd/searchadd/searchaddpl 全てがこの共通関数を経由するため一括で直る
# (mpdregexvalidate-patch.py/mpdnegonlyfilter-patch.py 等と同じ「共有ヘルパーに1箇所
# 手を入れて全コマンドへ波及させる」流儀)。単一フィールドのみの従来クエリは
# len(query) > 1 の条件で対象外のため無変更・回帰なし。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpdfindmultitag_positives"
if MARKER in s:
    print("music_db.py already patched (find multi-tag AND positives), skip")
else:
    ANCHOR = (
        "        value = parameters.pop(0)\n"
        "        if value.strip():\n"
        "            query.setdefault(field, []).append(value)\n"
        "    return query\n"
    )
    assert s.count(ANCHOR) == 1, f"expected 1 occurrence of legacy query-loop anchor (got {s.count(ANCHOR)})"
    NEW = (
        "        value = parameters.pop(0)\n"
        "        if value.strip():\n"
        "            query.setdefault(field, []).append(value)\n"
        "    _mpdfindmultitag_positives = [\n"
        '        (f, "exact", v[0]) for f, v in query.items() if len(v) == 1\n'
        "    ]\n"
        "    if len(query) > 1 and len(_mpdfindmultitag_positives) == len(query):\n"
        '        query["__mpd_positives__"] = _mpdfindmultitag_positives\n'
        "    return query\n"
    )
    s = s.replace(ANCHOR, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: _query_from_mpd_search_parameters()に旧来形式"
        "(空白区切り複数TYPE/WHATペア)用のAND positives生成を追加。"
        "find artist X album Y のような複数フィールド同時指定でalbum条件が"
        "黙殺されていた不具合を修正 (全フィールドが1値ずつの場合のみ)"
    )
