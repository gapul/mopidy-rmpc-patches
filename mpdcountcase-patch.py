# music_db.py の count()/searchcount() が共有する _mpd_count_grouped() が、両者に
# 対し無条件に case_sensitive=False をハードコードしており、count が本来持つべき
# 大文字小文字を区別する挙動(実MPD仕様: countはfind同様に区別、searchcountのみ
# searchと同様に区別しない)が実装されていない不具合。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントが(general-purposeサブエージェントへの調査委任を
# 経て)新規発見した項目。
#
# 実MPD本体(src/command/DatabaseCommands.cxx、gh apiで実際に取得し確認):
#   handle_count()        -> handle_count_internal(client, args, r, /*fold_case=*/false, false)
#   handle_searchcount()   -> handle_count_internal(client, args, r, /*fold_case=*/true, strip_diacritics)
# count は find と同じ大文字小文字を区別する厳密一致、searchcount のみ search と
# 同じ大文字小文字を区別しない一致、という非対称仕様。musicpd.org のドキュメントにも
# 「searchcount は FILTER が search と同様に大文字小文字を区別せずに一致する点を除き
# count と同じ」と明記されている。
#
# 本ファイルの find()/search() 自体は _mpd_filter_negatives/_mpd_filter_positives に
# それぞれ case_sensitive=True/False を正しく渡し分けている(mpdnegfilter-patch.py/
# mpdfilterkind-patch.py由来の規約)のに、_mpd_count_grouped() だけがこの規約から
# 漏れ、count 側の leaf 実装 (mpdfilterkind-patch.py/mpdsearchdiacritics-patch.py が
# 積み上げた現行実装) は両方の呼び出しで case_sensitive=False を直書きしたまま
# 据え置かれていた。
#
# 実害: フィルタ式 `(TAG OP "VALUE")` 1条件だけの count でも即座にこの経路を通る。
# ライブラリに実タグ `Artist: YOASOBI` の曲がある状態で
#   find  "(Artist == \"yoasobi\")"  -> 大小不一致のため 0件 (find は正しく区別)
#   count "(Artist == \"yoasobi\")"  -> 本来 find と同じ 0件のはずが、本バグにより
#                                        大小を無視して一致し songs: 1 を返してしまう
# find と count という兄弟コマンドが同一フィルタに対し矛盾した結果を返す。従来形式の
# `count artist "x" album "y"` (mpdfindmultitag-patch.py 由来の positives 経由) でも
# 同様に誤爆する。
#
# 修正方針: mpdsearchcount-patch.py(exact引数)/mpdsearchdiacritics-patch.py
# (strip_diacritics引数)と全く同じ流儀で、_mpd_count_grouped() に
# case_sensitive=True (デフォルト、実MPDのcountと一致) を追加し、group再帰へも
# 伝播。searchcount() 側だけ明示的に case_sensitive=False を渡す。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "case_sensitive=case_sensitive, strip_diacritics=strip_diacritics"
if MARKER in s:
    print("count case-sensitivity already wired, skip")
else:
    old_count_grouped = '''def _mpd_count_grouped(
    context, query, groups, negatives=(), positives=(), exact=True, strip_diacritics=False
):
    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=False, strip_diacritics=strip_diacritics
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=False, strip_diacritics=strip_diacritics
        )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_count_grouped(
            context, subquery, groups[1:], negatives, positives, exact, strip_diacritics
        )
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    assert s.count(old_count_grouped) == 1, f"old_count_grouped count={s.count(old_count_grouped)}"

    new_count_grouped = '''def _mpd_count_grouped(
    context, query, groups, negatives=(), positives=(), exact=True, strip_diacritics=False,
    case_sensitive=True,
):
    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
        )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
        subquery = dict(query or {})
        subquery[gfield] = [str(gvalue)]  # 数値タグ(disc/track)のint値でmopidy validationが落ちるのを回避
        sub = _mpd_count_grouped(
            context, subquery, groups[1:], negatives, positives, exact, strip_diacritics,
            case_sensitive,
        )
        if dict(sub).get("songs"):
            rows.append((gname, gvalue))
            rows.extend(sub)
    return rows
'''
    assert s.count(new_count_grouped) == 0
    s = s.replace(old_count_grouped, new_count_grouped, 1)

    old_searchcount_call = '''    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False,
        strip_diacritics=_strip_diacritics,
    )
'''
    assert s.count(old_searchcount_call) == 1, f"old_searchcount_call count={s.count(old_searchcount_call)}"
    new_searchcount_call = '''    return _mpd_count_grouped(
        context, query, _group_fields, _negatives, _positives, exact=False,
        strip_diacritics=_strip_diacritics, case_sensitive=False,
    )
'''
    s = s.replace(old_searchcount_call, new_searchcount_call, 1)

    open(p, "w").write(s)
    print("patched music_db.py: count() を実MPD仕様通り大文字小文字を区別するよう修正 (searchcountのみ従来通り区別しない)")
