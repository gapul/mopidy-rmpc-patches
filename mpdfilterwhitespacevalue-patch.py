# find/search/count/findadd/searchadd/searchaddpl/playlistfind/playlistsearch/
# searchplaylist が共有するフィルタ式パーサ (`_query_from_mpd_filter_expression`/
# `_query_from_mpd_search_parameters`, music_db.py) は、mpdfilteremptyvalue-patch.py
# 適用後も「VALUE が空白のみ (例: `(TAG == "  ")`)」の節を一律 drop する挙動を
# 意図的にスコープ外として据え置いていた (同パッチ自身のコメント参照)。TODO
# 全項目消化済みのため自走エージェントが (general-purpose サブエージェントへの
# 調査委任を経て) 新規発見。
#
# 実MPD本体を gh raw で直接確認:
#   - src/song/Filter.cxx ExpectQuoted(): クォート文字列トークナイザはクォート内
#     の文字を1バイトずつそのままバッファへ積むだけで、内容への strip/trim は
#     一切行わない (StripLeft はトークン境界の空白飛ばしにのみ使われる)。
#   - src/song/StringFilter.hxx: `bool empty() const { return value.empty(); }`
#     — 純粋な長さ0チェック。空白のみの文字列は empty() == false。
# つまり空白のみの VALUE は実MPDでは「タグ不在マッチ」の特別扱い
# (TagSongFilter::Match の filter.empty() フォールバック) を受けない、通常の
# 非空文字列条件 (ほぼ確実に0件になるが正当なクエリ) である。mopidy_mpd は
# この節自体を黙って消し去るため、単独では `ACK incorrect arguments`、他条件
# と AND 併用時 (`(Composer == "  ") AND (Artist == "YOASOBI")`) はさらに悪く
# 条件が消えたまま黙って絞り込み漏れの結果を返す — mpdfilteremptyvalue-patch.py
# が真に空文字列について修正したのと全く同じ実害パターンが残っていた。
#
# **実装上の罠 (最初の実装が踏んだ)**: 空白のみの値を真っ先に単純に
# `query.setdefault(field, []).append(value)` (通常値と同じ経路) へ流すと、
# mopidy core 自体の `mopidy/internal/validation.py check_query()`
# (`_check_query_value`: `not isinstance(arg, str) or not arg.strip()` で
# ValidationError) が `core.library.search()`/`find_exact()` 呼び出し時に
# 例外を送出し、find/search/count 等が丸ごとクラッシュして接続が切れる
# (実機確認で `find "(Composer == \"  \")"` 送信直後に接続が無応答になる形で
# 再現、mopidy.log に `ValidationError: Expected "composer" to be list of
# strings, not '  '` のTracebackを確認)。よって真に空文字列と全く同じ理由
# (backendのqueryとしては送れない) で、空白のみの値も backend へは送らず
# ローカル判定専用に回す必要がある。
#
# 修正方針: 真に空文字列 (`value == ""`) と空白のみ (`not value.strip()`) は
# どちらも「backendのqueryへは送らずローカルpositive/negativeとしてのみ扱う」
# という同じ経路に統合する (`not value.strip()` は空文字列も包含するため
# 分岐自体が単純化される)。ローカル判定側
# (`_mpd_track_matches_positives`/`_mpd_track_excluded`、
# current_playlist.pyの独立複製`_pf_matches`) は無変更 — 既存の
# `needle == ""` 分岐が真に空文字列の場合のみ「タグ不在マッチ」の特別扱いを
# 行い、空白のみ (`needle == "  "` など、`needle == ""` には該当しない) は
# 自動的に通常の非空文字列比較経路 (real MPD の `filter.empty() == false` と
# 同じ挙動、タグ不在なら不一致) を通る。
#
# 実機確認 (TCP 6601、mopidy-ytmusic 実アカウント): mopidy_ytmusic の Track は
# composer を常に空で返すため、`(Composer == "  ") AND (Artist == "YOASOBI")`
# は修正前は Composer 節が消えて YOASOBI の全曲がヒットしていたが、修正後は
# 「Composer が文字列 "  " と一致する」条件を全曲が満たせず 0 件になることを
# 確認 (playlistfind 経由でも同型に確認)。単独条件 `find "(Composer == \"  \")"`
# は修正前 `ACK incorrect arguments`、修正後 `OK` (0件、クラッシュなし) に
# 変化することを確認。旧式構文 `find Composer "  "` も同型。回帰確認:
# `find "(Composer == \"\")"` (真に空文字列)、`find "(Album == \"  \")"`
# (通常フィールドでの空白のみ、0件になるが正当)、
# `find "(Artist == \"YOASOBI\")"` (無関係な既存クエリ) は無変更、
# mopidy.log に新規 ERROR/Traceback 0件、mopidy が正常に起動し続けることを
# 確認。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "mpdfilterwhitespacevalue-patch"
if MARKER in s:
    print("whitespace-only filter value support already present in music_db.py, skip")
