# _query_from_mpd_search_parameters()は引数リストの先頭がフィルタ式
# ("(TAG == \"VALUE\")"等)の場合、parameters[0]だけを_query_from_mpd_filter_expression()
# へ渡してその戻り値を即returnしてしまい、parameters[1:]に残った引数を一切検証せず
# 無条件に無視してしまう不具合を修正 (find/search/count/searchcount/findadd/searchadd/
# searchaddpl/searchplaylist/playlistfind/playlistsearch全てが共有するこの関数の不具合)。
# mpdcountsinglegroup-patch.py検証時に実機で発覚し、BACKLOG.mdへ「次回以降の
# 自走エージェントへの申し送り」として明記されていた既知の残課題
# (TODO全項目消化済みのため過去の自走エージェントが発見・記録)。
#
# 具体例: count/searchcountは`_mpd_extract_single_group_param()`で末尾の
# `group TAG`を高々1組しか剥がさないため、`count "(Genre == \"Pop\")" group artist
# group album`のように2組目のgroupが残ると、剥がされなかった`["group","artist"]`が
# そのままこの関数に渡る。従来実装はparameters[0]が"("始まりだと判定した時点で
# 即returnするため、この残りの`["group","artist"]`は完全に読み捨てられOKになって
# しまっていた。
#
# 実MPD本体 (gh rawでsrc/song/Filter.cxxのSongFilter::Parse(std::span<const char
# *const> args, ...)を確認) は、フィルタ式(先頭"("トークン)を1つ消費した後も
# doループを継続し、残りの引数を旧来のTAG VALUEペアとして同じParse(tag, value)へ
# 渡す (未知タグは"Unknown filter type"で例外→ACK)。つまり実MPDはフィルタ式と
# 旧形式TAG VALUEペアの混在を許し、両方をANDで積み重ねる設計であり、フィルタ式が
# 「残り引数の唯一の要素であることを検証しない」のではなく「残り引数も同じ
# パーサでAND結合する」というのが正しい仕様。
#
# 修正: parameters[0]がフィルタ式の場合、消費してparameters[1:]が空ならこれまで
# 通り即returnする (通常経路は無変更)。空でなければ、フィルタ式の戻り値
# (__mpd_positives__/__mpd_negatives__を除いたquery本体)を種として、既存の旧形式
# TAG VALUEペアwhileループをその残り引数に対して実行しqueryへAND結合で積み増す。
# ループ内で未知タグ(例: "group")に遭遇すると既存の`raise
# exceptions.MpdArgError("incorrect arguments")`がそのまま働きACKになる
# (実MPDとACK文言は異なるが拒否する点はmpdcountsinglegroup-patch.pyのコメントと
# 同じく一致)。フィルタ式自身のpositives(__mpd_positives__、kind=exact/regex情報
# 付き)はそのまま温存し、末尾のTAG VALUEペア専用「複数フィールドが単一値のみなら
# ローカルAND検証を信頼する」ヒューリスティック(mpdfindmultitag-patch.py)は末尾
# ペアだけから独立して再計算する(混ぜるとkind情報を失ったり二重計上したりする
# ため)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdfilterexprtrailing-patch"
if MARKER in s:
    print("フィルタ式の残余引数無視バグ修正は既に適用済み、skip")
