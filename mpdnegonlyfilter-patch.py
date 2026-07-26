# `count`/`searchcount group TAG` と `playlistfind`/`playlistsearch` が、フィルタ式が
# `!=`/`!~` (negatives) だけで肯定条件を1つも含まない場合に、実際には正しく計算できるにも
# 関わらず一律 `ACK incorrect arguments` を返す不具合。TODO 全項目消化済みのため自走
# エージェントが調査して新規発見・追加した項目。
#
# mpdnegfilter-patch.py が `_query_from_mpd_filter_expression` に追加した
# `if not query: raise exceptions.MpdArgError("incorrect arguments")` は、本来
# 「backend の library.search() に丸投げする find/search/findadd/searchadd/searchaddpl
# が、mopidy-ytmusic のようなリモートAPIのみのbackendでは『全曲取得』手段を持たず
# 代替不能」という制約のために必要な安全策 (mpdnegfilter-patch.py 自身の既知の制約
# コメント参照)。ところがこの関数は呼び出し元の事情を一切知らないため、同じ制約が
# 本来不要な2つの経路にも一律適用されてしまっていた:
#
#   1. `count`/`searchcount group TAG`: `_mpd_count_grouped()` は group 指定時
#      `context.core.library.get_distinct(gfield, query)` でタグ値を列挙し、値ごとに
#      `subquery[gfield] = [value]` という肯定条件を追加してから再帰する構造になって
#      いる (music_db.py で既に確認済み)。つまり最終的に leaf (groups が尽きた時点) で
#      `context.core.library.search()` へ渡される query は常に非空になり、「backendが
#      全曲取得できない」制約はそもそも発生しない。にも関わらず、フィルタが negatives
#      のみだと group の有無を問わず即座に ACK になっていた。
#   2. `playlistfind`/`playlistsearch` (current_playlist.py `_pf_search`):
#      `context.core.tracklist.get_tl_tracks()` でキュー全体を無条件に取得してから
#      ローカルの Python 比較でフィルタする実装のため、backend への丸投げが一切存在
#      せず「全曲取得できない」制約が原理的に当てはまらない。実 MPD もキューという
#      常に有限・列挙可能なデータに対して素朴に `!=` 単独条件を評価できる。
#
# dev mopidy(6601) で実際に `playlistfind "(Title != \"XYZDOESNOTEXIST\")"` を送って
# 再現確認したところ、2曲キューされた状態でも `ACK [2@0] {playlistfind} incorrect
# arguments` となり、本来「該当しない1曲を除いた全曲」を返せるはずの操作が丸ごと
# 失敗することを確認した。`count ... group TAG` も同様に、検証用スタブ backend
# (get_distinct/search を実装、genre/artist違いの4トラック) で
# `count "(Genre != \"Rock\")" group artist` を送るとフィルタ無し版
# (`count "(Genre == \"Rock\")" group artist`、こちらは正しく動作) と対比して同じ
# ACK になることを確認済み。
#
# 修正方針: `_query_from_mpd_filter_expression`/`_query_from_mpd_search_parameters` に
# `require_positive=True` (既定値、find/search/findadd/searchadd/searchaddpl は
# 無指定のまま=従来通り厳格) を追加し、呼び出し元が「肯定条件が無くても計算可能」と
# 判断できる場合だけ `require_positive=False` を渡せるようにする。
#   - `count`/`searchcount`: `group` 指定時 (`_group_fields` が非空) のみ
#     `require_positive=False` を渡す (group 無しの場合は従来通り backend 制約が
#     残るため厳格なまま)。
#   - `playlistfind`/`playlistsearch` (`_pf_search`): 常に
#     `require_positive=False` (キューはbackend丸投げが無いため制約自体が無い)。
#     加えて `_pf_search` 自身が二重に持っていた同種の `if not query: raise` も、
#     negatives/positives いずれも空の場合のみ (=本当に何の条件も無い場合のみ)
#     エラーにするよう修正。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "require_positive"
if MARKER in s:
    print("negative-only filter + group/queue support already present in music_db.py, skip")
