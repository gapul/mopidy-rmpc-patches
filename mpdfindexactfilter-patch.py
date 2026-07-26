# `find`/`findadd`/`count` (`searchcount`/`search`/`searchadd`/`searchaddpl` を除く) が、
# フィルタ式 (`(Tag contains "x")`/`(Tag starts_with "x")`/`(Tag =~ "x")`) の明示的な
# 演算子を無視し、backend への丸投げクエリを常に `exact=True` で送ってしまうため、
# mopidy_ytmusic のように `exact=True` 時に自前で casefold 完全一致まで絞り込む backend
# では contains/starts_with/regex を指定した正当な部分一致検索が無条件で0件になる不具合。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが mpdfilterkind-patch.py
# 等これまでの一連の発見的パッチと同じ流儀でコード品質を再調査して発見した項目。
#
# 実MPD仕様 (mpd.readthedocs.io/en/latest/protocol.html) を確認したところ、`find` の
# "case sensitive" は search との大小文字区別の違いを説明しているだけで、フィルタ式の
# 明示的な演算子 (`==`/`contains`/`starts_with`/`=~`) はそのまま尊重される
# (`find` だから常に完全一致に強制される、という仕様ではない) と確認した。
#
# mpdfilterkind-patch.py が `_query_from_mpd_filter_expression` に実装した
# `(field, kind, value)` の `positives` リストと、それを個々の track 属性に対して直接
# 判定する `_mpd_filter_positives`/`_mpd_track_matches_positives` は、演算子種別ごとの
# 判定をpost-filterとして既に正しく実装済み (music_db.py で確認済み)。ところが
# `find()`(268行目)/`findadd()`(367行目)/`count()`(経由の`_mpd_count_grouped`既定値、
# 204行目) は、この positives の有無に関わらず一律 `context.core.library.search(query=query,
# exact=True)` を呼んでおり、mopidy_ytmusic/library.py の `search()` はこの `exact=True` を
# 受けると `parseSearch(res, field, query[field])` を呼んで `q.casefold() ==
# result["title"/"artist"/"title"].casefold() for q in queries` という完全一致のみを
# 通す事前フィルタを自前でかける (library.py で確認済み)。この事前フィルタは
# post-filter (`_mpd_filter_positives`) に候補が届く前に、`contains`/`starts_with` で
# 指定した部分文字列を「完全一致でない」という理由で弾いてしまう。`search`/`searchadd`/
# `searchaddpl`/`searchcount` は `exact=False` を渡すためこの問題が起きず、`find` 系だけの
# 非対称なバグと確認した。
#
# rmpc本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc/src/ui/panes/search/inputs.rs の `FilterKind` の既定値は `Contains` であり、
# rmpc/src/ui/panes/search/mod.rs は「Case sensitive」トグルがONの状態では `find` を、
# OFFの状態では `search` を送信する。つまり検索ペインで大文字小文字区別トグルを
# ONにしたまま (既定のContainsモードで) 部分文字列検索する、という誰でも到達する
# 普通の操作がこの不具合を踏む。
#
# 修正方針: `positives` (フィルタ式由来の演算子付き肯定条件) が1件でもあれば、
# backend への `exact` は常に False にし、演算子種別ごとの厳密な判定は既存の
# post-filter (`_mpd_filter_positives`) に完全に委ねる。post-filter は kind=="exact"
# (`==`) も含めて全演算子を正しく扱うため、フィルタ式由来のクエリでは backend 側の
# 事前 exact 縮退は不要かつ有害。positives が無い旧来形式 (`find TAG VALUE` の
# 暗黙 exact、`_query_from_mpd_search_parameters` の非フィルタ式パスは positives を
# 一切生成しない) では、これまで通り backend への exact=True を維持し既存の
# 動作を変えない。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_backend_search_exact"
if MARKER in s:
    print("find/findadd/count exact-filter backend override already present in music_db.py, skip")
else:
    old_helper_anchor = (
        "def _mpd_filter_positives(tracks, positives, case_sensitive):\n"
        "    if not positives:\n"
        "        return tracks\n"
        "    return [t for t in tracks if _mpd_track_matches_positives(t, positives, case_sensitive)]\n"
    )
    assert s.count(old_helper_anchor) == 1, f"old_helper_anchor count={s.count(old_helper_anchor)}"
    new_helper_anchor = old_helper_anchor + (
        "\n\n"
        "def _mpd_backend_search_exact(default_exact, positives):\n"
        "    # フィルタ式由来の明示的な演算子付き肯定条件 (positives) がある場合、\n"
        "    # ==/contains/starts_with/=~ の判定は _mpd_filter_positives が track の\n"
        "    # 実属性を直接見て正しく行うため、backend への exact=True による事前の\n"
        "    # 完全一致縮退は不要かつ有害 (mopidy_ytmusic 等は exact=True 時に自前の\n"
        "    # casefold 完全一致で候補を先に間引き、contains/starts_with/=~ を無条件で\n"
        "    # 0件にしてしまう)。positives が無い旧来形式 (find TAG VALUE の暗黙\n"
        "    # exact) では従来通り default_exact を尊重する。\n"
        "    return False if positives else default_exact\n"
    )
    s = s.replace(old_helper_anchor, new_helper_anchor, 1)

    old_find_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = []\n"
    )
    assert s.count(old_find_search) == 1, f"old_find_search count={s.count(old_find_search)}"
    new_find_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(\n"
        "        query=query, exact=_mpd_backend_search_exact(True, _positives)\n"
        "    ).get()\n"
        "    result_tracks = []\n"
    )
    s = s.replace(old_find_search, new_find_search, 1)

    old_findadd_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=True\n"
        "    )\n"
    )
    assert s.count(old_findadd_search) == 1, f"old_findadd_search count={s.count(old_findadd_search)}"
    new_findadd_search = (
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "\n"
        "    results = context.core.library.search(\n"
        "        query=query, exact=_mpd_backend_search_exact(True, _positives)\n"
        "    ).get()\n"
        "    tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=True\n"
        "    )\n"
    )
    s = s.replace(old_findadd_search, new_findadd_search, 1)

    old_count_return = (
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives, _positives)\n"
    )
    assert s.count(old_count_return) == 1, f"old_count_return count={s.count(old_count_return)}"
    new_count_return = (
        "    return _mpd_count_grouped(\n"
        "        context, query, _group_fields, _negatives, _positives,\n"
        "        exact=_mpd_backend_search_exact(True, _positives),\n"
        "    )\n"
    )
    s = s.replace(old_count_return, new_count_return, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: find/findadd/count がフィルタ式の "
        "contains/starts_with/=~ 演算子を backend へ丸投げする際に exact=True で "
        "誤って完全一致に縮退させていた問題を修正"
    )
