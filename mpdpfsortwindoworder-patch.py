# mpdsortwindoworder-patch.py と同じ不具合が current_playlist.py 側の独自コピー
# `_pf_extract_sort_params()` (playlistfind/playlistsearch 用、
# mpdplaylistfindsortprio-patch.py で新設) にも存在する。music_db.py の
# `_mpd_extract_sort_params()` とは独立した実装(sort prio 対応のため
# `_PF_SORT_MAPPING` を使う点のみが差分)なので、別ファイルとして同じ修正を適用する
# 必要がある(mpdbasefilter-patch.py が music_db.py/current_playlist.py 両方の
# `_mpd_track_matches_positives`/`_pf_matches` を個別に直す必要があったのと同じ
# クロスファイル重複)。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# 実機確認(TCP 6601、実キューに実データを findadd 後): 以下が修正前は `OK`
# (本来ACKになるべき)だったことを確認:
#   playlistfind "(Artist == \"YOASOBI\")" window "0:1" sort Artist  (順序が逆)
#   playlistfind "(Artist == \"YOASOBI\")" sort Artist sort Title    (sort 重複)
p = "mopidy_mpd/protocol/current_playlist.py"
s = open(p).read()

MARKER = "mpdpfsortwindoworder-patch"
if MARKER in s:
    print("playlistfind/playlistsearch sort/window order validation already present, skip")
else:
    old_func = '''def _pf_extract_sort_params(params):
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
'''
    assert s.count(old_func) == 1, f"old_func count={s.count(old_func)}"

    new_func = '''def _pf_extract_sort_params(params):  # mpdpfsortwindoworder-patch
    """`_mpd_extract_sort_params` (music_db.py) と同じく実MPD本体
    (DatabaseCommands.cxx ParseDatabaseSelection()) 準拠の非ループ一発勝負で
    `[sort TYPE] [window START:END]` を剥がす。playlistfind/playlistsearch専用の
    `sort prio` (キュー優先度でソート、mpd.readthedocs.io protocol.htmlの
    playlistfind節に明記、find/search/list/countの `_SORT_MAPPING` には存在しない)
    も受け付ける。共有の `_SORT_MAPPING` 自体は変更しない (find/search側へ
    sort prioが波及するのを防ぐため)。順序が逆や重複がある場合、余った
    "sort"/"window" トークンはそのまま残り呼び出し側で未知タグとしてACKになる。"""
    params = list(params)
    sort_field = None
    descending = False
    window = None
    if len(params) >= 2 and params[-2].lower() == "window":
        window = _mpd_parse_window(params[-1])
        del params[-2:]
    if len(params) >= 2 and params[-2].lower() == "sort":
        value = params[-1]
        desc = value.startswith("-")
        type_ = value[1:] if desc else value
        field = _PF_SORT_MAPPING.get(type_.lower())
        if field is None:
            raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
        sort_field, descending = field, desc
        del params[-2:]
    return params, sort_field, descending, window
'''
    s = s.replace(old_func, new_func, 1)

    open(p, "w").write(s)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch の "
        "sort/window 修飾子の順序・重複を実MPD準拠で検証するよう修正"
    )
