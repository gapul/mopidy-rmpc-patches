# `list file [FILTER]` / `list filename [FILTER]` が、実MPDでは他のTYPE
# (artist/album等) と全く別の実装 (DatabaseCommands.cxx handle_list_file、
# フィルタに一致した曲の `file: <uri>` 行をそのまま列挙するPrintSongUris) に
# 分岐するのに対し、mopidy_mpd (mpdlist-patch.py由来のlist_()) は_LIST_MAPPING
# の "file"/"filename" → "uri" マッピングをそのまま他タグと同じ
# get_distinct("uri", query) 経路 (_mpd_list_grouped) に流し込んでしまう不具合。
# mopidy_ytmusic.library.get_distinct() は field が "artist"/"albumartist"/
# "album"/"date" の4分岐しか持たずfield=="uri"はどれにも一致しないため、
# `list file`/`list filename` は実データが存在してもACKにすらならず常に
# 空応答 (OKのみ) になっていた (ACKより気付きにくい「静かに0件」の不具合)。
# TODO全項目消化済みの自走エージェントが (general-purposeサブエージェントへの
# 調査委任を経て) 新規発見した項目。BACKLOG.mdを
# grep -n -i "list file\|list filename\|PrintSongUris\|handle_list_file"
# で確認したが既出の対応/blocked扱いは無い。
#
# 確認した実MPD本体の該当ロジック (DatabaseCommands.cxx):
#   CommandResult handle_list(...) {
#       const char *tag_name = args.shift();
#       if (StringEqualsCaseASCII(tag_name, "file") ||
#           StringEqualsCaseASCII(tag_name, "filename"))
#           return handle_list_file(client, args, r);
#       ... (window/groupの解析はここより後、file/filenameには一切適用されない)
#   }
#   static CommandResult handle_list_file(...) {
#       filter->Parse(args, false);  // 残り引数を通常のfind同様フィルタとして解釈
#       PrintSongUris(r, client.GetPartition(), filter.get());  // file: <uri> を列挙
#   }
# つまり file/filename は window/group を一切サポートせず (`list file group
# artist` は実MPDではフィルタ式として誤解釈されACKになる)、フィルタに一致した
# 曲のuriを (distinct集合化・ソート無しに) そのまま出力する。
#
# 修正: list_() で field解決直後、field=="uri" (=引数が file/filename) の
# 場合は group/window解析より前に分岐し、find()と同じフィルタパース
# (_query_from_mpd_search_parameters + negatives/positives) で一致した曲を
# 集め、"file"タグとしてuriのみ出力する専用ヘルパへ委譲する。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdlistfile-patch"
if MARKER in s:
    print("list file/filename 専用経路は既に適用済み、skip")
else:
    old_helper_anchor = "def _mpd_list_grouped(context, field, name, query, groups, window=None):"
    assert s.count(old_helper_anchor) == 1, f"old_helper_anchor count={s.count(old_helper_anchor)}"

    new_helper = (
        "def _mpd_list_file(context, params):  # mpdlistfile-patch\n"
        "    # 実MPD handle_list_fileと同じ: 残り引数をfind()同様のフィルタとして解釈し\n"
        "    # (group/window非対応、find()と同じエラー伝播)、一致した曲の\n"
        "    # file: <uri> をそのまま列挙する。\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return []\n"
        "    negatives = _mpd_pop_negatives(query)\n"
        "    positives = _mpd_pop_positives(query)\n"
        "    results = context.core.library.search(\n"
        "        query=query, exact=_mpd_backend_search_exact(True, positives)\n"
        "    ).get()\n"
        "    result_tracks = _get_tracks(results)\n"
        "    result_tracks = _mpd_filter_negatives(result_tracks, negatives, case_sensitive=True)\n"
        "    result_tracks = _mpd_filter_positives(result_tracks, positives, case_sensitive=True)\n"
        "    return [(\"file\", t.uri) for t in result_tracks]\n"
        "\n"
        "\n"
        + old_helper_anchor
    )
    s = s.replace(old_helper_anchor, new_helper, 1)

    old_dispatch = (
        "    field_arg = params.pop(0)\n"
        "    field = _LIST_MAPPING.get(field_arg.lower())\n"
        "    if field is None:\n"
        "        raise exceptions.MpdArgError(f\"Unknown tag type: {field_arg}\")\n"
        "\n"
        "    _list_window = None\n"
    )
    assert s.count(old_dispatch) == 1, f"old_dispatch count={s.count(old_dispatch)}"

    new_dispatch = (
        "    field_arg = params.pop(0)\n"
        "    field = _LIST_MAPPING.get(field_arg.lower())\n"
        "    if field is None:\n"
        "        raise exceptions.MpdArgError(f\"Unknown tag type: {field_arg}\")\n"
        "\n"
        "    if field == \"uri\":  # mpdlistfile-patch: file/filenameはgroup/window非対応の別経路\n"
        "        return _mpd_list_file(context, params)\n"
        "\n"
        "    _list_window = None\n"
    )
    s = s.replace(old_dispatch, new_dispatch, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: list file/filenameをPrintSongUris相当の専用経路へ分岐 "
        "(get_distinct(\"uri\")が常に空を返していた不具合を修正)"
    )
