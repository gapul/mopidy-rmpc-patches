# `list TYPE ... group file` / `... group filename` (count/searchcountでも同様に
# `group file`/`group filename`) が、実MPDではACKになるべきなのに mopidy_mpd では
# 素通りして常に0件のOKを返してしまう不具合。
# TODO全項目消化済みの自走エージェントが (general-purposeサブエージェントへの
# 調査委任を経て) 新規発見した項目。BACKLOG.mdを
# grep -n -i "group file\|group filename\|_mpd_extract_group_params" で確認したが、
# _mpd_extract_group_params自体への既存言及(重複group検出/count・searchcountとの共有)
# はあるものの、"group file"/"group filename"という組み合わせを不具合として扱った
# 記述は無い。mpdlistfile-patch(直前のコミット)は list の TYPE 自体が file/filename の
# 場合の経路修正であり、今回の group 修飾子側は対応漏れとして残っていた。
#
# 原因: `_mpd_extract_group_params()` は group TAG を他のタグと同じ
# `_LIST_MAPPING.get(tag.lower())` で解決している。mpdlistfile-patch が
# `_LIST_MAPPING["file"/"filename"] = "uri"` を登録済みのため、group修飾子としての
# file/filenameもここを素通りしてしまう。素通り後は list_()→_mpd_list_grouped、
# count()/searchcount()→_mpd_count_grouped がいずれも
# context.core.library.get_distinct("uri", query) を呼ぶが、
# mopidy_ytmusic.library.get_distinct() は field が "artist"/"albumartist"/
# "album"/"date" の4分岐しか持たず "uri" はどれにも一致せず空のset()を返す。
# 結果、ACKにもならず常に0件のOKになる (ACKより気付きにくい「静かに0件」の不具合)。
#
# 確認した実MPD本体の該当ロジック (DatabaseCommands.cxx, gh apiで取得):
#   handle_list() の group 解析ループは tag_name_parse_i(s) で group タグ名を
#   解決する。これは src/tag/Names.cxx の tag_item_names_init (Artist/Album/
#   Title/…/MUSICBRAINZ_*等) に基づき、"File"/"Filename" は含まれていない。
#   一方 list の TYPE 引数側の file/filename特別扱い (handle_list_file への
#   分岐) は TYPE 解決専用であり、group 側の解決には一切適用されない。よって
#   実MPDでは `list album group file` は tag_name_parse_i("file") が
#   TAG_NUM_OF_ITEM_TYPES を返し ACK "Unknown tag type: file" になる。
#   handle_count_internal() も同じ tag_name_parse_i を使うため
#   `count FILTER group file` も同様にACKになる。
#
# 修正: _mpd_extract_group_params() で group TAG を _LIST_MAPPING で解決する前に
# tag.lower() が "file"/"filename" なら (list の主TYPE解決とは独立に)
# Unknown tag type で拒否する。list_()/count()/searchcount() が全てこの関数を
# 共有しているため、3コマンドまとめて実MPDと同じ挙動になる。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdlistgroupfile-patch"
if MARKER in s:
    print("group file/filename 拒否は既に適用済み、skip")
else:
    old_extract = '''    while len(params) >= 2 and params[-2].lower() == "group":
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
    assert s.count(old_extract) == 1, f"old_extract count={s.count(old_extract)}"

    new_extract = '''    while len(params) >= 2 and params[-2].lower() == "group":
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
    s = s.replace(old_extract, new_extract, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: list/count/searchcountのgroup file/filenameを "
        "Unknown tag typeで拒否 (get_distinct(\"uri\")が常に空を返していた不具合を修正)"
    )
