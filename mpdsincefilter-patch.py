# find/search/count/findadd/searchadd/searchaddpl/searchplaylist/playlistfind/
# playlistsearch が共有するフィルタ式パーサ `_query_from_mpd_filter_expression()`/
# 旧式パーサ `_query_from_mpd_search_parameters()` (music_db.py) が、実MPD
# (musicpd.org protocol、Filters節、mpd.readthedocs.io に "(modified-since
# 'VALUE'): compares the file's time stamp with the given value (ISO 8601 or
# UNIX time stamp)." / "(added-since 'VALUE'): compares time stamp when the
# file was added with the given value" と明記) の `modified-since`/
# `added-since` 疑似タグを一切認識しない不具合。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントが(general-purposeサブエージェントへの調査
# 委任を経て)新規発見した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、gh apiで実際にソース取得し確認) の
# `src/song/Filter.cxx` の `ParseExpression()`/`SongFilter::Parse()` は
# `modified-since`/`added-since` を `base` (mpdbasefilter-patch.py で対応済み)
# と全く同じ枠組み — `LOCATE_TAG_MODIFIED_SINCE`/`LOCATE_TAG_ADDED_SINCE` と
# いう通常のタグ種別とは別の特殊擬似タグとして認識し、演算子を取らない単一の
# 引用値のみを受け取る (`(modified-since "TIME")`、legacy構文でも
# `find modified-since "TIME"` として同様に認識される)。対応する
# `ModifiedSinceSongFilter::Match()`/`AddedSinceSongFilter::Match()` は
# `song.mtime >= value` という以上判定 (>=) で、値はISO 8601かUNIX
# タイムスタンプの2形式を受け付ける (`ParseTimeStamp()`)。
#
# 現状の `_query_from_mpd_filter_expression()` は `base` 以外の単一トークン
# (`len(parts) == 1`) を一切処理しないため、`(modified-since "2020-01-01")`
# は `parts == ["modified-since"]` となりどのブロックにも一致せず完全に
# 素通りする。実害 (127.0.0.1:6601、mopidy-ytmusic 実アカウントで確認):
#   - `search "((artist contains \"Buzz\") AND (modified-since
#     \"2099-01-01\"))"` → 該当節が黙って無視され、`modified-since` 無しの
#     `search "(artist contains \"Buzz\")"` と全く同じ243件が返る
#     (静かな誤り、未来日付=本来0件になるべき条件が一切効いていない)。
#   - `modified-since`/`added-since` 単独指定 (`find "(modified-since
#     \"2020-01-01\")"`) は `query` が空のまま `require_positive` チェックに
#     引っかかり `ACK incorrect arguments` (実MPDでは正当な問い合わせとして
#     受理されるべき)。
# 旧式引数列パーサ (`find modified-since "TIME"`) 側も `mapping.get()` が
# 常に `None` になり同じく `ACK incorrect arguments` で拒否される。
#
# `translator.py` は既に `Added:` (get_or_stamp_library_added、MPDセッション内
# でこのuriを最初に返した近似時刻) と `Last-Modified:` (track.last_modified)
# の両方をレスポンスへ出力済みで、両疑似タグが必要とするデータは既に配線
# 済み — フィルタ式パーサ側が認識しないだけ。
#
# 本パッチは既存の negatives/positives 後段フィルタ機構 (mpdnegfilter-patch.py/
# mpdfilterkind-patch.py/mpdbasefilter-patch.py) に kind="modified_since"/
# "added_since" を追加する形で配線する。backend の `library.search()`/
# `get_distinct()` はこれらを理解しないため、query 本体には一切触れず、
# 必ず `__mpd_positives__`/`__mpd_negatives__` 経由のローカル後段フィルタ
# としてのみ効かせる (base_dir と同じ設計)。
#
# 既知の制約: `added-since` の比較対象 `Added:` はmopidyのTrackモデルに
# 「ライブラリへ追加された日時」という概念が無いための近似値 (このMPD
# セッションが最初にそのuriを返した時刻) であり、実MPDの「実際にファイルが
# 追加されたDB更新日時」とは意味が異なる (mpdlibraryadded-patch.py が
# `Added:` フィールド自体を追加した際に既に受け入れられている既知の制約の
# 横展開で、新たな不整合ではない)。BACKLOG.md を `grep -n
# "modified-since\|added-since\|AddedSince\|ModifiedSince"` で確認したが
# 既存パッチとの重複はない。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "_mpd_since_matches"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    # --- 0. datetime import (ISO 8601 / UNIX timestamp パース用) ---
    old_import = """import functools
import urllib
import itertools
import re

from mopidy.models import Track
from mopidy_mpd import exceptions, protocol, translator
"""
    assert s.count(old_import) == 1, f"import anchor count={s.count(old_import)}"
    new_import = """import datetime
import functools
import urllib
import itertools
import re

from mopidy.models import Track
from mopidy_mpd import exceptions, protocol, translator
"""
    s = s.replace(old_import, new_import, 1)

    # --- 1. 旧式引数列パーサ: `find modified-since "TIME"` ---
    old_legacy = '''        tag = parameters.pop(0).lower()
        if tag == "base":
            # base は通常のタグではなく特殊フィルタなので mapping を通さず、
            # 常にディレクトリ境界一致のpositiveとして積む(下記参照)。
            if not parameters:
                raise ValueError
            _mpdbasefilter_positives.append(("uri", "base_dir", parameters.pop(0)))
            continue
        field = mapping.get(tag)
'''
    assert s.count(old_legacy) == 1, f"legacy anchor count={s.count(old_legacy)}"
    new_legacy = '''        tag = parameters.pop(0).lower()
        if tag == "base":
            # base は通常のタグではなく特殊フィルタなので mapping を通さず、
            # 常にディレクトリ境界一致のpositiveとして積む(下記参照)。
            if not parameters:
                raise ValueError
            _mpdbasefilter_positives.append(("uri", "base_dir", parameters.pop(0)))
            continue
        if tag in _MPD_SINCE_TAG_KINDS:
            # modified-since/added-since も base と同様、演算子を取らない
            # 特殊フィルタ (下記フィルタ式パーサ側と同じ _mpd_parse_since_timestamp
            # で即座にパース、不正な形式ならここでACKにする)。
            if not parameters:
                raise ValueError
            _mpdbasefilter_positives.append(
                ("uri", _MPD_SINCE_TAG_KINDS[tag], _mpd_parse_since_timestamp(parameters.pop(0)))
            )
            continue
        field = mapping.get(tag)
'''
    s = s.replace(old_legacy, new_legacy, 1)

    # --- 2. 新式フィルタ式パーサ: `(modified-since "TIME")`/`(added-since "TIME")` ---
    old_expr_parts = '''        value = "".join(buf)
        idx = j + 1
        parts = head.split()
        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() == "base":
            # 実MPD (Filter.cxx LOCATE_TAG_BASE_TYPE/BaseSongFilter) の
            # `(base "DIR")` は演算子を取らない特殊フィルタで、fold_case
            # (find/searchの大小区別切り替え)の対象外に常に大小を区別する。
            if _neg_wrap:
                negatives.append(("uri", "base_dir", value))
            else:
                positives.append(("uri", "base_dir", value))
                has_base_positive = True
            continue
        if len(parts) >= 2:
'''
    assert s.count(old_expr_parts) == 1, f"expr_parts anchor count={s.count(old_expr_parts)}"
    new_expr_parts = '''        value = "".join(buf)
        idx = j + 1
        parts = head.split()
        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() == "base":
            # 実MPD (Filter.cxx LOCATE_TAG_BASE_TYPE/BaseSongFilter) の
            # `(base "DIR")` は演算子を取らない特殊フィルタで、fold_case
            # (find/searchの大小区別切り替え)の対象外に常に大小を区別する。
            if _neg_wrap:
                negatives.append(("uri", "base_dir", value))
            else:
                positives.append(("uri", "base_dir", value))
                has_base_positive = True
            continue
        if len(parts) == 1 and parts[0].strip("\\"'").lstrip("(").lower() in _MPD_SINCE_TAG_KINDS:
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
    s = s.replace(old_expr_parts, new_expr_parts, 1)

    # --- 3. _MPD_SINCE_TAG_KINDS / _mpd_parse_since_timestamp /
    # _mpd_since_matches / _mpd_added_since_matches: base_dir と同じ枠組みで
    # base_dir_matches の直前に追加する ---
    old_helpers_anchor = '''def _mpd_base_dir_matches(base_dir, uri):
    """`(base "DIR")` のディレクトリ境界判定。実MPD
'''
    assert s.count(old_helpers_anchor) == 1, f"helpers anchor count={s.count(old_helpers_anchor)}"
    new_helpers_anchor = '''_MPD_SINCE_TAG_KINDS = {
    "modified-since": "modified_since",
    "added-since": "added_since",
}


def _mpd_parse_since_timestamp(value):
    """`modified-since`/`added-since` の VALUE (ISO 8601 or UNIX timestamp、
    実MPD src/util/ParseTimeStamp.cxx 相当) をepoch秒(float)に変換する。
    パース不能なら実MPD同様ここでACKにする (MpdArgError)。"""
    value = value.strip()
    if re.fullmatch(r"-?\\d+", value):
        return float(value)
    iso_value = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        dt = datetime.datetime.fromisoformat(iso_value)
    except ValueError:
        raise exceptions.MpdArgError(f"Invalid timestamp: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _mpd_since_matches(last_modified_ms, since_epoch):
    """`modified-since` のMatch()相当。実MPD (ModifiedSinceSongFilter::Match)
    の `song.mtime >= value` と同じ以上判定。last_modified_ms は
    track.last_modified (mopidy Track標準、ミリ秒、無ければNone)。"""
    if last_modified_ms is None:
        return False
    return (last_modified_ms / 1000.0) >= since_epoch


def _mpd_added_since_matches(uri, since_epoch):
    """`added-since` 相当。translator.get_or_stamp_library_added() が返す
    近似 `Added:` (このMPDセッションが最初にuriを返した時刻) を比較に使う
    (mopidyのTrackモデルには実MPDの「DB追加日時」に相当する概念が無いための
    近似、mpdlibraryadded-patch.pyの `Added:` フィールドと同じ制約)。"""
    added_iso = translator.get_or_stamp_library_added(uri)
    if not added_iso:
        return False
    try:
        dt = datetime.datetime.strptime(added_iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return False
    return dt.timestamp() >= since_epoch


def _mpd_base_dir_matches(base_dir, uri):
    """`(base "DIR")` のディレクトリ境界判定。実MPD
