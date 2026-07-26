# mopidy-mpd 3.3.0 の `list` は group 修飾を解さず、rmpc が送る
#   list "Album" group "AlbumArtist"
# を "Unknown filter type" で弾く (rmpc の Albums / Album Artists タブが機能しない)。
# ここでは末尾の `group TAG` 対を取り出し、group タグの distinct 値ごとに
# クエリを絞って再帰的に列挙し、MPD 仕様どおり
#   AlbumArtist: X
#   Album: a
#   Album: b
#   AlbumArtist: Y
#   ...
# の形で返すようにする。ついでに `list Album "(Artist == \"x\")"` のように
# 引数1個がフィルタ式のケースも解釈する (従来は album 以外で必ずエラーだった)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_list_grouped"
if MARKER in s:
    print("list group support already present, skip")
else:
    # ヘルパは raw triple-single string で逐語コピー
    helper = r'''

def _mpd_extract_group_params(params):
    """末尾に並ぶ `group TAG` 対を取り除き、(残りの引数, group フィールド列) を返す。

    実クライアントは group を必ず末尾に置くため、末尾からのみ剥がす
    (フィルタ値がたまたま "group" だった場合の誤爆を避ける)。
    """
    params = list(params)
    groups = []
    while len(params) >= 2 and params[-2].lower() == "group":
        tag = params.pop()
        params.pop()
        field = _LIST_MAPPING.get(tag.lower())
        if field is None:
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        groups.insert(0, field)
    return params, groups


def _mpd_list_grouped(context, field, name, query, groups):
    if not groups:
        values = context.core.library.get_distinct(field, query).get()
        return [(name, v) for v in sorted(v for v in values if v)]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_list_grouped(context, field, name, subquery, groups[1:])
        if sub:
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    s += helper

    anchor_a = (
        "    query = None\n"
        "    if len(params) == 1:\n"
        "        if field != \"album\":\n"
    )
    inject_a = (
        "    params, group_fields = _mpd_extract_group_params(params)\n"
        "\n"
        "    query = None\n"
        "    if len(params) == 1 and params[0][:1] == \"(\":\n"
        "        query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)\n"
        "    elif len(params) == 1:\n"
        "        if field != \"album\":\n"
    )
    assert s.count(anchor_a) == 1, f"anchor_a count={s.count(anchor_a)}"
    s = s.replace(anchor_a, inject_a, 1)

    anchor_b = (
        "    name = _LIST_NAME_MAPPING[field]\n"
        "    result = context.core.library.get_distinct(field, query)\n"
        "    return [(name, value) for value in result.get()]\n"
    )
    inject_b = (
        "    name = _LIST_NAME_MAPPING[field]\n"
        "    return _mpd_list_grouped(context, field, name, query, group_fields)\n"
    )
    assert s.count(anchor_b) == 1, f"anchor_b count={s.count(anchor_b)}"
    s = s.replace(anchor_b, inject_b, 1)

    open(p, "w").write(s)
    print("patched music_db.py: list の group 修飾 + フィルタ式引数をサポート")
