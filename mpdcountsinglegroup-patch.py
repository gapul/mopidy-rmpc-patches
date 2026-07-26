# count/searchcountがgroup修飾子を`list`と全く同じ_mpd_extract_group_params()
# (末尾から`group TAG`対を繰り返し剥がすwhileループ、複数連鎖group対応)で解析して
# いるため、`count group artist group album`のように2組以上のgroupを渡しても
# ACKにならず素通りして誤ってネストしたcount結果を返してしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。BACKLOG.md:109-110は`count group album group artist`が
# 「album毎に正しくネスト」と記録し正常動作として扱っていたが、実MPD本体
# (gh rawでsrc/command/DatabaseCommands.cxx handle_count_internalを確認)は
# listと異なりwhileループではなく単一のif文でしかgroupを剥がさない:
#
#   TagType group = TAG_NUM_OF_ITEM_TYPES;
#   if (args.size() >= 2 && StringIsEqual(args[args.size() - 2], "group")) {
#       ...
#       args.pop_back();
#       args.pop_back();
#   }
#
# 2組目以降のgroupは剥がされずFILTER側に残るため、実MPDでは
# `count group artist group album`はSongFilter::Parse()が残った"group"トークンを
# 未知のフィルタ型として拒否し`ACK Unknown filter type: group`になる。
# mopidy_mpdは_mpd_extract_group_paramsをlist/count/searchcountで共有しているため
# listの正しい多段対応(list自体はネストしたgroup TAG...を実MPDでも複数受け付ける、
# handle_listのgroupループはwhile)がcount/searchcountにも誤って伝播していた。
#
# 修正: count/searchcount専用に単一group版の_mpd_extract_single_group_param()を
# 新設(if文、高々1組のみ剥がす、file/filename拒否はmpdlistgroupfile-patchと同様に
# 踏襲)し、count()/searchcount()の呼び出し元だけをこちらに差し替える。list()は
# 無変更(_mpd_extract_group_paramsのまま、正しく複数group対応を維持)。剥がされな
# かった2組目以降の"group X"はそのまま_query_from_mpd_search_parametersへ渡り、
# _SEARCH_MAPPINGに"group"キーが無いためMpdArgError("incorrect arguments")で
# ACKになる(実MPDと文言は異なるがACKで拒否する点は一致)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdcountsinglegroup-patch"
if MARKER in s:
    print("count/searchcount単一group制限は既に適用済み、skip")
else:
    old_func_anchor = '''def _mpd_extract_group_params(params):
    """末尾に並ぶ `group TAG` 対を取り除き、(残りの引数, group フィールド列) を返す。

    実クライアントは group を必ず末尾に置くため、末尾からのみ剥がす
    (フィルタ値がたまたま "group" だった場合の誤爆を避ける)。
    """
    # mpdlistgroupconflict-patch: 実MPD (DatabaseCommands.cxx handle_list) は
    # group 列に既出のタグが再度渡されると "Conflicting group" で拒否する。
    params = list(params)
    groups = []
    while len(params) >= 2 and params[-2].lower() == "group":
        tag = params.pop()
        params.pop()
        if tag.lower() in ("file", "filename"):  # mpdlistgroupfile-patch
            # 実MPD (Names.cxx tag_item_names_init) の group タグ名解決には
            # File/Filenameが無い (listのTYPE解決専用の特別扱いとは別経路)。
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        field = _LIST_MAPPING.get(tag.lower())
        if field is None:
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        if field in groups:
            raise exceptions.MpdArgError("Conflicting group")
        groups.insert(0, field)
    return params, groups
'''
    assert s.count(old_func_anchor) == 1, f"old_func_anchor count={s.count(old_func_anchor)}"

    new_func_anchor = old_func_anchor + '''

def _mpd_extract_single_group_param(params):  # mpdcountsinglegroup-patch
    """count/searchcount専用: 末尾の `group TAG` を高々1組だけ剥がす。

    実MPD (DatabaseCommands.cxx handle_count_internal) は list と異なり while
    ループではなく単一の if で末尾group1組のみを剥がすため、list/searchと共有の
    _mpd_extract_group_params (while ループ、複数連鎖group対応) を count/
    searchcount にそのまま使うと2組目以降のgroup句が剥がされずFILTER側に残り、
    実MPDならACKになるべきところを誤って素通りしてしまう。
    """
    params = list(params)
    if len(params) >= 2 and params[-2].lower() == "group":
        tag = params.pop()
        params.pop()
        if tag.lower() in ("file", "filename"):
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        field = _LIST_MAPPING.get(tag.lower())
        if field is None:
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        return params, [field]
    return params, []
'''
    s = s.replace(old_func_anchor, new_func_anchor, 1)

    old_count_call = '''    - use multiple tag-needle pairs to make more specific searches.
    """
    args, _group_fields = _mpd_extract_group_params(args)
    try:
        query = _query_from_mpd_search_parameters(
            args, _SEARCH_MAPPING, require_positive=not _group_fields
        )
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives,
        exact=_mpd_backend_search_exact(True, _positives),
    )
'''
    assert s.count(old_count_call) == 1, f"old_count_call count={s.count(old_count_call)}"
    new_count_call = old_count_call.replace(
        "args, _group_fields = _mpd_extract_group_params(args)",
        "args, _group_fields = _mpd_extract_single_group_param(args)  # mpdcountsinglegroup-patch",
    )
    s = s.replace(old_count_call, new_count_call, 1)

    old_searchcount_call = '''        be omitted).
    """
    args, _group_fields = _mpd_extract_group_params(args)
    try:
        query = _query_from_mpd_search_parameters(
            args, _SEARCH_MAPPING, require_positive=not _group_fields
        )
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    _negatives = _mpd_pop_negatives(query)
    _positives = _mpd_pop_positives(query)
    _strip_diacritics = "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False,
        strip_diacritics=_strip_diacritics, case_sensitive=False,
    )
'''
    assert s.count(old_searchcount_call) == 1, (
        f"old_searchcount_call count={s.count(old_searchcount_call)}"
    )
    new_searchcount_call = old_searchcount_call.replace(
        "args, _group_fields = _mpd_extract_group_params(args)",
        "args, _group_fields = _mpd_extract_single_group_param(args)  # mpdcountsinglegroup-patch",
    )
    s = s.replace(old_searchcount_call, new_searchcount_call, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: count/searchcountのgroupを高々1組に制限 "
        "(実MPD handle_count_internalと同挙動、2組目以降はACK incorrect arguments)"
    )