else:
    old_func = '''def _query_from_mpd_search_parameters(parameters, mapping, require_positive=True):
    parameters = list(parameters)
    if parameters and isinstance(parameters[0], str) and parameters[0][:1] == "(":
        return _query_from_mpd_filter_expression(
            parameters[0], mapping, require_positive=require_positive
        )
    query = {}
    _mpdbasefilter_positives = []
    while parameters:'''
    assert s.count(old_func) == 1, f"old_func count={s.count(old_func)}"

    new_func = '''def _query_from_mpd_search_parameters(parameters, mapping, require_positive=True):  # mpdfilterexprtrailing-patch
    parameters = list(parameters)
    _mpdexprfield_positives = []
    _mpdexprfield_negatives = []
    if parameters and isinstance(parameters[0], str) and parameters[0][:1] == "(":
        expr_query = _query_from_mpd_filter_expression(
            parameters.pop(0), mapping, require_positive=require_positive
        )
        if not parameters:
            return expr_query
        # 実MPD (song/Filter.cxx SongFilter::Parse) はフィルタ式を1つ消費した
        # 後も残り引数を旧形式TAG VALUEペアとして同じパーサへ渡しANDで積み
        # 重ねる。未知タグ(例: 剥がされなかった2組目以降のgroup)はここで
        # 下のwhileループがACKにする。
        _mpdexprfield_positives = expr_query.pop("__mpd_positives__", [])
        _mpdexprfield_negatives = expr_query.pop("__mpd_negatives__", [])
        query = expr_query
    else:
        query = {}
    _mpdbasefilter_positives = []
    _mpdtrailing_query = {}
    while parameters:'''
    s = s.replace(old_func, new_func, 1)

    old_loop_field_append = '''        value = parameters.pop(0)
        if value.strip():
            if field in _PHANTOM_TAG_FIELDS:
                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う
                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。
                _mpdbasefilter_positives.append((field, "exact", value))
            else:
                query.setdefault(field, []).append(value)
    _mpdfindmultitag_positives = [
        (f, "exact", v[0]) for f, v in query.items() if len(v) == 1
    ]
    if len(query) > 1 and len(_mpdfindmultitag_positives) == len(query):
        query["__mpd_positives__"] = _mpdfindmultitag_positives
    if _mpdbasefilter_positives:
        query["__mpd_positives__"] = (
            query.get("__mpd_positives__", []) + _mpdbasefilter_positives
        )
    return query'''
    assert s.count(old_loop_field_append) == 1, (
        f"old_loop_field_append count={s.count(old_loop_field_append)}"
    )

    new_loop_field_append = '''        value = parameters.pop(0)
        if value.strip():
            if field in _PHANTOM_TAG_FIELDS:
                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う
                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。
                _mpdbasefilter_positives.append((field, "exact", value))
            else:
                query.setdefault(field, []).append(value)
                _mpdtrailing_query.setdefault(field, []).append(value)
    # mpdfindmultitag-patchのヒューリスティックの母集団(信頼するかどうかの
    # 判定対象)は末尾TAG VALUEペア部分だけから独立して計算する(フィルタ式
    # 由来のフィールドを混ぜるとkind=exact/regex情報を失ったり同じ条件を
    # 二重計上したりするため)。ただし「信頼するか」のゲート自体は
    # queryの合計フィールド数(フィルタ式+末尾ペア)で判定する必要がある:
    # フィルタ式1個+末尾ペア1個の組み合わせでも合計2フィールドとなり、
    # backend側のelif連鎖(mpdfindmultitag-patch.pyのコメント参照、
    # mopidy_ytmusic.library.search()は"any"等が有れば他フィールドを
    # 無視する)が同じく起こり得るため、末尾ペアが1個だけでもローカルAND
    # 検証を信頼しないと末尾ペアの条件が実質無視されてしまう。
    _mpdfindmultitag_positives = [
        (f, "exact", v[0]) for f, v in _mpdtrailing_query.items() if len(v) == 1
    ]
    _mpdpositives = list(_mpdexprfield_positives)
    if (
        _mpdtrailing_query
        and len(query) > 1
        and len(_mpdfindmultitag_positives) == len(_mpdtrailing_query)
    ):
        _mpdpositives += _mpdfindmultitag_positives
    if _mpdbasefilter_positives:
        _mpdpositives += _mpdbasefilter_positives
    if _mpdpositives:
        query["__mpd_positives__"] = _mpdpositives
    if _mpdexprfield_negatives:
        query["__mpd_negatives__"] = _mpdexprfield_negatives
    return query'''
    s = s.replace(old_loop_field_append, new_loop_field_append, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: _query_from_mpd_search_parameters()がフィルタ式の"
        "残余引数を旧形式TAG VALUEペアとしてAND結合するよう修正 "
        "(実MPD SongFilter::Parseと同挙動、未知トークンはACK incorrect arguments)"
    )
