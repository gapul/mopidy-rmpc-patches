# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの調査
# 委任を経て)新規発見。フィルタ式 `(TAG OP "VALUE")` の演算子として実MPD本体
# (raw.githubusercontent.comでsrc/song/Filter.cxxを直接取得し確認、ParseStringFilter()の
# 12エントリのoperators配列)が受け付ける、コマンド単位のfold_case既定値(find=区別/
# search=非区別)を上書きする明示的な大文字小文字指定演算子 `eq_cs`/`eq_ci`/
# `contains_cs`/`contains_ci`/`starts_with_cs`/`starts_with_ci` とそれぞれの否定形
# `!eq_cs`/`!eq_ci`/`!contains_cs`/`!contains_ci`/`!starts_with_cs`/`!starts_with_ci`、
# および無印`contains`/`starts_with`の否定形`!contains`/`!starts_with`(同じくFilter.cxxに
# 実装あり)を、mopidy_mpdの`_query_from_mpd_filter_expression()`(music_db.py、
# find/search/count/searchcount/findadd/searchadd/searchaddpl/searchplaylist/
# playlistfind/playlistsearchが共有)が一切認識していなかった不具合を修正。
#
# 実害は「無視される」だけでは済まない: `op`が未知トークンだと
# `_MPD_POSITIVE_OP_KIND.get(op, "exact")`が黙って"exact"にフォールバックし、かつ
# `_op_is_neg_token = op in ("!=", "!~")`も否定形`!eq_cs`等を否定と認識しないため、
# 本来除外条件であるべき`(Artist !eq_cs "X")`が肯定条件`Artist == "X"`として扱われ、
# クエリの正負が完全に反転する(除外のつもりが逆に「Xのみ」に絞り込まれる)。ACKも
# 出ずサイレントに誤った結果を返す。
#
# 修正: `_MPD_POSITIVE_OP_KIND`にcs/ci演算子(と無印否定`!contains`/`!starts_with`)を
# 追加し新kind `exact_cs`/`exact_ci`/`contains_cs`/`contains_ci`/`starts_with_cs`/
# `starts_with_ci`として登録、`_op_is_neg_token`をこれらの否定トークン集合
# `_MPD_CS_CI_NEG_OPS`も見るよう拡張。後段フィルタ`_mpd_track_excluded`/
# `_mpd_track_matches_positives`(music_db.py)と`_pf_matches`
# (current_playlist.py、playlistfind/playlistsearch用の独自複製実装)双方に、
# 新kindをコマンド単位のcase_sensitive/strict既定値を無視して強制的に
# 大文字小文字区別/非区別する分岐を追加(strip_diacriticsは既存の共通前処理を
# そのまま踏襲、cs/ci判定はfold_caseのみを上書きしdiacritics除去には影響しない
# 実MPD仕様と一致)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_MPD_CS_CI_NEG_OPS"
if MARKER in s:
    print("filter cs/ci operators already patched in music_db.py, skip")
