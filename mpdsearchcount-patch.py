# mpd.readthedocs.io の protocol リファレンス全文と mopidy_mpd/protocol/music_db.py の
# @protocol.commands.add(...) 一覧を照合した差分調査 (mpdplaylistlength-patch.py 参照) で
# 見つかった未実装6件のうち、`playlistlength` に続き自走エージェントが今回選定した項目。
# `searchcount {FILTER} [group {GROUPTYPE}]` (music database section) は `count` と全く同じ
# 意味論だが、`find`/`search` の関係と同じく大文字小文字を区別しない (musicpd.org 仕様: "count は
# 大文字小文字を区別するが、searchcount は区別しない。それ以外のパラメータの意味は同じ")。
# mopidy_mpd 3.3.0 にはコマンド自体が丸ごと存在せず `ACK unknown command` になる。
# 実装は count の既存インフラ (_mpd_count_grouped/_mpd_pop_negatives/_mpd_pop_positives、
# mpdcount-patch.py/mpdnegfilter-patch.py/mpdfilterkind-patch.py 由来) をそのまま再利用する:
#   - count は `library.search(query, exact=True)` (find と同じ厳密一致) を使うのに対し、
#     search は `library.search(query)` (exact=False, 大文字小文字を区別しない部分一致) を使う
#     という既存の使い分けが、まさに count/find vs search の大小文字区別の違いを実現している
#     実装上の軸なので、_mpd_count_grouped に exact フラグを追加し searchcount からは
#     exact=False で呼ぶだけで済む (group 再帰・negatives/positives フィルタは無改変で共有)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "searchcount"
if f'@protocol.commands.add("{MARKER}")' in s:
    print("searchcount already present, skip")
else:
    assert "_mpd_count_grouped" in s, "mpdcount-patch must run before mpdsearchcount-patch"
    assert "_mpd_pop_negatives" in s, "mpdnegfilter-patch must run before mpdsearchcount-patch"
    assert "_mpd_pop_positives" in s, "mpdfilterkind-patch must run before mpdsearchcount-patch"

    old_grouped = '''def _mpd_count_grouped(context, query, groups, negatives=(), positives=()):
    if not groups:
        results = context.core.library.search(query=query, exact=True).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=False
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=False
        )
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
        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives, positives)
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows'''
    assert s.count(old_grouped) == 1, f"old_grouped count={s.count(old_grouped)}"

    new_grouped = '''def _mpd_count_grouped(context, query, groups, negatives=(), positives=(), exact=True):
    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=False
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=False
        )
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
        sub = _mpd_count_grouped(context, subquery, groups[1:], negatives, positives, exact)
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows'''
    s = s.replace(old_grouped, new_grouped, 1)

    old_count = '''@protocol.commands.add("count")
def count(context, *args):
    """
    *musicpd.org, music database section:*

        ``count {FILTER} [group {GROUPTYPE}]``

        Counts the number of songs and their total playtime in the db
        matching ``FILTER``. ``group`` groups the results by a tag,
        e.g. ``count group artist`` (FILTER may be omitted).

    *GMPC:*

    - use multiple tag-needle pairs to make more specific searches.
    """
    args, _group_fields = _mpd_extract_group_params(args)
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    return _mpd_count_grouped(context, query, _group_fields, _negatives, _positives)'''
    assert s.count(old_count) == 1, f"old_count count={s.count(old_count)}"

    new_count = old_count + '''


@protocol.commands.add("searchcount")
def searchcount(context, *args):
    """
    *musicpd.org, music database section:*

        ``searchcount {FILTER} [group {GROUPTYPE}]``

        Counts the number of songs and their total playtime in the db
        matching ``FILTER``, like ``count``, except that ``FILTER`` is
        matched case insensitively, like with ``search``. ``group`` groups
        the results by a tag, e.g. ``searchcount group artist`` (FILTER may
        be omitted).
    """
    args, _group_fields = _mpd_extract_group_params(args)
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False
    )'''
    s = s.replace(old_count, new_count, 1)

    open(p, "w").write(s)
    print("patched music_db.py: searchcount (count の大文字小文字を区別しない版) を実装")
