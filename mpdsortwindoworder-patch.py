# find/search/findadd/searchadd/searchaddpl が共有する `_mpd_extract_sort_params()`
# (mpdsort-patch.py で新設、mpdwindow-patch.py で window 対応を追加) は末尾から
# `while len(params) >= 2 and params[-2].lower() in ("sort", "window"):` という
# ループで `sort`/`window` 修飾子対を「任意の順序・任意の回数」剥がしてしまう不具合。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体(gh rawで src/command/DatabaseCommands.cxx の ParseDatabaseSelection() を
# 確認)は非ループの一発勝負: まず末尾ペアが "window" なら1回だけ剥がし、続けて
# (window 剥がし後の)末尾ペアが "sort" なら1回だけ剥がす。つまりコマンド上の並びは
# 常に `FILTER [sort TYPE] [window START:END]` (sort が window より前) でなければ
# ならず、重複した `sort`/`window` も許されない。剥がしきれなかった "sort"/"window"
# トークンはそのまま SongFilter::Parse() (mopidy_mpd 側では
# _query_from_mpd_search_parameters() の旧式 TAG VALUE ループ) に渡り、未知タグとして
# ACK になる。
#
# 実機確認(TCP 6601、実ytmusicアカウント): 以下がいずれも修正前は `OK`(本来は
# ACKになるべき)だったことを確認:
#   find "(Artist == \"YOASOBI\")" window "0:1" sort Artist   (順序が逆)
#   find "(Artist == \"YOASOBI\")" sort Artist sort Title     (sort 重複)
#   find "(Artist == \"YOASOBI\")" window "0:1" window "1:2"  (window 重複)
#
# BACKLOG.md を `_mpd_extract_sort_params`/`sort.*window.*順序`/`重複.*sort` で
# grep したが、この関数の新設/window対応追加/共用箇所の確認についての記述のみで、
# 順序検証・重複検出は未対応・未blockedと確認。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "mpdsortwindoworder-patch"
if MARKER in s:
    print("sort/window order validation already present, skip")
else:
    old_func = '''def _mpd_extract_sort_params(params):
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
    assert s.count(old_func) == 1, f"old_func count={s.count(old_func)}"

    new_func = '''def _mpd_extract_sort_params(params):  # mpdsortwindoworder-patch
    """末尾から `[sort TYPE] [window START:END]` 修飾子を剥がし、(残りの引数,
    sort用フィールド, 降順か, window の slice か None) を返す。実MPD本体
    (src/command/DatabaseCommands.cxx ParseDatabaseSelection()) と同じく非ループの
    一発勝負: まず末尾ペアが "window" なら1回だけ剥がし、続けて(剥がした後の)
    末尾ペアが "sort" なら1回だけ剥がす。順序が逆(window が sort より前)だったり
    重複していたりする場合、余った "sort"/"window" トークンはそのまま残り、
    呼び出し側の _query_from_mpd_search_parameters() で未知タグとして ACK になる。
    両方無ければ (params, None, False, None)。TYPE が未知タグ/window の書式不正は
    エラー。
    """
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
        field = _SORT_MAPPING.get(type_.lower())
        if field is None:
            raise exceptions.MpdArgError(f"Unknown sort type: {type_}")
        sort_field, descending = field, desc
        del params[-2:]
    return params, sort_field, descending, window
'''
    s = s.replace(old_func, new_func, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: sort/window 修飾子の順序・重複を実MPD準拠で検証するよう修正"
    )
