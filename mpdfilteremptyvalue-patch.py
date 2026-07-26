# find/search/count/findadd/searchadd/searchaddpl/playlistfind/playlistsearch/
# searchplaylist が共有するフィルタ式パーサ (`_query_from_mpd_filter_expression`/
# `_query_from_mpd_search_parameters`, music_db.py) と旧式 TAG/VALUE ペア構文
# (同じ2関数) は、`VALUE` が真に空文字列 (`(TAG == "")` / `find TAG ""`) の節を
# 一律 `if not value.strip(): continue` で黙って読み捨てる。TODO 全項目消化済み
# のため自走エージェントが (general-purpose サブエージェントへの調査委任を経て)
# 新規発見。
#
# 実MPD本体 (gh raw で src/song/TagSongFilter.cxx TagSongFilter::Match() を確認)
# は空文字列 VALUE を特別扱いせず通常通りパースし、`Match()` 側に明示的な
# フォールバック分岐を持つ:
#
#   if (type < TAG_NUM_OF_ITEM_TYPES && !visited_types[type]) {
#       ...
#       /* If the search criterion was not visited during the sweep through
#          the song's tag, it means this field is absent from the tag or
#          empty. Thus, if the searched string is also empty then it's a
#          match as well and we should return true. */
#       if (filter.empty())
#           return !filter.IsNegated();
#   }
#
# つまり `(TAG == "")` はタグが不在/空のトラックにマッチする正当なクエリで、
# `(TAG != "")` は逆にタグが実在するトラックにのみマッチする。mopidy_mpd の
# 現行実装はこの節自体を黙って消し去るため、単独では `ACK incorrect
# arguments` (positives が空になり mpdnegonlyfilter-patch.py のガードに
# かかる) になり、他条件と AND 併用時 (`(Composer == "") AND (Artist ==
# "YOASOBI")`) はさらに悪く、Composer 条件が消えたまま Artist 条件だけで
# 検索され黙って誤った(絞り込み漏れの)結果集合を返す。BACKLOG.md 全体を
# `value.strip`/`filter.empty`/`TagSongFilter`/`空文字列`/`IsNegated` 等で検索
# し、mpdfilterexprtagerr-patch.py 自身のコメントが「値が空文字列のケースは
# 本項目のスコープ外」と明示的に据え置いていた未対応項目と確認済み。
#
# 修正方針 (現行の positives/negatives 分離アーキテクチャに素直に載せる):
#   - パーサ: 空白のみの値 (`value.strip()` が偽だが `value != ""`) は従来
#     通り無条件 drop (この既存挙動は変更しない、スコープ外)。真に空文字列
#     (`value == ""`) の節だけ、backend への `query` dict には含めず (ytmusic
#     の text search に空文字列を渡す意味が無いため base/prio/audioformat
#     等の既存疑似タグと同じ扱い)、kind 付き positives/negatives へ積む。
#   - ローカル判定 (`_mpd_track_matches_positives`/`_mpd_track_excluded`,
#     `_pf_matches`): 該当フィールドの値が1つも無い (`_mpd_negative_field_values`
#     が空リスト、実MPDの `!visited_types[type]` 相当) 場合、needle が空文字列
#     なら real MPD の `filter.empty() -> !IsNegated()` に倣い「positives は
#     マッチ (continue)」「negatives は不一致 (exclude=True)」とする。needle が
#     非空の場合の既存挙動 (positives: 不一致で return False、negatives: continue
#     して除外しない、いずれも real MPD の非空 filter 時の `return
#     filter.IsNegated()` と整合済み・要検証で確認済み) は無変更。
#
# 実機確認 (TCP 6601、mopidy-ytmusic 実アカウント): mopidy_ytmusic の Track は
# composer を常に空で返す (既存コメント多数箇所参照) ため、`(Composer !=
# "") AND (Artist == "YOASOBI")` は修正前は Composer 節が消えて YOASOBI の
# 全曲がヒットしていたが、修正後は「Composer が実在する」という条件を全曲が
# 満たせず 0 件になることを確認 (`playlistfind`/`count` 等 backend 丸投げに
# 依存しない経路でも同型に確認)。オフライン単体テストで
# `_mpd_track_matches_positives`/`_mpd_track_excluded` を合成 Track (composer
# 空 / composer 実在の両方) に対して直接叩き、positives 側 (`Composer == ""`
# がタグ不在にマッチしタグ実在に不一致、逆に非空 needle は従来通り) も含め
# 全4象限 (values有/無 × needle空/非空) を確認済み。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "実MPDの`!visited_types[type]`相当"
if MARKER in s:
    print("empty-value filter clause support already present in music_db.py, skip")
