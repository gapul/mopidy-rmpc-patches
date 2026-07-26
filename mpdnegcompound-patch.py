# MPD 公式フィルタ式仕様 (mpd.readthedocs.io/protocol.html, Filters節) の
# `(!EXPRESSION)` (式全体の否定) は EXPRESSION が単一リーフに限らず
# `(EXPRESSION1 AND EXPRESSION2 ...)` という複合式そのものも対象にできる
# (ド・モルガンの法則、NOT(A AND B))。mpdnegexpr-patch.py が実装した
# `_neg_wrap` 検出は、クオート値を含むリーフ自身の直前の `(` の、さらに直前
# 1文字だけを見て `!` かどうか判定するため、`(!((A) AND (B)))` のように
# `!` とリーフの間に複合式自身の `(` が1つ余分に挟まる場合、各リーフの
# `_neg_wrap` は常に False のままになり、否定が黙って消えて肯定条件
# (`A AND B`)として扱われてしまう (サイレントな誤り)。TODO/既知の残課題を
# 全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実機確認 (127.0.0.1:6601、mopidy-ytmusic 実アカウント、YOASOBI「怪物」
# 22件ヒットする検索条件で確認): 修正前は
#   find "((Artist == \"YOASOBI\") AND (!((Title contains \"怪物\") AND (Title contains \"物\"))))"
# が、否定なしの
#   find "((Artist == \"YOASOBI\") AND ((Title contains \"怪物\") AND (Title contains \"物\")))"
# と全く同じ1件(「怪物」のみ)を返してしまう(本来は NOT(both) が真になる
# 残り21件が返るべき)。playlistfind (current_playlist.py の独自実装
# `_pf_matches`/`_query_from_mpd_search_parameters` 経由) でも同型の不具合を
# 再現。BACKLOG.md 全体を `_neg_wrap`/`!(` で検索したが、既存の mpdnegexpr-
# patch.py 自身の回帰テストは各リーフが個別に `!` を持つ形
# (`((A) AND (!(B)))`) のみで、複合式全体を1個の `!` でラップする形は
# 未検証・未修正と確認した。
#
# 修正方針: `_query_from_mpd_filter_expression` の現行アーキテクチャは
# 「フラットなリーフ条件リスト+AND」というモデルで、`!(...)` はリーフ単位
# でしか否定を扱えない (OR を持たない)。しかし NOT(A AND B) は「A と B が
# 両方真になったら除外」と等価であり、これは既存の `_mpd_track_matches_
# positives` 相当の「全リーフがANDで真か」を判定するロジックをそのまま
# 転用すれば OR を一切追加せずに正しく表現できる。そこで:
#   1. メインループの前に `!(` の出現位置を走査し、対応する閉じ括弧までの
#      中身を「同じ関数への再帰呼び出し」(`require_positive=False`) で
#      パースする。中身が単一リーフなら (positives 1件) 何もせず既存の
#      `_neg_wrap` ロジックに委ねる (ゼロ変更、回帰リスクを避ける)。
#   2. 中身が複数リーフ(AND、positives 2件以上)なら「複合否定グループ」と
#      判定し、その範囲を空白でマスクしてメインループから見えなくした上で、
#      グループのリーフ一覧を `negatives` へ `kind="and_group"` として追加。
#   3. 中身の再帰パースが `__mpd_negatives__` を返した場合 (中身に `!=`/
#      `!~` や入れ子の `!(...)` が混ざる、NOT(A AND NOT B) 相当のより複雑な
#      論理になるケース)は、誤った結果を静かに返すよりも安全側に倒し
#      `ACK incorrect arguments` にする (このパッチのスコープ外、既知の
#      境界として明示)。
# `_mpd_track_excluded`/`_pf_matches` (negatives 側) は kind="and_group" を
# 見たら「グループ内の全リーフが真になったら除外」という新ヘルパ
# `_mpd_group_all_match`/`_pf_group_all_match` で判定する。既存の
# `_mpd_track_matches_positives` を直接使わなかったのは、genre/track_no/
# date 等の「backend のベストエフォート結果を信頼して単独条件時は
# continue」というバイパス (mpdgenrepositivetrust-patch.py 等) が、否定
# グループの文脈では常に True (=常に除外) を意味してしまい不正確なため
# (バックエンド検索とは無関係にローカルでのみ評価する条件のため常に実値で
# 判定する必要がある)。
#
# 既知の境界 (スコープ外、意図的): 複合式全体の否定のみが単独で存在し他に
# 一切条件が無い場合 (`find "(!((A) AND (B)))"` 単体)、`require_positive`
# チェックが `negatives` の有無を見ないため `ACK incorrect arguments` に
# なる。これは単一リーフの否定 (`find "(!(Artist == \"X\"))"` 単体) も
# 修正前から同じ理由で ACK になる既存の(本パッチ範囲外の)境界であり、
# 新たな回帰ではない。実際の rmpc/mpc 等のクライアントは通常他の条件と
# AND で組み合わせて否定式を送るため実害は無い。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "_mpd_find_matching_close_paren"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    # --- 1. ヘルパ2つの新設 + `_query_from_mpd_filter_expression` 冒頭 ---
    old_head = r'''def _query_from_mpd_filter_expression(expr, mapping, require_positive=True):
    query = {}
    negatives = []
    positives = []
    has_base_positive = False
    idx = 0
    L = len(expr)
    while idx < L:
'''
    assert s.count(old_head) == 1, f"head anchor count={s.count(old_head)}"
    new_head = r'''def _mpd_find_matching_close_paren(expr, open_idx):
    """`expr[open_idx]` が `(` である前提で対応する閉じ括弧の位置を返す
    (クオート内の文字は無視、mpdnegcompound-patch)。見つからなければ -1。"""
    depth = 0
    i = open_idx
    L = len(expr)
    while i < L:
        c = expr[i]
        if c in "'\"":
            quote = c
            i += 1
            while i < L:
                if expr[i] == "\\" and i + 1 < L:
                    i += 2
                    continue
                if expr[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            if depth == 0:
                return i
            i += 1
            continue
        i += 1
    return -1


def _mpd_find_next_bang_open(expr, start):
    """`start` 以降で最初に見つかる `!(` (空白を挟んでもよい) の位置を
    `(bang_idx, open_idx)` で返す (クオート内は無視、mpdnegcompound-patch)。
    見つからなければ `(-1, -1)`。"""
    i = start
    L = len(expr)
    while i < L:
        c = expr[i]
        if c in "'\"":
            quote = c
            i += 1
            while i < L:
                if expr[i] == "\\" and i + 1 < L:
                    i += 2
                    continue
                if expr[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "!":
            k = i + 1
            while k < L and expr[k] in " \t":
                k += 1
            if k < L and expr[k] == "(":
                return i, k
        i += 1
    return -1, -1


def _query_from_mpd_filter_expression(expr, mapping, require_positive=True):  # mpdnegcompound-patch
    query = {}
    negatives = []
    positives = []
    has_base_positive = False
    # `(!( LEAF1 AND LEAF2 ... ))` (複合式全体の否定) を検出する。単一リーフ
    # (positives 1件のみ) の場合は何もせず下の既存 `_neg_wrap` ロジックに
    # 委ねる (ゼロ変更)。中身に否定演算子/入れ子の否定が混ざり安全に判定
    # できない場合は ACK にする (詳細はファイル冒頭のコメント参照)。
    _mpdnegcompound_group_negatives = []
    _mpdnegcompound_masked = list(expr)
    _mpdnegcompound_scan_pos = 0
    _mpdnegcompound_L0 = len(expr)
    while _mpdnegcompound_scan_pos < _mpdnegcompound_L0:
        _bang_idx, _open_idx = _mpd_find_next_bang_open(expr, _mpdnegcompound_scan_pos)
        if _bang_idx < 0:
            break
        _close_idx = _mpd_find_matching_close_paren(expr, _open_idx)
        if _close_idx < 0:
            break
        _inner_span = expr[_open_idx + 1:_close_idx]
        _mpdnegcompound_scan_pos = _close_idx + 1
        if not _inner_span.strip():
            continue
        _group_result = _query_from_mpd_filter_expression(
            _inner_span, mapping, require_positive=False
        )
        _group_positives = _group_result.get("__mpd_positives__", [])
        _group_inner_negatives = _group_result.get("__mpd_negatives__", [])
        if _group_inner_negatives:
            raise exceptions.MpdArgError("incorrect arguments")
        if len(_group_positives) < 2:
            continue
        for _i in range(_bang_idx, _close_idx + 1):
            _mpdnegcompound_masked[_i] = " "
        _mpdnegcompound_group_negatives.append(
            ("__group__", "and_group", _group_positives)
        )
    expr = "".join(_mpdnegcompound_masked)
    idx = 0
    L = len(expr)
    while idx < L:
'''
    s = s.replace(old_head, new_head, 1)

    # --- 2. 末尾: グループ negatives の合流 ---
    old_tail = r'''    if require_positive and not query and not has_base_positive and not positives:
        raise exceptions.MpdArgError("incorrect arguments")
    if negatives:
        query["__mpd_negatives__"] = negatives
    if positives:
        query["__mpd_positives__"] = positives
    return query
'''
    assert s.count(old_tail) == 1, f"tail anchor count={s.count(old_tail)}"
    new_tail = r'''    if require_positive and not query and not has_base_positive and not positives:
        raise exceptions.MpdArgError("incorrect arguments")
    negatives = negatives + _mpdnegcompound_group_negatives
    if negatives:
        query["__mpd_negatives__"] = negatives
    if positives:
        query["__mpd_positives__"] = positives
    return query
'''
    s = s.replace(old_tail, new_tail, 1)

    # --- 3. _mpd_track_excluded: kind="and_group" 判定を追加 ---
    old_excluded = r'''    のみ (stringnormalization、mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in negatives:
        if kind == "modified_since":
'''
    assert s.count(old_excluded) == 1, f"excluded anchor count={s.count(old_excluded)}"
    new_excluded = r'''    のみ (stringnormalization、mpdsearchdiacritics-patch.py)。"""
    for field, kind, needle in negatives:
        if kind == "and_group":
            # `(!( LEAF1 AND LEAF2 ... ))` (mpdnegcompound-patch)。needle は
            # グループ内リーフの (field, kind, value) タプルのリスト。
            # NOT(A AND B) は「A かつ B が両方真なら除外」と等価。
            if _mpd_group_all_match(track, needle, case_sensitive, strip_diacritics):
                return True
            continue
        if kind == "modified_since":
'''
    s = s.replace(old_excluded, new_excluded, 1)

    # --- 4. _mpd_group_all_match ヘルパ新設 (_mpd_track_excluded の直前) ---
    old_excluded_def = r'''def _mpd_track_excluded(track, negatives, case_sensitive, strip_diacritics=False):
'''
    assert s.count(old_excluded_def) == 1, f"excluded_def anchor count={s.count(old_excluded_def)}"
    new_excluded_def = r'''def _mpd_group_all_match(track, leaves, case_sensitive, strip_diacritics=False):
    """`(!( LEAF1 AND LEAF2 ... ))` (mpdnegcompound-patch) 用: グループ内の
    全リーフが真になるか (AND) を判定する。`_mpd_track_matches_positives` と
    違い、mopidy_ytmusicバックエンドのベストエフォート信頼バイパス
    (genre/track_no/date等の単独条件時continue) は適用しない — このグループ
    はバックエンド検索結果とは無関係にローカルでのみ評価される否定条件の
    構成要素であり、バイパスすると常にTrue(=常に除外)になり不正確なため、
    常に実値で判定する。"""
    for field, kind, needle in leaves:
        if kind == "modified_since":
            if not _mpd_since_matches(track.last_modified, needle):
                return False
            continue
        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if kind == "priority":
            if not (0 >= needle):
                return False
            continue
        if kind == "audio_format":
            if not _mpd_audio_format_matches(track.uri, needle):
                return False
            continue
        values = _mpd_negative_field_values(track, field)
        if not values:
            if needle == "":
                continue
            return False
        if strip_diacritics and kind != "base_dir":
            values = [_mpd_strip_diacritics(v) for v in values]
            needle = _mpd_strip_diacritics(needle)
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
            try:
                pattern = re.compile(needle, 0 if case_sensitive else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if case_sensitive:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if case_sensitive:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if case_sensitive:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
        elif kind == "exact_cs":
            if needle not in values:
                return False
        elif kind == "exact_ci":
            if needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "contains_cs":
            if not any(needle in v for v in values):
                return False
        elif kind == "contains_ci":
            if not any(needle.lower() in v.lower() for v in values):
                return False
        elif kind == "starts_with_cs":
            if not any(v.startswith(needle) for v in values):
                return False
        elif kind == "starts_with_ci":
            if not any(v.lower().startswith(needle.lower()) for v in values):
                return False
    return True


def _mpd_track_excluded(track, negatives, case_sensitive, strip_diacritics=False):
'''
    s = s.replace(old_excluded_def, new_excluded_def, 1)

    open(mp, "w").write(s)
    print(
        "patched music_db.py: フィルタ式 (!( LEAF1 AND LEAF2 ... )) "
        "(複合式全体の否定) が黙って無視され肯定条件として扱われる不具合を修正"
    )

