# MPD 公式フィルタ式仕様 (mpd.readthedocs.io/protocol.html, Filters節) には
# `!=`/`!~` という否定演算子トークンとは別に、任意の式全体を丸ごと否定する
# `(!(EXPRESSION))` という構文があり、"which is equivalent to (artist != 'VALUE')"
# と明記されている (WebFetch で確認済み)。TODO 全項目消化済みのため自走エージェントが
# ソースを読んで新規発見した項目。
#
# mpdsearch-patch.py が追加した `_query_from_mpd_filter_expression`
# (mpdnegfilter-patch.py/mpdfilterkind-patch.py 適用後) は、クオート文字の直前の
# `(` を `rfind` で探して `TAG OP` を切り出す実装のため、`(!(artist == "X"))` の
# ような入力では内側の `(artist == "X")` だけを見つけて通常の肯定条件として扱い、
# 外側の `!` は一度もスキャンされず黙って無視される。つまり「Xというアーティストを
# 含まない」という意図のクエリが「Xというアーティストのみ」に反転してしまう
# (エラーにはならず `OK` で誤った結果を返すサイレントな不具合)。
# find/search/findadd/searchadd/searchaddpl/count/playlistfind/playlistsearch/
# searchplaylist が全て同じ `_query_from_mpd_filter_expression`
# (または current_playlist.py の `_pf_matches`) を経由するため同じ影響を受ける。
#
# 修正方針: `op_open` (`(` の位置) の直前 (空白を挟んでもよい) に `!` があるかを
# 見て `_neg_wrap` として記録し、演算子トークン自体が `!=`/`!~` かどうか
# (`_op_is_neg_token`) との XOR で最終的な否定有無を決める (`!(field != "x")` の
# ような二重否定も理屈通り肯定条件に潰れる)。kind (exact/contains/starts_with/regex)
# は演算子から一意に決まるため、mpdfilterkind-patch.py が positives 用に導入した
# `_MPD_POSITIVE_OP_KIND` をそのまま流用し、negatives 側も (field, is_regex, value)
# ではなく (field, kind, value) という同じ3要素形式に統一する (これまで `!=`/`!~`
# 由来の negatives は exact/regex の2種類しか表現できず、`!(tag contains "x")` の
# ような一般否定を後段フィルタで区別できなかったための統一)。この形式変更に伴い
# `_mpd_track_excluded` (music_db.py) と `_pf_matches` の negatives ループ
# (current_playlist.py、stored_playlists.py の searchplaylist もこれを再利用) を
# `_mpd_track_matches_positives`/positives ループと同じ4種判定に揃える。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_neg_wrap"
if MARKER in s:
    print("negated sub-expression !(...) support already present in music_db.py, skip")
