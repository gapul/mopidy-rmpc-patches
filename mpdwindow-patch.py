# mopidy-mpd 3.3.0 の `search`/`find` は末尾の `window START:END` 修飾子 (musicpd.org 仕様:
#   search {FILTER} [sort {TYPE}] [window {START:END}]
# ) を mpdsort-patch の時点では読み飛ばすだけで実際のページングをしていなかった。rmpc は
# 大きな結果セットをページ単位で取得するため window を送ってくるので、実際に結果を
# スライスして返すようにする。仕様 (musicpd.org): START/END は 0-based、END は
# Python のスライスと同様に含まれない (exclusive)。END を省略すると open-ended
# (`START:` = 以降すべて)。sort と併用時は sort 済みの結果に対して window を適用する
# (仕様の並び `[sort] [window]` どおり)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_parse_window"
if MARKER in s:
    print("window modifier support already present, skip")
else:
    old_func = '''def _mpd_extract_sort_params(params):
    """末尾から `sort TYPE` / `window ...` 修飾子対を剥がし、(残りの引数, sort用フィールド,
    降順か) を返す。`_mpd_extract_group_params` (mpdlist-patch) と同様、末尾からのみ剥がす
    ことで、フィルタ値がたまたま "sort" だった場合の誤爆を避ける。`window` はこの項目では
    未対応のため、値を読み飛ばすだけ (今まで通り無視・無害)。sort が無ければ
    (params, None, False)。TYPE が未知タグの場合はエラー。
    """
    params = list(params)
    sort_field = None
    descending = False
    while len(params) >= 2 and params[-2].lower() in ("sort", "window"):
        key = params[-2].lower()
        value = params[-1]
        del params[-2:]
        if key == "sort":
            desc = value.startswith("-")
            type_ = value[1:] if desc else value
            field = _SORT_MAPPING.get(type_.lower())
            if field is None:
                raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
            sort_field, descending = field, desc
    return params, sort_field, descending
'''
    assert s.count(old_func) == 1, f"old_func count={s.count(old_func)}"

    new_func = '''def _mpd_parse_window(value):
    """`window START:END` の値部分を slice に変換する。0-based, END は非包含。
    END 省略 (`START:`) は open-ended。書式不正/非数値/負値は MpdArgError。
    """
    if ":" not in value:
        raise exceptions.MpdArgError(f"Invalid window: {value}")
    start_s, end_s = value.split(":", 1)
    if not start_s.isdigit():
        raise exceptions.MpdArgError(f"Invalid window: {value}")
    start = int(start_s)
    end_s = end_s.strip()
    if end_s:
        if not end_s.isdigit():
            raise exceptions.MpdArgError(f"Invalid window: {value}")
        end = int(end_s)
        if end < start:
            raise exceptions.MpdArgError(f"Invalid window: {value}")
    else:
        end = None
    return slice(start, end)


def _mpd_extract_sort_params(params):
    """末尾から `sort TYPE` / `window START:END` 修飾子対を剥がし、(残りの引数,
    sort用フィールド, 降順か, window の slice か None) を返す。
    `_mpd_extract_group_params` (mpdlist-patch) と同様、末尾からのみ剥がすことで、
    フィルタ値がたまたま "sort"/"window" だった場合の誤爆を避ける。両方無ければ
    (params, None, False, None)。TYPE が未知タグ/window の書式不正はエラー。
    """
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
            field = _SORT_MAPPING.get(type_.lower())
            if field is None:
                raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
            sort_field, descending = field, desc
        else:
            window = _mpd_parse_window(value)
    return params, sort_field, descending, window
'''
    s = s.replace(old_func, new_func, 1)

    old_callsite = (
        "    args, _sort_field, _sort_desc = _mpd_extract_sort_params(args)\n"
    )
    assert s.count(old_callsite) == 2, f"old_callsite count={s.count(old_callsite)}"
    new_callsite = (
        "    args, _sort_field, _sort_desc, _window = _mpd_extract_sort_params(args)\n"
    )
    s = s.replace(old_callsite, new_callsite)

    old_tail = (
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    assert s.count(old_tail) == 2, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        "    if _sort_field:\n"
        "        result_tracks = _mpd_sort_tracks(result_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        result_tracks = result_tracks[_window]\n"
        "    return translator.tracks_to_mpd_format(\n"
        "        result_tracks, context.session.tagtypes\n"
        "    )\n"
    )
    s = s.replace(old_tail, new_tail)

    open(p, "w").write(s)
    print("patched music_db.py: search/find の window 修飾をサポート")