else:
    old_search_params = (
        "def _query_from_mpd_search_parameters(parameters, mapping):\n"
        "    parameters = list(parameters)\n"
        '    if parameters and isinstance(parameters[0], str) and parameters[0][:1] == "(":\n'
        "        return _query_from_mpd_filter_expression(parameters[0], mapping)\n"
        "    query = {}\n"
        "    while parameters:\n"
        "        # TODO: does it matter that this is now case insensitive\n"
        "        field = mapping.get(parameters.pop(0).lower())\n"
        "        if not field:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        if not parameters:\n"
        "            raise ValueError\n"
        "        value = parameters.pop(0)\n"
        "        if value.strip():\n"
        "            query.setdefault(field, []).append(value)\n"
        "    return query"
    )
    assert s.count(old_search_params) == 1, f"old_search_params count={s.count(old_search_params)}"
    new_search_params = (
        "def _query_from_mpd_search_parameters(parameters, mapping, require_positive=True):\n"
        "    parameters = list(parameters)\n"
        '    if parameters and isinstance(parameters[0], str) and parameters[0][:1] == "(":\n'
        "        return _query_from_mpd_filter_expression(\n"
        "            parameters[0], mapping, require_positive=require_positive\n"
        "        )\n"
        "    query = {}\n"
        "    while parameters:\n"
        "        # TODO: does it matter that this is now case insensitive\n"
        "        field = mapping.get(parameters.pop(0).lower())\n"
        "        if not field:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        if not parameters:\n"
        "            raise ValueError\n"
        "        value = parameters.pop(0)\n"
        "        if value.strip():\n"
        "            query.setdefault(field, []).append(value)\n"
        "    return query"
    )
    s = s.replace(old_search_params, new_search_params, 1)

    old_filter_expr_sig = (
        "def _query_from_mpd_filter_expression(expr, mapping):\n"
        "    query = {}\n"
        "    negatives = []\n"
        "    positives = []\n"
    )
    assert s.count(old_filter_expr_sig) == 1, f"old_filter_expr_sig count={s.count(old_filter_expr_sig)}"
    new_filter_expr_sig = (
        "def _query_from_mpd_filter_expression(expr, mapping, require_positive=True):\n"
        "    query = {}\n"
        "    negatives = []\n"
        "    positives = []\n"
    )
    s = s.replace(old_filter_expr_sig, new_filter_expr_sig, 1)

    old_filter_expr_tail = (
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    if negatives:\n"
        '        query["__mpd_negatives__"] = negatives\n'
        "    if positives:\n"
        '        query["__mpd_positives__"] = positives\n'
        "    return query\n"
    )
    assert s.count(old_filter_expr_tail) == 1, f"old_filter_expr_tail count={s.count(old_filter_expr_tail)}"
    new_filter_expr_tail = (
        "    if require_positive and not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    if negatives:\n"
        '        query["__mpd_negatives__"] = negatives\n'
        "    if positives:\n"
        '        query["__mpd_positives__"] = positives\n'
        "    return query\n"
    )
    s = s.replace(old_filter_expr_tail, new_filter_expr_tail, 1)

    # count(): group 指定時のみ「肯定条件0件」を許容 (group 無しは従来通り backend
    # 丸投げの制約が残るため厳格なまま)
    old_count = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives, _positives)\n"
    )
    assert s.count(old_count) == 1, f"old_count count={s.count(old_count)}"
    new_count = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(\n"
        "            args, _SEARCH_MAPPING, require_positive=not _group_fields\n"
        "        )\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    return _mpd_count_grouped(context, query, _group_fields, _negatives, _positives)\n"
    )
    s = s.replace(old_count, new_count, 1)

    old_searchcount = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    return _mpd_count_grouped(\n"
        "        context, query, _group_fields, _negatives, _positives, exact=False\n"
        "    )\n"
    )
    assert s.count(old_searchcount) == 1, f"old_searchcount count={s.count(old_searchcount)}"
    new_searchcount = (
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(\n"
        "            args, _SEARCH_MAPPING, require_positive=not _group_fields\n"
        "        )\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        "    return _mpd_count_grouped(\n"
        "        context, query, _group_fields, _negatives, _positives, exact=False\n"
        "    )\n"
    )
    s = s.replace(old_searchcount, new_searchcount, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: count/searchcount group指定時に肯定条件0件(negativesのみ)"
        "のフィルタを許容"
    )

# current_playlist.py 側: playlistfind/playlistsearch はキュー全体を無条件取得してから
# ローカルフィルタする実装のため、backend 丸投げの「全曲取得不能」制約が原理的に無い。
# require_positive=False を渡し、二重に存在した同種のガードも negatives/positives が
# 両方空のときだけエラーにするよう修正する。
cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

CP_MARKER = "require_positive"
if CP_MARKER in s_cp:
    print("negative-only filter support already present in current_playlist.py, skip")
else:
    old_pf_search = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    negatives = _mpd_pop_negatives(query)\n"
        "    positives = _mpd_pop_positives(query)\n"
        "    if not query:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
    )
    assert s_cp.count(old_pf_search) == 1, f"old_pf_search count={s_cp.count(old_pf_search)}"
    new_pf_search = (
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(\n"
        "            args, _SEARCH_MAPPING, require_positive=False\n"
        "        )\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    negatives = _mpd_pop_negatives(query)\n"
        "    positives = _mpd_pop_positives(query)\n"
        "    if not query and not negatives and not positives:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "\n"
    )
    s_cp = s_cp.replace(old_pf_search, new_pf_search, 1)

    open(cp, "w").write(s_cp)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch で "
        "肯定条件0件(negatives/positivesのみ)のフィルタを許容"
    )