else:
    # --- フィルタ式パーサ: 空白のみの `(TAG OP "  ")` を drop せず、
    #     backendのqueryへは送らずpositives/negativesへ積む ---
    old_expr = (
        "            if not field:\n"
        '                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")\n'
        "            if not value.strip() and value != \"\":\n"
        "                continue\n"
        "            _op_is_neg_token = op in (\"!=\", \"!~\") or op in _MPD_CS_CI_NEG_OPS\n"
    )
    assert s.count(old_expr) == 1, f"old_expr count={s.count(old_expr)}"
    new_expr = (
        "            if not field:\n"
        '                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")\n'
        "            # mpdfilterwhitespacevalue-patch: 空白のみの値もdropせず、\n"
        "            # 下のquery追加ガード(value.strip())でbackendへの送信のみ\n"
        "            # 抑止しpositives/negativesへは積む(real MPDのExpectQuotedは\n"
        "            # trimしないため空白のみも通常の非空値として扱う必要がある一方、\n"
        "            # mopidy core自体のvalidation.check_queryが空白のみのquery値を\n"
        "            # 拒否しクラッシュするためbackendへは送れない)。\n"
        "            _op_is_neg_token = op in (\"!=\", \"!~\") or op in _MPD_CS_CI_NEG_OPS\n"
    )
    s = s.replace(old_expr, new_expr, 1)

    old_expr_append = (
        "            if _op_is_neg_token != _neg_wrap:\n"
        "                negatives.append((field, _kind, value))\n"
        "            else:\n"
        "                if field not in _PHANTOM_TAG_FIELDS and value != \"\":\n"
        "                    query.setdefault(field, []).append(value)\n"
        "                positives.append((field, _kind, value))\n"
    )
    assert s.count(old_expr_append) == 1, f"old_expr_append count={s.count(old_expr_append)}"
    new_expr_append = (
        "            if _op_is_neg_token != _neg_wrap:\n"
        "                negatives.append((field, _kind, value))\n"
        "            else:\n"
        "                if field not in _PHANTOM_TAG_FIELDS and value.strip():\n"
        "                    query.setdefault(field, []).append(value)\n"
        "                positives.append((field, _kind, value))\n"
    )
    s = s.replace(old_expr_append, new_expr_append, 1)

    # --- 旧式 TAG/VALUE ペアパーサ: 真に空文字列/空白のみを同じ経路に統合 ---
    old_legacy = (
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
    assert s.count(old_legacy) == 1, f"old_legacy count={s.count(old_legacy)}"
    new_legacy = (
        "        value = parameters.pop(0)\n"
        "        if not value.strip():\n"
        "            # mpdfilterwhitespacevalue-patch: 真に空文字列/空白のみは\n"
        "            # どちらもbackendのqueryへは送れない(空文字列は実MPDの\n"
        "            # TagSongFilter::Match仕様上backendへ送る意味が無く、空白\n"
        "            # のみはmopidy core自体のvalidation.check_queryがValueError\n"
        "            # を送出しクラッシュするため)。backendへは送らずローカル\n"
        "            # positiveとしてのみ扱う(kind=exact、旧式構文に演算子は無い)。\n"
        "            # 真に空文字列/空白のみの区別は_mpd_track_matches_positives側の\n"
        "            # needle==\"\"分岐(タグ不在マッチの特別扱い)で実行時に自動的に\n"
        "            # 行われる(空白のみはneedle!=\"\"のため通常の非空値比較経路)。\n"
        "            _mpdbasefilter_positives.append((field, \"exact\", value))\n"
        "        else:\n"
        "            if field in _PHANTOM_TAG_FIELDS:\n"
        "                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う\n"
        "                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。\n"
        "                _mpdbasefilter_positives.append((field, \"exact\", value))\n"
        "            else:\n"
        "                query.setdefault(field, []).append(value)\n"
        "                _mpdtrailing_query.setdefault(field, []).append(value)\n"
    )
    s = s.replace(old_legacy, new_legacy, 1)

    open(p, "w").write(s)
    print("patched music_db.py: 空白のみのVALUEフィルタ節をdropせずローカル判定専用として扱う")
