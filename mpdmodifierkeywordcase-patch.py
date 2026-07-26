# find/search/count/searchcount/findadd/searchadd/searchaddpl/list (music_db.py),
# playlistfind/playlistsearch (current_playlist.py), sticker find (stickers.py),
# searchplaylist (stored_playlists.py) が共有／独自実装している末尾修飾子キーワード
# "sort"/"window"/"group"/"position" の判定が、いずれも `params[-2].lower() ==
# "sort"` のように .lower() で大文字小文字を無視して行われている不具合。
#
# TODO/既知の残課題を全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体(gh rawで以下を確認、要約でなく生ソース):
#   src/util/StringAPI.hxx StringIsEqual() … strcmp ベースの大文字小文字を
#     区別する比較 (大文字小文字を無視する版は StringIsEqualIgnoreCase()
#     として別に存在)
#   src/command/DatabaseCommands.cxx ParseDatabaseSelection() (find/search系
#     window/sort) / handle_list() (window/group) / handle_count_internal()
#     (group、mpdcountsinglegroup-patch.py が既に参照した関数) /
#     ParseQueuePosition()・ParseInsertPosition() (findadd/searchadd/
#     searchaddpl の position)
#   src/command/StickerCommands.cxx (sticker find の window/sort)
#   src/command/PlaylistCommands.cxx handle_searchplaylist() (window)
# の該当箇所は例外なく `StringIsEqual(args[args.size() - 2], "window")` の
# ように大文字小文字を区別する比較を使っており、"SORT"/"Window"/"GROUP"/
# "Position" 等は修飾子として一切認識されない(剥がされなかったトークンは
# そのままフィルタ式/引数パーサに渡り、未知タグ・引数エラーとして ACK に
# なる)。一方、修飾子の後に続く TYPE 側(sort TYPE の DB系タグ名解決)は
# ParseSortTag()/tag_name_parse_i() が StringIsEqualIgnoreCase/大文字小文字
# 非依存であり、これは既存の mopidy_mpd 実装(_SORT_MAPPING.get(type_.lower())
# 等)と一致している。ズレているのはキーワード自身の判定のみ。
#
# 同一原因(キーワード比較への誤った .lower() 適用)・同一修正形(.lower() を
# 削除するだけ)が sort/window/group/position の4種の修飾子・4ファイル・
# 計12箇所に横展開されていたため、mpdmetapositivetrust-patch.py と同様に
# 1パッチでまとめて修正する。

# --- mopidy_mpd/protocol/music_db.py -----------------------------------
p1 = "mopidy_mpd/protocol/music_db.py"
s1 = open(p1).read()

MARKER = "mpdmodifierkeywordcase-patch"
if MARKER in s1:
    print("modifier keyword case-sensitivity fix already present, skip")
else:
    # window (find/search/findadd/searchadd/searchaddpl の _mpd_extract_sort_params
    # と list_() の2箇所、テキストは完全に同一なので一括置換)
    old_window = '    if len(params) >= 2 and params[-2].lower() == "window":\n'
    new_window = '    if len(params) >= 2 and params[-2] == "window":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_window) == 2, f"old_window count={s1.count(old_window)}"
    s1 = s1.replace(old_window, new_window)

    # sort (_mpd_extract_sort_params)
    old_sort = '    if len(params) >= 2 and params[-2].lower() == "sort":\n'
    new_sort = '    if len(params) >= 2 and params[-2] == "sort":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_sort) == 1, f"old_sort count={s1.count(old_sort)}"
    s1 = s1.replace(old_sort, new_sort, 1)

    # position (findadd/searchadd, _mpd_extract_addpos_params)
    old_pos1 = '    if len(params) >= 2 and params[-2].lower() == "position":\n'
    new_pos1 = '    if len(params) >= 2 and params[-2] == "position":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_pos1) == 1, f"old_pos1 count={s1.count(old_pos1)}"
    s1 = s1.replace(old_pos1, new_pos1, 1)

    # position (searchaddpl)
    old_pos2 = '    if len(parameters) >= 2 and parameters[-2].lower() == "position":\n'
    new_pos2 = '    if len(parameters) >= 2 and parameters[-2] == "position":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_pos2) == 1, f"old_pos2 count={s1.count(old_pos2)}"
    s1 = s1.replace(old_pos2, new_pos2, 1)

    # group (list_() 用、複数連鎖対応 while ループ、_mpd_extract_group_params)
    old_group1 = '    while len(params) >= 2 and params[-2].lower() == "group":\n'
    new_group1 = '    while len(params) >= 2 and params[-2] == "group":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_group1) == 1, f"old_group1 count={s1.count(old_group1)}"
    s1 = s1.replace(old_group1, new_group1, 1)

    # group (count/searchcount 用、単発 if、_mpd_extract_single_group_param)
    old_group2 = '    if len(params) >= 2 and params[-2].lower() == "group":\n'
    new_group2 = '    if len(params) >= 2 and params[-2] == "group":  # mpdmodifierkeywordcase-patch\n'
    assert s1.count(old_group2) == 1, f"old_group2 count={s1.count(old_group2)}"
    s1 = s1.replace(old_group2, new_group2, 1)

    open(p1, "w").write(s1)
    print("patched music_db.py: sort/window/group/position 修飾子キーワードを大文字小文字を区別するよう修正")