else:
    old_dict = (
        '_MPD_POSITIVE_OP_KIND = {\n'
        '    "==": "exact",\n'
        '    "contains": "contains",\n'
        '    "starts_with": "starts_with",\n'
        '    "=~": "regex",\n'
        "}"
    )
    assert s.count(old_dict) == 1, f"old_dict count={s.count(old_dict)}"
    new_dict = (
        '_MPD_POSITIVE_OP_KIND = {\n'
        '    "==": "exact",\n'
        '    "contains": "contains",\n'
        '    "starts_with": "starts_with",\n'
        '    "=~": "regex",\n'
        '    "!contains": "contains",\n'
        '    "!starts_with": "starts_with",\n'
        '    "eq_cs": "exact_cs",\n'
        '    "!eq_cs": "exact_cs",\n'
        '    "eq_ci": "exact_ci",\n'
        '    "!eq_ci": "exact_ci",\n'
        '    "contains_cs": "contains_cs",\n'
        '    "!contains_cs": "contains_cs",\n'
        '    "contains_ci": "contains_ci",\n'
        '    "!contains_ci": "contains_ci",\n'
        '    "starts_with_cs": "starts_with_cs",\n'
        '    "!starts_with_cs": "starts_with_cs",\n'
        '    "starts_with_ci": "starts_with_ci",\n'
        '    "!starts_with_ci": "starts_with_ci",\n'
        "}\n"
        "\n"
        "_MPD_CS_CI_NEG_OPS = frozenset({\n"
        '    "!contains",\n'
        '    "!starts_with",\n'
        '    "!eq_cs",\n'
        '    "!eq_ci",\n'
        '    "!contains_cs",\n'
        '    "!contains_ci",\n'
        '    "!starts_with_cs",\n'
        '    "!starts_with_ci",\n'
        "})"
    )
    s = s.replace(old_dict, new_dict, 1)

    old_negtoken = (
        '            _op_is_neg_token = op in ("!=", "!~")\n'
        '            _kind = "regex" if op in ("=~", "!~") else _MPD_POSITIVE_OP_KIND.get(op, "exact")\n'
    )
    assert s.count(old_negtoken) == 1, f"old_negtoken count={s.count(old_negtoken)}"
    new_negtoken = (
        '            _op_is_neg_token = op in ("!=", "!~") or op in _MPD_CS_CI_NEG_OPS\n'
        '            _kind = "regex" if op in ("=~", "!~") else _MPD_POSITIVE_OP_KIND.get(op, "exact")\n'
    )
    s = s.replace(old_negtoken, new_negtoken, 1)

    old_excl = (
        '        elif kind == "starts_with":\n'
        "            if case_sensitive:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return True\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return True\n"
        '        elif kind == "contains":\n'
        "            if case_sensitive:\n"
        "                if any(needle in v for v in values):\n"
        "                    return True\n"
        "            elif any(needle.lower() in v.lower() for v in values):\n"
        "                return True\n"
        "        elif case_sensitive:\n"
        "            if needle in values:\n"
        "                return True\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return True\n"
        "    return False\n"
    )
    assert s.count(old_excl) == 1, f"old_excl count={s.count(old_excl)}"
    new_excl = (
        '        elif kind == "starts_with":\n'
        "            if case_sensitive:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return True\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return True\n"
        '        elif kind == "contains":\n'
        "            if case_sensitive:\n"
        "                if any(needle in v for v in values):\n"
        "                    return True\n"
        "            elif any(needle.lower() in v.lower() for v in values):\n"
        "                return True\n"
        '        elif kind == "exact_cs":\n'
        "            if needle in values:\n"
        "                return True\n"
        '        elif kind == "exact_ci":\n'
        "            if needle.lower() in [v.lower() for v in values]:\n"
        "                return True\n"
        '        elif kind == "contains_cs":\n'
        "            if any(needle in v for v in values):\n"
        "                return True\n"
        '        elif kind == "contains_ci":\n'
        "            if any(needle.lower() in v.lower() for v in values):\n"
        "                return True\n"
        '        elif kind == "starts_with_cs":\n'
        "            if any(v.startswith(needle) for v in values):\n"
        "                return True\n"
        '        elif kind == "starts_with_ci":\n'
        "            if any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return True\n"
        "        elif case_sensitive:\n"
        "            if needle in values:\n"
        "                return True\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return True\n"
        "    return False\n"
    )
    s = s.replace(old_excl, new_excl, 1)

    old_pos = (
        '        elif kind == "starts_with":\n'
        "            if case_sensitive:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if case_sensitive:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        "    return True\n"
    )
    assert s.count(old_pos) == 1, f"old_pos count={s.count(old_pos)}"
    new_pos = (
        '        elif kind == "starts_with":\n'
        "            if case_sensitive:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if case_sensitive:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "exact_cs":\n'
        "            if needle not in values:\n"
        "                return False\n"
        '        elif kind == "exact_ci":\n'
        "            if needle.lower() not in [v.lower() for v in values]:\n"
        "                return False\n"
        '        elif kind == "contains_cs":\n'
        "            if not any(needle in v for v in values):\n"
        "                return False\n"
        '        elif kind == "contains_ci":\n'
        "            if not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_cs":\n'
        "            if not any(v.startswith(needle) for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_ci":\n'
        "            if not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        "    return True\n"
    )
    s = s.replace(old_pos, new_pos, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: フィルタ式のcs/ci明示的大文字小文字指定演算子"
        "(eq_cs/eq_ci/contains_cs/contains_ci/starts_with_cs/starts_with_ci、"
        "各否定形、無印!contains/!starts_with)をサポート"
    )

cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

CP_MARKER = "kind == \"exact_cs\""
if CP_MARKER in s_cp:
    print("filter cs/ci operators already patched in current_playlist.py, skip")
else:
    old_neg = (
        '        elif kind == "starts_with":\n'
        "            if strict:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if strict:\n"
        "                if any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        "        elif strict:\n"
        "            if needle in values:\n"
        "                return False\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return False\n"
        "    for field, kind, needle in positives:\n"
    )
    assert s_cp.count(old_neg) == 1, f"old_neg count={s_cp.count(old_neg)}"
    new_neg = (
        '        elif kind == "starts_with":\n'
        "            if strict:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if strict:\n"
        "                if any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "exact_cs":\n'
        "            if needle in values:\n"
        "                return False\n"
        '        elif kind == "exact_ci":\n'
        "            if needle.lower() in [v.lower() for v in values]:\n"
        "                return False\n"
        '        elif kind == "contains_cs":\n'
        "            if any(needle in v for v in values):\n"
        "                return False\n"
        '        elif kind == "contains_ci":\n'
        "            if any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_cs":\n'
        "            if any(v.startswith(needle) for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_ci":\n'
        "            if any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        "        elif strict:\n"
        "            if needle in values:\n"
        "                return False\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return False\n"
        "    for field, kind, needle in positives:\n"
    )
    s_cp = s_cp.replace(old_neg, new_neg, 1)

    old_pos = (
        '        elif kind == "starts_with":\n'
        "            if strict:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if strict:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        "    return True\n"
    )
    assert s_cp.count(old_pos) == 1, f"old_pos count={s_cp.count(old_pos)}"
    new_pos = (
        '        elif kind == "starts_with":\n'
        "            if strict:\n"
        "                if not any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        '        elif kind == "contains":\n'
        "            if strict:\n"
        "                if not any(needle in v for v in values):\n"
        "                    return False\n"
        "            elif not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "exact_cs":\n'
        "            if needle not in values:\n"
        "                return False\n"
        '        elif kind == "exact_ci":\n'
        "            if needle.lower() not in [v.lower() for v in values]:\n"
        "                return False\n"
        '        elif kind == "contains_cs":\n'
        "            if not any(needle in v for v in values):\n"
        "                return False\n"
        '        elif kind == "contains_ci":\n'
        "            if not any(needle.lower() in v.lower() for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_cs":\n'
        "            if not any(v.startswith(needle) for v in values):\n"
        "                return False\n"
        '        elif kind == "starts_with_ci":\n'
        "            if not any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        "    return True\n"
    )
    s_cp = s_cp.replace(old_pos, new_pos, 1)

    open(cp, "w").write(s_cp)
    print(
        "patched current_playlist.py: playlistfind/playlistsearchのフィルタ式へも"
        "同じcs/ci明示的大文字小文字指定演算子サポートを追加"
    )
