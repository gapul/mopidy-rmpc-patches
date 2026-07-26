# mopidy-mpd 3.3.0 の `count` は musicpd.org 仕様:
#   count {FILTER} [group {GROUPTYPE}]
# のうち FILTER (旧来のタグ/値ペアも新フィルタ式 `(Tag == "x")` も) は既に解釈できるが
# (mpdsearch-patch 由来)、`group TAG` 修飾を知らないため rmpc 等が group 付きで送ると
# "incorrect arguments" になる。ここでは mpdlist-patch が定義する
# `_mpd_extract_group_params` (末尾の `group TAG` 対を剥がす) をそのまま再利用し、
# `list` と同様に group タグの distinct 値ごとに再帰してクエリを絞り、
#   <GroupTag>: <value>
#   songs: N
#   playtime: T
#   ...
# を group 値ごとに繰り返す形で返す (仕様: `count group artist` のように FILTER 省略も可)。
# group 無しなら従来どおり songs/playtime を1組だけ返す。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_count_grouped"
if MARKER in s:
    print("count group support already present, skip")
else:
    assert "_mpd_extract_group_params" in s, "mpdlist-patch must run before mpdcount-patch"

    helper = '''

def _mpd_count_grouped(context, query, groups):
    if not groups:
        results = context.core.library.search(query=query, exact=True).get()
        result_tracks = _get_tracks(results)
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_count_grouped(context, subquery, groups[1:])
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    s += helper

    old_count = (
        '@protocol.commands.add("count")\n'
        "def count(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``count {TAG} {NEEDLE}``\n"
        "\n"
        "        Counts the number of songs and their total playtime in the db\n"
        "        matching ``TAG`` exactly.\n"
        "\n"
        "    *GMPC:*\n"
        "\n"
        "    - use multiple tag-needle pairs to make more specific searches.\n"
        '    """\n'
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "    result_tracks = _get_tracks(results)\n"
        "    total_length = sum(t.length for t in result_tracks if t.length)\n"
        "    return [\n"
        '        ("songs", len(result_tracks)),\n'
        '        ("playtime", int(total_length / 1000)),\n'
        "    ]\n"
    )
    assert s.count(old_count) == 1, f"old_count count={s.count(old_count)}"

    new_count = (
        '@protocol.commands.add("count")\n'
        "def count(context, *args):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``count {FILTER} [group {GROUPTYPE}]``\n"
        "\n"
        "        Counts the number of songs and their total playtime in the db\n"
        "        matching ``FILTER``. ``group`` groups the results by a tag,\n"
        "        e.g. ``count group artist`` (FILTER may be omitted).\n"
        "\n"
        "    *GMPC:*\n"
        "\n"
        "    - use multiple tag-needle pairs to make more specific searches.\n"
        '    """\n'
        "    args, _group_fields = _mpd_extract_group_params(args)\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    return _mpd_count_grouped(context, query, _group_fields)\n"
    )
    s = s.replace(old_count, new_count, 1)

    open(p, "w").write(s)
    print("patched music_db.py: count の group 修飾をサポート")
