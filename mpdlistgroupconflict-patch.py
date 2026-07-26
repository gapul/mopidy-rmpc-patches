# `list {TYPE} [FILTER] [group {GROUPTYPE}]...` の group 修飾チェーンに、主タグ (TYPE)
# 自身または既に指定済みの group と重複するタグを渡した場合 (例: `list album group album`,
# `list album group artist group artist`) に、mopidy_mpd (mpdlist-patch.py 由来の
# _mpd_extract_group_params/_mpd_list_grouped) が検証せず素通しし、同じ distinct 値の
# 階層をもう一段そのまま再帰してしまい `Album: X` のような行が重複して返る不具合
# (エラーにならず、件数も値も静かに壊れたレスポンスになる)。
# TODO/既知の残課題を全項目消化済みの自走エージェントが実 MPD 本体
# (MusicPlayerDaemon/MPD src/command/DatabaseCommands.cxx handle_list) を実際に
# gh api で fetch して発見・追加した項目。
#
# 確認した実 MPD の該当ロジック (DatabaseCommands.cxx, handle_list の group ループ内):
#   if (group == tagType ||
#       std::find(tag_types.begin(), tag_types.end(), group) != tag_types.end()) {
#       r.Error(ACK_ERROR_ARG, "Conflicting group");
#       return CommandResult::ERROR;
#   }
# つまり実 MPD は group タグが主タグ (tagType) と同じ、または既に集めた group 列に
# 既出の場合は即座に `ACK [2@0] {list} Conflicting group` で拒否し、1行も返さない。
# mopidy_mpd 側にはこのガードが無いため、同じフィールドで二重にネストし
# 「同一distinct値のグループヘッダ+その配下(=自分自身の再列挙)」という無意味かつ
# 実MPDと異なる出力になっていた。
#
# 修正: _mpd_extract_group_params 内で group 列同士の重複を検出し
# ACK_ERROR_ARG 相当の MpdArgError("Conflicting group") を送出。list_() 側では
# 主タグ (field) と group 列との重複も同様にチェックする (count/searchcount は
# 実MPDにそもそも主タグの概念が無くこのチェック対象外、mpdcount-patch.py 側は無変更)。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdlistgroupconflict-patch"
if MARKER in s:
    print("list group conflict guard already present, skip")
else:
    old_extract = '''def _mpd_extract_group_params(params):
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
'''
    assert s.count(old_extract) == 1, f"old_extract count={s.count(old_extract)}"

    new_extract = '''def _mpd_extract_group_params(params):
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
        field = _LIST_MAPPING.get(tag.lower())
        if field is None:
            raise exceptions.MpdArgError("Unknown tag type: %s" % tag)
        if field in groups:
            raise exceptions.MpdArgError("Conflicting group")
        groups.insert(0, field)
    return params, groups
'''
    s = s.replace(old_extract, new_extract, 1)

    old_list_extract_call = (
        "    params, group_fields = _mpd_extract_group_params(params)\n"
        "\n"
        "    query = None\n"
        "    if len(params) == 1 and params[0][:1] == \"(\":\n"
    )
    assert s.count(old_list_extract_call) == 1, (
        f"old_list_extract_call count={s.count(old_list_extract_call)}"
    )
    new_list_extract_call = (
        "    params, group_fields = _mpd_extract_group_params(params)\n"
        "    if field in group_fields:  # mpdlistgroupconflict-patch\n"
        "        raise exceptions.MpdArgError(\"Conflicting group\")\n"
        "\n"
        "    query = None\n"
        "    if len(params) == 1 and params[0][:1] == \"(\":\n"
    )
    s = s.replace(old_list_extract_call, new_list_extract_call, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: list group 修飾チェーンの主タグ/group間の重複を "
        "Conflicting group で拒否 (実MPD handle_listと同挙動)"
    )
