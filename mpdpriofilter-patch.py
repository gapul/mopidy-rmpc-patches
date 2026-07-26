# playlistfind/playlistsearch(current_playlist.pyの_pf_search/_pf_matches)と
# find/search/count等(music_db.pyの_query_from_mpd_filter_expression)が共有
# するフィルタ式パーサが、実MPD (musicpd.org Filters節、gh apiでsrc/song/
# Filter.cxxも直接確認) の `prio` 疑似タグ (`(prio >= "N")`、キュー内の曲の
# 優先度でフィルタする) を一切認識しない不具合。TODO全項目消化済みのため
# 自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見した項目。
#
# 実MPD本体 `src/song/Filter.cxx` の `ParseExpression()` は "prio" を
# `LOCATE_TAG_PRIORITY` という base/modified-since と同じ枠組みの特殊擬似
# タグとして認識するが、base/modified-since と違い演算子を伴う
# (`s[0]=='>' && s[1]=='='` のみ許容、それ以外は `'>=' expected` で例外、
# ソース中のTODOコメントで他演算子は実MPD自身も未対応と明記)。値は
# 0-255の整数(`value > 0xff`ならエラー)。`src/song/PrioritySongFilter.cxx`
# の`Match()`は`song.priority >= value`。
#
# 現状の`_query_from_mpd_filter_expression()`は`len(parts)==1`の特殊タグ
# (base/modified-since/added-since)しか処理せず、`(prio >= "N")`は
# `parts == ["prio", ">="]`(len==2)のため一般の`len(parts)>=2`分岐に落ち、
# `mapping.get("prio")`が`None`のため`ACK Unknown filter type: prio`になる。
#
# 実機検証 (127.0.0.1:6601、mopidy-ytmusic実アカウント):
#   clear → add ytmusic:track:... (x2) → prioid "100" "1" (Id=1に優先度100)
#   → playlistid 1 で実際にPrio: 100が返ることを確認(prioid自体は既存実装で
#   正常動作、translator.py の _queue_priorities に実データが乗っている)。
#   その状態で `playlistfind "(prio >= \"50\")"` を送ると
#   `ACK [2@0] {playlistfind} Unknown filter type: prio` (実MPDならId=1の
#   曲が該当曲として返るはず)。
#
# 注意: `prio`は実MPDでもキュー限定の概念で、DB由来のLightSong(find/search
# 等の音楽データベース検索対象)は`Queue::GetLight()`を経由しないため
# `song.priority`は常にデフォルト値0のまま(実際に優先度を設定できるのは
# `prio`/`prioid`コマンドが操作するキュー内エントリのみ)。本パッチはこの
# 非対称性を忠実に再現する: current_playlist.py側(playlistfind/
# playlistsearch、実際のキューを検索)は translator.get_priority(tlid) の
# 実データで判定し、music_db.py側(find/search/count等、音楽データベースを
# 検索)は常に「優先度0」として判定する(`(prio >= "0")`は常に真、
# `(prio >= "1")`以上は常に偽になる、実MPDのLightSong既定値0と同じ)。
#
# また実MPD本体のソースでは、括弧無しの旧式`TAG VALUE`列挙構文
# (`SongFilter::Parse(tag_string, value, ...)`の switch)には
# `LOCATE_TAG_PRIORITY`のcaseが無く`default:`(通常タグ扱い、未定義に近い
# 挙動)に落ちる — base/modified-since/added-siteが明示的にcaseを持つのとは
# 非対称。本パッチもこれに倣い、旧式`_query_from_mpd_search_parameters()`の
# 逐次パーサ側には一切手を入れず、括弧付きフィルタ式`_query_from_mpd_filter_
# expression()`側にのみ配線する(旧式`find prio "50"`は従来通り
# `mapping.get("prio")`がNoneのままACKになる、実MPDの未定義に近い挙動より
# 安全な選択)。
#
# BACKLOG.mdをgrep -n -i "prio.*filter\|filter.*prio\|PrioritySongFilter\|
# LOCATE_TAG_PRIORITY\|prio >="で確認したが既出の対応/blocked扱いは無い
# (既存の"prio"/"prioid"関連エントリはコマンド自体の実装・TOCTOUレース
# 修正のみを扱っており、フィルタ式の疑似タグとしてのprioは未着手だった)。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "_mpd_parse_prio_filter_value"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    # --- 1. 新式フィルタ式パーサ: `(prio >= "N")` ---
    old_expr_parts = '''        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() in _MPD_SINCE_TAG_KINDS:
            # 実MPD (Filter.cxx LOCATE_TAG_MODIFIED_SINCE/LOCATE_TAG_ADDED_SINCE)
            # の `(modified-since "TIME")`/`(added-since "TIME")` も base と同じ
            # 演算子を取らない特殊フィルタ。不正な TIME 形式は実MPD同様ここで
            # ACKにする (ParseTimeStamp() 相当)。
            _since_tag = parts[0].strip("\\"'").lstrip("(").lower()
            _since_value = _mpd_parse_since_timestamp(value)
            _since_kind = _MPD_SINCE_TAG_KINDS[_since_tag]
            if _neg_wrap:
                negatives.append(("uri", _since_kind, _since_value))
            else:
                positives.append(("uri", _since_kind, _since_value))
            continue
        if len(parts) >= 2:
'''
    assert s.count(old_expr_parts) == 1, f"expr_parts anchor count={s.count(old_expr_parts)}"
    new_expr_parts = '''        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() in _MPD_SINCE_TAG_KINDS:
            # 実MPD (Filter.cxx LOCATE_TAG_MODIFIED_SINCE/LOCATE_TAG_ADDED_SINCE)
            # の `(modified-since "TIME")`/`(added-since "TIME")` も base と同じ
            # 演算子を取らない特殊フィルタ。不正な TIME 形式は実MPD同様ここで
            # ACKにする (ParseTimeStamp() 相当)。
            _since_tag = parts[0].strip("\\"'").lstrip("(").lower()
            _since_value = _mpd_parse_since_timestamp(value)
            _since_kind = _MPD_SINCE_TAG_KINDS[_since_tag]
            if _neg_wrap:
                negatives.append(("uri", _since_kind, _since_value))
            else:
                positives.append(("uri", _since_kind, _since_value))
            continue
        if len(parts) == 2 and parts[0].strip("\\"'").lstrip("(").lower() == "prio":
            # 実MPD (Filter.cxx LOCATE_TAG_PRIORITY/PrioritySongFilter) の
            # `(prio >= "N")`。base/modified-since と同じ特殊疑似タグだが、
            # 演算子`>=`だけは必須で残る (実MPD自身のTODOコメントで他演算子は
            # 未対応と明記、`>=`以外はここでACKにする)。
            _prio_value = _mpd_parse_prio_filter_value(parts[1], value)
            if _neg_wrap:
                negatives.append(("uri", "priority", _prio_value))
            else:
                positives.append(("uri", "priority", _prio_value))
            continue
        if len(parts) >= 2:
'''
    s = s.replace(old_expr_parts, new_expr_parts, 1)

    # --- 2. _mpd_parse_prio_filter_value: _mpd_parse_since_timestamp の直後 ---
    old_helper_anchor = '''def _mpd_since_matches(last_modified_ms, since_epoch):
'''
    assert s.count(old_helper_anchor) == 1, f"helper anchor count={s.count(old_helper_anchor)}"
    new_helper_anchor = '''def _mpd_parse_prio_filter_value(op, raw_value):
    """`(prio OP "VALUE")` の OP/VALUE をパースする。実MPD (Filter.cxx
    LOCATE_TAG_PRIORITY) は演算子 `>=` のみを受け付け (ソース中のTODOで他
    演算子は実MPD自身も未対応と明記)、VALUE は 0-255 の整数のみ
    (`uint8_t`、超えると `Invalid priority value` でACK)。"""
    if op != ">=":
        raise exceptions.MpdArgError("'>=' expected")
    if not re.fullmatch(r"\\d+", raw_value):
        raise exceptions.MpdArgError("Number expected")
    value = int(raw_value)
    if value > 255:
        raise exceptions.MpdArgError("Invalid priority value")
    return value


def _mpd_since_matches(last_modified_ms, since_epoch):
'''
    s = s.replace(old_helper_anchor, new_helper_anchor, 1)

    # --- 3. 後段フィルタ (DB検索対象): find/search/count等は音楽データベースの
    # Trackを見ており、mopidyのTrackモデルには優先度概念が無い。実MPDでも
    # DB由来のLightSongはQueue::GetLight()を経由しないためpriorityは常に
    # デフォルト値0 (Queue内エントリのみ実際の値を持つ) なので、常に0として
    # 判定する ((prio >= "0")は常に真、(prio >= "1")以上は常に偽)。---
    old_negatives = '''        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return True
            continue
        values = _mpd_negative_field_values(track, field)
'''
    assert s.count(old_negatives) == 1, f"negatives anchor count={s.count(old_negatives)}"
    new_negatives = '''        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return True
            continue
        if kind == "priority":
            if 0 >= needle:
                return True
            continue
        values = _mpd_negative_field_values(track, field)
'''
    s = s.replace(old_negatives, new_negatives, 1)

    old_positives = '''        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if field == "any":
'''
    assert s.count(old_positives) == 1, f"positives anchor count={s.count(old_positives)}"
    new_positives = '''        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if kind == "priority":
            if not (0 >= needle):
                return False
            continue
        if field == "any":
'''
    s = s.replace(old_positives, new_positives, 1)

    open(mp, "w").write(s)
    print("patched music_db.py: find/search/count等のフィルタに (prio \">=\" \"N\") "
          "疑似タグを配線 (DB検索対象は常に優先度0として判定)")

    # --- 4. current_playlist.py: playlistfind/playlistsearch は実際のキュー
    # (tlid付き) を検索するため、翻訳層の translator.get_priority(tlid) が
    # 持つ本物の優先度データで判定する。_pf_matches() に priority 引数を追加
    # し、呼び出し元の _pf_search() で tl_track.tlid から取得して渡す
    # (stored_playlists.py の searchplaylist() は tlid を持たないm3u曲を
    # 検索するため、既定値 priority=0 のまま _pf_matches() を呼び続ける ——
    # 実MPDでもプレイリスト内の曲はQueue優先度を持たないため正しい)。
    cp = "mopidy_mpd/protocol/current_playlist.py"
    s3 = open(cp).read()

    MARKER3 = "_mpd_parse_prio_filter_value"
    if MARKER3 in s3:
        print("current_playlist.py already patched, skip")
    else:
        old_cp_sig = '''def _pf_matches(
    track, query, strict, strip_diacritics=False, negatives=(), positives=()
):
'''
        assert s3.count(old_cp_sig) == 1, f"cp_sig anchor count={s3.count(old_cp_sig)}"
        new_cp_sig = '''def _pf_matches(
    track, query, strict, strip_diacritics=False, negatives=(), positives=(),
    priority=0,
):
'''
        s3 = s3.replace(old_cp_sig, new_cp_sig, 1)

        old_cp_negatives = '''        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        assert s3.count(old_cp_negatives) == 1, f"cp_negatives anchor count={s3.count(old_cp_negatives)}"
        new_cp_negatives = '''        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if kind == "priority":
            if priority >= needle:
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        s3 = s3.replace(old_cp_negatives, new_cp_negatives, 1)

        old_cp_positives = '''        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if strip_diacritics and kind != "base_dir":
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if not values:
            return False
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
'''
        assert s3.count(old_cp_positives) == 1, f"cp_positives anchor count={s3.count(old_cp_positives)}"
        new_cp_positives = '''        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if kind == "priority":
            if not (priority >= needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if strip_diacritics and kind != "base_dir":
            values = [_pf_strip_diacritics(v) for v in values]
            needle = _pf_strip_diacritics(needle)
        if not values:
            return False
        if kind == "base_dir":
            if not any(_mpd_base_dir_matches(needle, v) for v in values):
                return False
        elif kind == "regex":
'''
        s3 = s3.replace(old_cp_positives, new_cp_positives, 1)

        old_cp_call = '''    tl_tracks = context.core.tracklist.get_tl_tracks().get()
    matches = [
        (position, tl_track)
        for position, tl_track in enumerate(tl_tracks)
        if _pf_matches(
            tl_track.track, query, strict, strip_diacritics, negatives, positives
        )
    ]
'''
        assert s3.count(old_cp_call) == 1, f"cp_call anchor count={s3.count(old_cp_call)}"
        new_cp_call = '''    tl_tracks = context.core.tracklist.get_tl_tracks().get()
    matches = [
        (position, tl_track)
        for position, tl_track in enumerate(tl_tracks)
        if _pf_matches(
            tl_track.track, query, strict, strip_diacritics, negatives, positives,
            translator.get_priority(tl_track.tlid),
        )
    ]
'''
        s3 = s3.replace(old_cp_call, new_cp_call, 1)

        open(cp, "w").write(s3)
        print("patched current_playlist.py: playlistfind/playlistsearch が "
              "translator.get_priority(tlid) の実データで (prio \">=\" \"N\") を判定")
