# 実 MPD (MusicPlayerDaemon/MPD src/command/DatabaseCommands.cxx handle_list) の
# `list` コマンドは musicpd.org 仕様どおり
#   list {TYPE} {FILTER} [group {GROUPTYPE}] [window {START:END}]
# という文法で末尾の `window START:END` 修飾 (ページング) を受け付けるが、
# mopidy-mpd 3.3.0 (mpdlist-patch.py 適用後含む) の `list_()` はこれを一切
# 剥がさないため、`window` トークンがそのままフィルタ式のタグ名として
# `_query_from_mpd_search_parameters` に渡り `Unknown filter type` の ACK
# エラーになる (window 抜きでは通る有効な `list` 呼び出しが window を付けた
# だけで丸ごと失敗する)。TODO 全項目消化済みのため自走エージェントが実 MPD
# ソース (DatabaseCommands.cxx) を直接確認し新規発見・追加した項目。rmpc
# 本体 (mierak/rmpc) は現状 `list ... group ...` を window 無しでしか送って
# いないが (rmpc-mpd/src/mpd_client.rs send_list_tag_grouped)、rmpc の
# tag_browser ペイン (rmpc/src/ui/panes/tag_browser.rs) は任意個数の group
# tag を組み立てて送る汎用実装であり、musicpd.org 仕様に明記された正当な
# 呼び出しを送るクライアント全般に対する互換性ギャップとして修正する。
#
# 実 MPD の解析順序 (DatabaseCommands.cxx handle_list): 末尾2トークンが
# "window START:END" ならまずそれを剥がし、次に残りの末尾から "group TAG"
# 対を剥がす (つまり window は "group" 群よりさらに後ろに置く)。window は
# PrintUniqueTags の最外周(tag_types.front(); group 指定時はその一番外側の
# group、無指定時は TYPE 自体)のみに適用され、内側の階層は常に全件表示
# (RangeArg::All()) となる。
#
# mopidy-mpd 3.3.0 の music_db.py には mpdwindow-patch.py が追加した
# `_mpd_parse_window(value)` (window 値文字列 -> slice 変換、書式検証込み)
# が既にあるため、それを list 側でも再利用する。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpd_list_grouped(context, field, name, query, group_fields, _list_window)"
if MARKER in s:
    print("list window modifier support already present, skip")
else:
    old_list_body = '''    params, group_fields = _mpd_extract_group_params(params)

    query = None
    if len(params) == 1 and params[0][:1] == "(":
        query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)
    elif len(params) == 1:
        if field != "album":
            raise exceptions.MpdArgError('should be "Album" for 3 arguments')
        if params[0].strip():
            query = {"artist": params}
    else:
        try:
            query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)
        except exceptions.MpdArgError as exc:
            exc.message = "Unknown filter type"  # noqa B306: Our own exception
            raise
        except ValueError:
            return

    _mpd_pop_negatives(query)  # list はグループ化タグ値の列挙のため !=/!~ は対象外
    _mpd_pop_positives(query)  # 同様に演算子種別 (==/contains/starts_with/=~) も対象外
    name = _LIST_NAME_MAPPING[field]
    return _mpd_list_grouped(context, field, name, query, group_fields)
'''
    assert s.count(old_list_body) == 1, f"old_list_body count={s.count(old_list_body)}"

    new_list_body = '''    _list_window = None
    if len(params) >= 2 and params[-2].lower() == "window":
        _list_window = _mpd_parse_window(params[-1])
        params = params[:-2]

    params, group_fields = _mpd_extract_group_params(params)

    query = None
    if len(params) == 1 and params[0][:1] == "(":
        query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)
    elif len(params) == 1:
        if field != "album":
            raise exceptions.MpdArgError('should be "Album" for 3 arguments')
        if params[0].strip():
            query = {"artist": params}
    else:
        try:
            query = _query_from_mpd_search_parameters(params, _SEARCH_MAPPING)
        except exceptions.MpdArgError as exc:
            exc.message = "Unknown filter type"  # noqa B306: Our own exception
            raise
        except ValueError:
            return

    _mpd_pop_negatives(query)  # list はグループ化タグ値の列挙のため !=/!~ は対象外
    _mpd_pop_positives(query)  # 同様に演算子種別 (==/contains/starts_with/=~) も対象外
    name = _LIST_NAME_MAPPING[field]
    return _mpd_list_grouped(context, field, name, query, group_fields, _list_window)
'''
    s = s.replace(old_list_body, new_list_body, 1)

    old_grouped = '''def _mpd_list_grouped(context, field, name, query, groups):
    if not groups:
        values = context.core.library.get_distinct(field, query).get()
        return [(name, v) for v in sorted(v for v in values if v)]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_list_grouped(context, field, name, subquery, groups[1:])
        if sub:
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    assert s.count(old_grouped) == 1, f"old_grouped count={s.count(old_grouped)}"

    new_grouped = '''def _mpd_list_grouped(context, field, name, query, groups, window=None):
    # window (musicpd.org 仕様) は実 MPD の PrintUniqueTags 同様、最外周の階層
    # (group 指定時はその一番外側の group、無指定時は TYPE 自体) にのみ適用し、
    # 内側の階層 (再帰呼び出し) には渡さず常に全件を返す。
    if not groups:
        values = sorted(v for v in context.core.library.get_distinct(field, query).get() if v)
        if window is not None:
            values = values[window]
        return [(name, v) for v in values]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = sorted(v for v in context.core.library.get_distinct(gfield, query).get() if v)
    if window is not None:
        gvalues = gvalues[window]
    rows = []
    for gvalue in gvalues:
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_list_grouped(context, field, name, subquery, groups[1:])
        if sub:
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    s = s.replace(old_grouped, new_grouped, 1)

    open(p, "w").write(s)
    print("patched music_db.py: list の window 修飾をサポート")