'''
    s = s.replace(old_helpers_anchor, new_helpers_anchor, 1)

    # --- 4. 後段フィルタ: negatives/positives へ kind="modified_since"/
    # "added_since" の早期分岐を追加 (base_dir 同様、field="uri" プレース
    # ホルダのままだと文字列比較の一般ロジック(_mpd_negative_field_values
    # 経由)へ落ちてneedle(数値)に.lower()を呼び出しクラッシュするため、
    # 値取得より前に必ずbypassする) ---
    old_negatives = '''    for field, kind, needle in negatives:
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
    assert s.count(old_negatives) == 1, f"negatives anchor count={s.count(old_negatives)}"
    new_negatives = '''    for field, kind, needle in negatives:
        if kind == "modified_since":
            if _mpd_since_matches(track.last_modified, needle):
                return True
            continue
        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return True
            continue
        values = _mpd_negative_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
    s = s.replace(old_negatives, new_negatives, 1)

    old_positives = '''    for field, kind, needle in positives:
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
'''
    assert s.count(old_positives) == 1, f"positives anchor count={s.count(old_positives)}"
    new_positives = '''    for field, kind, needle in positives:
        if kind == "modified_since":
            if not _mpd_since_matches(track.last_modified, needle):
                return False
            continue
        if kind == "added_since":
            if not _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        if field == "any":
            continue  # backend の関連度マッチ (文字列一致を保証しない) を信頼する