# current_playlist.py の _pf_matches (playlistfind/playlistsearch、および
# stored_playlists.py の searchplaylist がこれを再利用) も
# _query_from_mpd_search_parameters 経由で同じ kind="and_group" を受け取るが
# 独自の negatives ループ (_pf_field_values ベース) しか持たないため、
# 同様に対応させる必要がある (mpdbasefilter-patch.py が
# _mpd_track_matches_positives/_pf_matches を別々に直したのと同じ
# クロスファイル重複)。
cp = "mopidy_mpd/protocol/current_playlist.py"
s_cp = open(cp).read()

MARKER_CP = "_pf_group_all_match"
if MARKER_CP in s_cp:
    print("current_playlist.py already patched, skip")
else:
    old_pf_negatives = r'''        if not matched:
            return False
    for field, kind, needle in negatives:
        if kind == "modified_since":
            if _mpd_since_matches(track.last_modified, needle):
                return False
            continue
'''
    assert s_cp.count(old_pf_negatives) == 1, f"pf_negatives anchor count={s_cp.count(old_pf_negatives)}"
    new_pf_negatives = r'''        if not matched:
            return False
    for field, kind, needle in negatives:
        if kind == "and_group":
            if _pf_group_all_match(track, needle, strict, strip_diacritics, priority):
                return False
            continue
        if kind == "modified_since":
            if _mpd_since_matches(track.last_modified, needle):
                return False
            continue
'''
    s_cp = s_cp.replace(old_pf_negatives, new_pf_negatives, 1)

    old_pf_matches_def = r'''def _pf_matches(
    track, query, strict, strip_diacritics=False, negatives=(), positives=(),
    priority=0,
):
'''
    assert s_cp.count(old_pf_matches_def) == 1, f"pf_matches_def anchor count={s_cp.count(old_pf_matches_def)}"
    new_pf_matches_def = r'''def _pf_group_all_match(track, leaves, strict, strip_diacritics, priority):
    """`(!( LEAF1 AND LEAF2 ... ))` (mpdnegcompound-patch) 用: music_db.py の
    `_mpd_group_all_match` と同じロジックを `_pf_field_values`/実キュー優先度
    (priority引数) 版で再実装する。priority は music_db.py 側と異なり実際の
    キュー優先度をそのまま使う(mpdprio-patch.py以来の非対称: DB検索には
    キュー優先度の概念が無く常に0扱いになる音楽ライブラリ側とは違い、
    playlistfind/playlistsearchは実際のtracklist上のtrackを見ているため)。"""
    for field, kind, needle in leaves:
        if kind == "modified_since":
            if not _mpd_since_matches(track.last_modified, needle):
                return False
            continue
        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if kind == "priority":
            if not (priority >= needle):
                return False
            continue
        if kind == "audio_format":
            if not _mpd_audio_format_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            if needle == "":
                continue
            return False
        if strip_diacritics and kind != "base_dir":
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
            try:
                pattern = re.compile(needle, 0 if strict else re.IGNORECASE)
            except re.error:
                continue
            if not any(pattern.search(v) for v in values):
                return False
        elif kind == "exact":
            if strict:
                if needle not in values:
                    return False
            elif needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "starts_with":
            if strict:
                if not any(v.startswith(needle) for v in values):
                    return False
            elif not any(v.lower().startswith(needle.lower()) for v in values):
                return False
        elif kind == "contains":
            if strict:
                if not any(needle in v for v in values):
                    return False
            elif not any(needle.lower() in v.lower() for v in values):
                return False
        elif kind == "exact_cs":
            if needle not in values:
                return False
        elif kind == "exact_ci":
            if needle.lower() not in [v.lower() for v in values]:
                return False
        elif kind == "contains_cs":
            if not any(needle in v for v in values):
                return False
        elif kind == "contains_ci":
            if not any(needle.lower() in v.lower() for v in values):
                return False
        elif kind == "starts_with_cs":
            if not any(v.startswith(needle) for v in values):
                return False
        elif kind == "starts_with_ci":
            if not any(v.lower().startswith(needle.lower()) for v in values):
                return False
    return True


def _pf_matches(
    track, query, strict, strip_diacritics=False, negatives=(), positives=(),
    priority=0,
):
'''
    s_cp = s_cp.replace(old_pf_matches_def, new_pf_matches_def, 1)

    open(cp, "w").write(s_cp)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch/searchplaylist "
        "が共有する _pf_matches() の (!( LEAF1 AND LEAF2 ... )) 不具合を修正"
    )