else:
    # --- フィルタ式パーサ: `(TAG OP "")` を drop せず positives/negatives へ ---
    old_expr = (
        "            if not field:\n"
        '                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")\n'
        "            if not value.strip():\n"
        "                continue\n"
        "            _op_is_neg_token = op in (\"!=\", \"!~\") or op in _MPD_CS_CI_NEG_OPS\n"
    )
    assert s.count(old_expr) == 1, f"old_expr count={s.count(old_expr)}"
    new_expr = (
        "            if not field:\n"
        '                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")\n'
        "            if not value.strip() and value != \"\":\n"
        "                continue\n"
        "            _op_is_neg_token = op in (\"!=\", \"!~\") or op in _MPD_CS_CI_NEG_OPS\n"
    )
    s = s.replace(old_expr, new_expr, 1)

    old_expr_append = (
        "            if _op_is_neg_token != _neg_wrap:\n"
        "                negatives.append((field, _kind, value))\n"
        "            else:\n"
        "                if field not in _PHANTOM_TAG_FIELDS:\n"
        "                    query.setdefault(field, []).append(value)\n"
        "                positives.append((field, _kind, value))\n"
    )
    assert s.count(old_expr_append) == 1, f"old_expr_append count={s.count(old_expr_append)}"
    new_expr_append = (
        "            if _op_is_neg_token != _neg_wrap:\n"
        "                negatives.append((field, _kind, value))\n"
        "            else:\n"
        "                if field not in _PHANTOM_TAG_FIELDS and value != \"\":\n"
        "                    query.setdefault(field, []).append(value)\n"
        "                positives.append((field, _kind, value))\n"
    )
    s = s.replace(old_expr_append, new_expr_append, 1)

    # --- 旧式 TAG/VALUE ペアパーサ: `TAG ""` を drop せず positives へ ---
    old_legacy = (
        "        value = parameters.pop(0)\n"
        "        if value.strip():\n"
        "            if field in _PHANTOM_TAG_FIELDS:\n"
        "                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う\n"
        "                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。\n"
        "                _mpdbasefilter_positives.append((field, \"exact\", value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                _mpdtrailing_query.setdefault(field, []).append(value)\n"
    )
    assert s.count(old_legacy) == 1, f"old_legacy count={s.count(old_legacy)}"
    new_legacy = (
        "        value = parameters.pop(0)\n"
        "        if value == \"\":\n"
        "            # 実MPD (TagSongFilter::Match) 仕様: 真に空文字列の VALUE は\n"
        "            # タグ不在/空へのマッチという正当な条件。backendへは送らず\n"
        "            # ローカルpositiveとしてのみ扱う (kind=exact、旧式構文に\n"
        "            # 演算子は無い)。空白のみの値は対象外 (無条件drop、既存の\n"
        "            # strip()判定は無変更)。\n"
        "            _mpdbasefilter_positives.append((field, \"exact\", value))\n"
        "        elif value.strip():\n"
        "            if field in _PHANTOM_TAG_FIELDS:\n"
        "                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う\n"
        "                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。\n"
        "                _mpdbasefilter_positives.append((field, \"exact\", value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                _mpdtrailing_query.setdefault(field, []).append(value)\n"
    )
    s = s.replace(old_legacy, new_legacy, 1)

    # --- ローカル判定: positives 側 (タグ不在+空needleはマッチ扱い) ---
    old_positives_match = (
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            return False\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_mpd_strip_diacritics(v) for v in values]\n"
        "            needle = _mpd_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if not any(_mpd_base_dir_matches(needle, v) for v in values):\n"
    )
    assert s.count(old_positives_match) == 1, f"old_positives_match count={s.count(old_positives_match)}"
    new_positives_match = (
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            # 実MPDの`!visited_types[type]`相当 (タグ不在)。\n"
        "            # TagSongFilter::Match: filter.empty() -> !IsNegated() ->\n"
        "            # positives側では空needleのみマッチ扱い。\n"
        "            if needle == \"\":\n"
        "                continue\n"
        "            return False\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_mpd_strip_diacritics(v) for v in values]\n"
        "            needle = _mpd_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if not any(_mpd_base_dir_matches(needle, v) for v in values):\n"
    )
    s = s.replace(old_positives_match, new_positives_match, 1)

    # --- ローカル判定: negatives 側 (タグ不在+空needleは除外扱い) ---
    old_negatives_match = (
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_mpd_strip_diacritics(v) for v in values]\n"
        "            needle = _mpd_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return True\n"
    )
    assert s.count(old_negatives_match) == 1, f"old_negatives_match count={s.count(old_negatives_match)}"
    new_negatives_match = (
        "        values = _mpd_negative_field_values(track, field)\n"
        "        if not values:\n"
        "            # TagSongFilter::Match: filter.empty() -> !IsNegated() ->\n"
        "            # negatives側では空needleは不一致 (=除外対象)。\n"
        "            if needle == \"\":\n"
        "                return True\n"
        "            continue\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_mpd_strip_diacritics(v) for v in values]\n"
        "            needle = _mpd_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return True\n"
    )
    s = s.replace(old_negatives_match, new_negatives_match, 1)

    open(p, "w").write(s)
    print("patched music_db.py: 空文字列VALUEのフィルタ節をタグ不在マッチとして扱う")