'''
    s = s.replace(old_positives, new_positives, 1)

    open(mp, "w").write(s)
    print("patched music_db.py: find/search/count/findadd/searchadd/searchaddpl の"
          "フィルタに (modified-since \"TIME\")/(added-since \"TIME\") 疑似タグを配線")

    # --- 5. current_playlist.py: playlistfind/playlistsearch/searchplaylist が
    # 共有する _pf_matches() は music_db.py の _mpd_track_excluded/
    # _mpd_track_matches_positives とは別実装 (mpdbasefilter-patch.py が
    # base_dir 用に同種の分岐を追加済み) で、kind="modified_since"/
    # "added_since" を追加しないとどのelifにも一致せず素通り(無条件で
    # 「合格」扱い)になってしまう。
    cp = "mopidy_mpd/protocol/current_playlist.py"
    s3 = open(cp).read()

    MARKER3 = "_mpd_since_matches"
    if MARKER3 in s3:
        print("current_playlist.py already patched, skip")
    else:
        old_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _mpd_base_dir_matches,
    _mpd_extract_sort_params,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)'''
        assert s3.count(old_cp_import) == 1, f"cp_import anchor count={s3.count(old_cp_import)}"
        new_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _mpd_added_since_matches,
    _mpd_base_dir_matches,
    _mpd_extract_sort_params,
    _mpd_pop_negatives,
    _mpd_pop_positives,
    _mpd_since_matches,
    _mpd_sort_value,
    _query_from_mpd_search_parameters,
)'''
        s3 = s3.replace(old_cp_import, new_cp_import, 1)

        old_cp_negatives = '''    for field, kind, needle in negatives:
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        assert s3.count(old_cp_negatives) == 1, f"cp_negatives anchor count={s3.count(old_cp_negatives)}"
        new_cp_negatives = '''    for field, kind, needle in negatives:
        if kind == "modified_since":
            if _mpd_since_matches(track.last_modified, needle):
                return False
            continue
        if kind == "added_since":
            if _mpd_added_since_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        s3 = s3.replace(old_cp_negatives, new_cp_negatives, 1)

        old_cp_positives = '''    for field, kind, needle in positives:
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
        new_cp_positives = '''    for field, kind, needle in positives:
        if kind == "modified_since":
            if not _mpd_since_matches(track.last_modified, needle):
                return False
            continue
        if kind == "added_since":
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
        s3 = s3.replace(old_cp_positives, new_cp_positives, 1)

        open(cp, "w").write(s3)
        print("patched current_playlist.py: playlistfind/playlistsearch/searchplaylist "
              "が共有する _pf_matches() が (modified-since \"TIME\")/(added-since \"TIME\") "
              "を静かに無視する不具合を修正")