else:
    old_loop = (
        '        op_open = expr.rfind("(", idx, qpos)\n'
        "        if op_open < 0:\n"
        "            idx = qpos + 1\n"
        "            continue\n"
        "        head = expr[op_open + 1:qpos]\n"
        "        quote = expr[qpos]\n"
    )
    assert s.count(old_loop) == 1, f"old_loop count={s.count(old_loop)}"
    new_loop = (
        '        op_open = expr.rfind("(", idx, qpos)\n'
        "        if op_open < 0:\n"
        "            idx = qpos + 1\n"
        "            continue\n"
        "        _neg_wrap = False\n"
        "        _k = op_open - 1\n"
        '        while _k >= idx and expr[_k] in " \\t":\n'
        "            _k -= 1\n"
        '        if _k >= idx and expr[_k] == "!":\n'
        "            _neg_wrap = True\n"
        "        head = expr[op_open + 1:qpos]\n"
        "        quote = expr[qpos]\n"
    )
    s = s.replace(old_loop, new_loop, 1)

    old_tail = (
        "        parts = head.split()\n"
        "        if len(parts) >= 2:\n"
        '            tag = parts[0].strip("\\"\'").lstrip("(")\n'
        "            op = parts[-1]\n"
        "            field = mapping.get(tag.lower())\n"
        "            if not field or not value.strip():\n"
        "                continue\n"
        '            if op in ("!=", "!~"):\n'
        '                negatives.append((field, op == "!~", value))\n'
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                kind = _MPD_POSITIVE_OP_KIND.get(op)\n"
        "                if kind:\n"
        "                    positives.append((field, kind, value))\n"
    )
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        "        parts = head.split()\n"
        "        if len(parts) >= 2:\n"
        '            tag = parts[0].strip("\\"\'").lstrip("(")\n'
        "            op = parts[-1]\n"
        "            field = mapping.get(tag.lower())\n"
        "            if not field or not value.strip():\n"
        "                continue\n"
        '            _op_is_neg_token = op in ("!=", "!~")\n'
        '            _kind = "regex" if op in ("=~", "!~") else _MPD_POSITIVE_OP_KIND.get(op, "exact")\n'
        "            if _op_is_neg_token != _neg_wrap:\n"
        "                negatives.append((field, _kind, value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                positives.append((field, _kind, value))\n"
    )
    s = s.replace(old_tail, new_tail, 1)

    old_excluded = (
        "def _mpd_track_excluded(track, negatives, case_sensitive):\n"
        '    """`!=`/`!~` (negatives) のいずれかにマッチしたら True (=結果から除外)。\n'
        "    実MPD仕様 (musicpd.org filter syntax): `!=` はタグの全値のいずれとも\n"
        "    一致しないことが条件を満たす条件 (=いずれか1つでも一致したら除外)。\n"
        "    `find`/`findadd` は大文字小文字を区別、`search`/`searchadd`/\n"
        '    `searchaddpl`/`count` は区別しない。"""\n'
        "    for field, is_regex, needle in negatives:\n"
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if is_regex:\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return True\n"
        "        elif case_sensitive:\n"
        "            if needle in values:\n"
        "                return True\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return True\n"
        "    return False\n"
    )
    assert s.count(old_excluded) == 1, f"old_excluded count={s.count(old_excluded)}"
    new_excluded = (
        "def _mpd_track_excluded(track, negatives, case_sensitive):\n"
        '    """`!=`/`!~`/`!(...)` (negatives) のいずれかにマッチしたら True\n'
        "    (=結果から除外)。実MPD仕様 (musicpd.org filter syntax): 否定条件は\n"
        "    タグの全値のいずれかと一致したら除外する。kind は positives と同じ\n"
        '    exact/contains/starts_with/regex。`find`/`findadd` は大文字小文字を\n'
        '    区別、`search`/`searchadd`/`searchaddpl`/`count` は区別しない。"""\n'
        "    for field, kind, needle in negatives:\n"
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if kind == \"regex\":\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return True\n"
        "        elif kind == \"starts_with\":\n"
        "            if case_sensitive:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return True\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return True\n"
        "        elif kind == \"contains\":\n"
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
    s = s.replace(old_excluded, new_excluded, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: フィルタ式の `(!(EXPRESSION))` (式全体の否定) を "
        "!=/!~ と同じ negatives 経路でサポート (kind付きに統一)"
    )

# current_playlist.py の _pf_matches (playlistfind/playlistsearch、および
# stored_playlists.py の searchplaylist がこれを再利用) も、negatives を
# (field, is_regex, value) 前提で読んでいるため同様に kind 対応させる。
cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

CP_MARKER = 'for field, kind, needle in negatives:'
if CP_MARKER in s_cp:
    print("negated sub-expression !(...) support already present in current_playlist.py, skip")
else:
    old_pf_negatives = (
        "    for field, is_regex, needle in negatives:\n"
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if is_regex:\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return False\n"
        "        elif strict:\n"
        "            if needle in values:\n"
        "                return False\n"
        "        elif needle.lower() in [v.lower() for v in values]:\n"
        "            return False\n"
    )
    assert s_cp.count(old_pf_negatives) == 1, f"old_pf_negatives count={s_cp.count(old_pf_negatives)}"
    new_pf_negatives = (
        "    for field, kind, needle in negatives:\n"
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics:\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if kind == \"regex\":\n"
        "            try:\n"
        "                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)\n"
        "            except re.error:\n"
        "                continue\n"
        "            if any(pattern.search(v) for v in values):\n"
        "                return False\n"
        "        elif kind == \"starts_with\":\n"
        "            if strict:\n"
        "                if any(v.startswith(needle) for v in values):\n"
        "                    return False\n"
        "            elif any(v.lower().startswith(needle.lower()) for v in values):\n"
        "                return False\n"
        "        elif kind == \"contains\":\n"
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
    )
    s_cp = s_cp.replace(old_pf_negatives, new_pf_negatives, 1)

    open(cp, "w").write(s_cp)
    print(
        "patched current_playlist.py: _pf_matches の negatives を kind (exact/"
        "contains/starts_with/regex) 対応に統一 (playlistfind/playlistsearch/"
        "searchplaylist)"
    )