# --- mopidy_mpd/protocol/current_playlist.py ----------------------------
p2 = "mopidy_mpd/protocol/current_playlist.py"
s2 = open(p2).read()

if MARKER in s2:
    print("current_playlist.py already patched, skip")
else:
    old_window = '    if len(params) >= 2 and params[-2].lower() == "window":\n'
    new_window = '    if len(params) >= 2 and params[-2] == "window":  # mpdmodifierkeywordcase-patch\n'
    assert s2.count(old_window) == 1, f"old_window count={s2.count(old_window)}"
    s2 = s2.replace(old_window, new_window, 1)

    old_sort = '    if len(params) >= 2 and params[-2].lower() == "sort":\n'
    new_sort = '    if len(params) >= 2 and params[-2] == "sort":  # mpdmodifierkeywordcase-patch\n'
    assert s2.count(old_sort) == 1, f"old_sort count={s2.count(old_sort)}"
    s2 = s2.replace(old_sort, new_sort, 1)

    open(p2, "w").write(s2)
    print("patched current_playlist.py: playlistfind/playlistsearch の sort/window 修飾子キーワードを大文字小文字を区別するよう修正")

# --- mopidy_mpd/protocol/stickers.py -------------------------------------
p3 = "mopidy_mpd/protocol/stickers.py"
s3 = open(p3).read()

if MARKER in s3:
    print("stickers.py already patched, skip")
else:
    old_window = '        if len(tail) >= 2 and tail[-2].lower() == "window":\n'
    new_window = '        if len(tail) >= 2 and tail[-2] == "window":  # mpdmodifierkeywordcase-patch\n'
    assert s3.count(old_window) == 1, f"old_window count={s3.count(old_window)}"
    s3 = s3.replace(old_window, new_window, 1)

    old_sort = '        if len(tail) >= 2 and tail[-2].lower() == "sort":\n'
    new_sort = '        if len(tail) >= 2 and tail[-2] == "sort":  # mpdmodifierkeywordcase-patch\n'
    assert s3.count(old_sort) == 1, f"old_sort count={s3.count(old_sort)}"
    s3 = s3.replace(old_sort, new_sort, 1)

    open(p3, "w").write(s3)
    print("patched stickers.py: sticker find の sort/window 修飾子キーワードを大文字小文字を区別するよう修正")

# --- mopidy_mpd/protocol/stored_playlists.py ------------------------------
p4 = "mopidy_mpd/protocol/stored_playlists.py"
s4 = open(p4).read()

if MARKER in s4:
    print("stored_playlists.py already patched, skip")
else:
    old_window = '    if len(params) >= 2 and params[-2].lower() == "window":\n'
    new_window = '    if len(params) >= 2 and params[-2] == "window":  # mpdmodifierkeywordcase-patch\n'
    assert s4.count(old_window) == 1, f"old_window count={s4.count(old_window)}"
    s4 = s4.replace(old_window, new_window, 1)

    open(p4, "w").write(s4)
    print("patched stored_playlists.py: searchplaylist の window 修飾子キーワードを大文字小文字を区別するよう修正")