# --- current_playlist.py 側: playlistfind/playlistsearch の _pf_matches も同じ複製 ---
cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

CP_MARKER = "TagSongFilter::Match: filter.empty()"
if CP_MARKER in s_cp:
    print("empty-value filter clause support already present in current_playlist.py, skip")
else:
    old_cp_negatives = (
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            continue\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return False\n"
    )
    assert s_cp.count(old_cp_negatives) == 1, f"old_cp_negatives count={s_cp.count(old_cp_negatives)}"
    new_cp_negatives = (
        "        values = _pf_field_values(track, field)\n"
        "        if not values:\n"
        "            # TagSongFilter::Match: filter.empty() -> !IsNegated() ->\n"
        "            # negatives側では空needleは不一致 (=マッチ全体が不成立)。\n"
        "            if needle == \"\":\n"
        "                return False\n"
        "            continue\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if kind == \"base_dir\":\n"
        "            if any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return False\n"
    )
    s_cp = s_cp.replace(old_cp_negatives, new_cp_negatives, 1)

    old_cp_positives = (
        "        values = _pf_field_values(track, field)\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if not values:\n"
        "            return False\n"
        "        if kind == \"base_dir\":\n"
        "            if not any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return False\n"
    )
    assert s_cp.count(old_cp_positives) == 1, f"old_cp_positives count={s_cp.count(old_cp_positives)}"
    new_cp_positives = (
        "        values = _pf_field_values(track, field)\n"
        "        if strip_diacritics and kind != \"base_dir\":\n"
        "            values = [_pf_strip_diacritics(v) for v in values]\n"
        "            needle = _pf_strip_diacritics(needle)\n"
        "        if not values:\n"
        "            # TagSongFilter::Match: filter.empty() -> !IsNegated() ->\n"
        "            # positives側では空needleのみマッチ扱い。\n"
        "            if needle == \"\":\n"
        "                continue\n"
        "            return False\n"
        "        if kind == \"base_dir\":\n"
        "            if not any(_mpd_base_dir_matches(needle, v) for v in values):\n"
        "                return False\n"
    )
    s_cp = s_cp.replace(old_cp_positives, new_cp_positives, 1)

    open(cp, "w").write(s_cp)
    print("patched current_playlist.py: _pf_matches に空文字列VALUEのタグ不在マッチを追加")
