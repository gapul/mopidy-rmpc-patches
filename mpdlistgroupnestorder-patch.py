# `list TYPE group G1 group G2 ...` のように group 修飾子を2組以上連鎖させた場合、
# mopidy_mpd (_mpd_extract_group_params/_mpd_list_grouped, mpdlist-patch.py由来) が
# 実MPDと逆順にネスト階層を組んでしまう不具合。TODO全項目消化済みのため自走エージェント
# が(general-purposeサブエージェントへの調査委任を経て)新規発見。rmpc本体
# (github.com/mierak/rmpc、rmpc-mpd/src/mpd_client.rs send_list_tag_grouped()/
# rmpc/src/ui/panes/tag_browser.rs queue_root_fetch()、`self.tags[0].group_by.len() > 1`
# のとき`group_tags`を複数連結して実際に`list TAG group G1 group G2`を発行する経路が
# 実装・テスト済みで、ユーザがBrowserペインのgroup_byを3段以上に設定すると到達する)
# が対象なので、rmpc互換レイヤとして実際に踏まれ得るコードパス。
#
# 実MPD本体 (gh rawでsrc/command/DatabaseCommands.cxx handle_list()を確認) の
# group 修飾子ループ:
#   while (args.size() >= 2 && StringIsEqual(args[args.size() - 2], "group")) {
#       ...
#       tag_types.emplace_back(group);   // 末尾から剥がしつつ「末尾に追加」
#       args.pop_back(); args.pop_back();
#   }
#   tag_types.emplace_back(tagType);
# 末尾から剥がした順(ワイヤ上の最後のgroup句が最初に剥がされる)にemplace_back(末尾
# 追加)するため、`list Album group AlbumArtist group Date`ではtag_types=
# [Date, AlbumArtist, Album]になる。src/db/DatabasePrint.cxx PrintUniqueTags()は
# tag_types.front()を最外周として使い、以降subspan(1)で再帰的に内側へ潜るため、
# 実MPDでの実際のネスト順は Date(最外周) → AlbumArtist → Album(最内周)。
#
# 一方mopidy_mpdの_mpd_extract_group_paramsは同じく末尾から剥がすが
# `groups.insert(0, field)`(先頭挿入)のため、剥がした順がそのままワイヤ上の記述順
# (先頭が先)に戻ってしまい、groups=[AlbumArtist, Date]になる。_mpd_list_grouped()は
# groups[0]を最外周として使うため、mopidyでの実際のネスト順は
# AlbumArtist(最外周) → Date → Album(最内周) — 実MPDと完全に逆順。
#
# 検証: デプロイ済み_mpd_extract_group_paramsをそのまま実行し
# (params=["group","albumartist","group","date"]) groups=['albumartist','date']
# (mopidyの最外周はalbumartist)を確認。実MPDのpop末尾+emplace_back(末尾追加)を
# そのまま再現した対照ロジックはtag_types=['date','albumartist','album']
# (実MPDの最外周はdate)を返し、両者のgroups[0]が一致しないことを確認済み
# (ytmusic実アカウントの保存済みライブラリが空でlist実データでの目視確認は不可
# だったため、パッチ適用対象そのものを直接実行するオフライン検証で確認)。
#
# BACKLOG.md全体を"insert(0"・"group"のネスト順・"tag_types.front"等で検索したが、
# 複数group句のネスト方向(最外周がワイヤ上の最初のgroupか最後のgroupか)を扱った
# 既存項目は見当たらず新規ギャップと判断した。mpdlistgroupconflict-patch.py(group列
# 同士の重複検出)・mpdlistgroupfile-patch.py(group file/filenameの拒否)は本件とは
# 別軸(重複判定・タグ名解決)で無関係。mpdcountsinglegroup-patch.py導入により
# count/searchcountは単一groupのみ(順序が問題になり得ない)なので対象外、影響は
# listのみ。
#
# 修正: groups.insert(0, field) を groups.append(field) に変更するだけで、末尾から
# 剥がした順(=実MPDのemplace_backと同じ順)がそのままgroupsの先頭から並ぶようになり、
# 実MPDのtag_types(groups部分)と一致する。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdlistgroupnestorder-patch"
if MARKER in s:
    print("list group 複数連鎖のネスト順序修正は既に適用済み、skip")
else:
    old_tail = '''        if field in groups:
            raise exceptions.MpdArgError("Conflicting group")
        groups.insert(0, field)
    return params, groups
'''
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"

    new_tail = '''        if field in groups:
            raise exceptions.MpdArgError("Conflicting group")
        groups.append(field)  # mpdlistgroupnestorder-patch
    return params, groups
'''
    s = s.replace(old_tail, new_tail, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: list の複数group連鎖(group G1 group G2 ...)の"
        "ネスト順序を実MPD (handle_list, tag_types.emplace_back) と同じ末尾group"
        "優先(最外周)に修正"
    )
