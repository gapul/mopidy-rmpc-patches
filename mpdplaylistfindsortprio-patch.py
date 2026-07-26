# mpd.readthedocs.io/protocol.html の playlistfind 節 (WebFetchで実際に文面確認済み):
# 「sort sorts the result by the specified tag. ... The type "Last-Modified" can
# sort by file modification time, and "prio" sorts by queue priority.」と明記。
# playlistsearch は「Parameters have the same meaning as for playlistfind」で
# この sort 仕様を継承する。
#
# 現状の mopidy_mpd/protocol/current_playlist.py の `playlistfind`/
# `playlistsearch` (`_pf_search`) は、find/search/list/count と共有する
# music_db.py の `_mpd_extract_sort_params`/`_SORT_MAPPING` をそのまま使って
# おり、"prio" は `_SORT_MAPPING` に無いキーのため `sort prio` を送ると即座に
# `ACK [2@0] {playlistfind} Unknown sort type: prio` になる不具合。
#
# 実機再現 (ENVのPythonでオフライン確認): `python3 -c "from mopidy_mpd.protocol.music_db
# import _mpd_extract_sort_params; _mpd_extract_sort_params(['sort', 'prio'])"`
# → `MpdArgError: Unknown sort type: prio` を即座に再現。
#
# 修正方針: 優先度 (`prio`/`prioid`) はキュー限定の概念で、DB検索
# (find/search/list/count) 側には対応する曲が無い (mpdpriofilter-patch.py の
# コメントと同じ非対称性)。よって共有の `_SORT_MAPPING` 自体には "prio" を
# 追加しない (find/search側にまで sort prio が波及して誤って有効になって
# しまうのを避けるため)。代わりに current_playlist.py 側だけに専用の
# `_PF_SORT_MAPPING`/`_pf_extract_sort_params` を新設し、"prio" を
# `translator.get_priority(tlid)` の実データでソートする。
#
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見した項目。BACKLOG.mdをgrep -n "sort prio\|playlistfind.*sort\|
# _SORT_MAPPING\|_mpd_extract_sort_params"で確認したが、sort修飾子自体の
# 導入(mpdplaylistfind-patch.py)は既出でも"prio"キー欠落は未対応・未blockedと確認。
p = "mopidy_mpd/protocol/current_playlist.py"
s = open(p).read()

MARKER = "_pf_extract_sort_params"
if MARKER in s:
    print("playlistfind/playlistsearch sort prio support already present, skip")
else:
    old_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _mpd_added_since_matches,
    _mpd_base_dir_matches,
    _mpd_extract_sort_params,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_since_matches,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)
'''
    assert s.count(old_import) == 1, f"import anchor count={s.count(old_import)}"
    new_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _SORT_MAPPING,
    _mpd_added_since_matches,
    _mpd_base_dir_matches,
    _mpd_extract_sort_params,
    _mpd_parse_window,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_since_matches,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)
'''
    s = s.replace(old_import, new_import, 1)

    old_search_head = '''def _pf_search(context, args, strict):
    if not args:
        raise exceptions.MpdArgError("wrong number of arguments")
    args, sort_field, descending, window = _mpd_extract_sort_params(args)
'''
    assert s.count(old_search_head) == 1, f"search_head anchor count={s.count(old_search_head)}"
    new_search_head = '''_PF_SORT_MAPPING = dict(_SORT_MAPPING)
_PF_SORT_MAPPING["prio"] = "priority"


def _pf_extract_sort_params(params):
    """`_mpd_extract_sort_params` と同じ末尾からのsort/window剥がしだが、
    playlistfind/playlistsearch専用の `sort prio` (キュー優先度でソート、
    mpd.readthedocs.io protocol.htmlのplaylistfind節に明記、find/search/
    list/countの `_SORT_MAPPING` には存在しない) も受け付ける。共有の
    `_SORT_MAPPING` 自体は変更しない (find/search側へsort prioが波及するのを
    防ぐため)。"""
    params = list(params)
    sort_field = None
    descending = False
    window = None
    while len(params) >= 2 and params[-2].lower() in ("sort", "window"):
        key = params[-2].lower()
        value = params[-1]
        del params[-2:]
        if key == "sort":
            desc = value.startswith("-")
            type_ = value[1:] if desc else value
            field = _PF_SORT_MAPPING.get(type_.lower())
            if field is None:
                raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
            sort_field, descending = field, desc
        else:
            window = _mpd_parse_window(value)
    return params, sort_field, descending, window


def _pf_search(context, args, strict):
    if not args:
        raise exceptions.MpdArgError("wrong number of arguments")
    args, sort_field, descending, window = _pf_extract_sort_params(args)
'''
    s = s.replace(old_search_head, new_search_head, 1)

    old_sort_apply = '''    if sort_field:
        matches.sort(
            key=lambda pt: _mpd_sort_value(pt[1].track, sort_field),
            reverse=descending,
        )
'''
    assert s.count(old_sort_apply) == 1, f"sort_apply anchor count={s.count(old_sort_apply)}"
    new_sort_apply = '''    if sort_field:
        if sort_field == "priority":
            matches.sort(
                key=lambda pt: translator.get_priority(pt[1].tlid),
                reverse=descending,
            )
        else:
            matches.sort(
                key=lambda pt: _mpd_sort_value(pt[1].track, sort_field),
                reverse=descending,
            )
'''
    s = s.replace(old_sort_apply, new_sort_apply, 1)

    open(p, "w").write(s)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch の "
        "`sort prio` (キュー優先度ソート) を実装"
    )
