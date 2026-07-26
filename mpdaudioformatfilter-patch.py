# find/search/count/findadd/searchadd/searchaddpl/playlistfind/playlistsearchが
# 共有するフィルタ式パーサ (music_db.pyの_query_from_mpd_filter_expression()) が、
# 実MPD (gh rawでsrc/song/Filter.cxxを確認) の `AudioFormat` 疑似タグ
# (`(AudioFormat == "SAMPLERATE:BITS:CHANNELS")`/`(AudioFormat =~ "PATTERN")`、
# base/modified-since/added-since/prioと同じ枠組みの特殊擬似タグ)を一切認識しない
# 不具合。TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェント
# への調査委任を経て)新規発見。
#
# 実MPD本体 `src/song/Filter.cxx` の `ParseExpression()` は "AudioFormat" を
# `LOCATE_TAG_AUDIO_FORMAT` という base/modified-since/added-since/prioと同じ
# 特殊擬似タグ枠として認識する。演算子は `==` (完全一致、値に "*" は使えない) と
# `=~` (ワイルドカードマスク一致、各フィールドに "*" を使える) のみを許容し、他の
# 演算子はここで例外送出(`'==' or '=~' expected`)。値は `src/pcm/AudioParser.cxx`
# の `ParseAudioFormat()` で "SAMPLERATE:FORMAT:CHANNELS" (FORMATは"8"/"16"/"24"/
# "24_3"/"32"/"f"/"dsd"のいずれか) としてパースされる。`AudioFormatSongFilter::Match()`
# は `song.audio_format.IsDefined() && song.audio_format.MatchMask(value)`
# (`src/pcm/AudioFormat.hxx` の `MatchMask()`: マスク側で "*" (=未指定) の
# フィールドは常に一致、それ以外は実際の値と厳密一致。`==`はマスク成分が
# 存在しないため実質「全フィールド厳密一致」になる)。
#
# 現状の`_query_from_mpd_filter_expression()`は`len(parts)==1`(base/modified-since/
# added-since)と`len(parts)==2`でtagが"prio"の場合のみ特殊擬似タグとして処理し、
# それ以外は一般の`len(parts)>=2`分岐に落ちる。`(AudioFormat == "48000:16:2")`は
# `parts == ["AudioFormat", "=="]`(len==2)のため一般分岐に落ち、
# `mapping.get("audioformat")`が`None`のため`ACK Unknown filter type: AudioFormat`
# になる(実MPDなら該当曲があれば黙ってヒット、無ければ0件でOK)。
#
# 比較対象データは既にこのリポジトリにある: `translator.py`の`_audio_format_cache`/
# `get_song_audio_format(uri)`(mpdaudioformat-patch.py/ytaudioformat-patch.py/
# mpdaudioformatpreload-patch.py導入、status応答のFormatタグ/audioフィールドに
# 既に使われている、実再生時にyt-dlpが解決した"samplerate:16:channels"文字列、
# bitsは常に16固定の近似値であることは既知の制約として上記パッチで既に
# 受け入れ済みの横展開でしかなく新たな不整合ではない)を再利用する。
#
# 実機検証 (127.0.0.1:6601、mopidy-ytmusic実アカウント):
#   1. search any "YOASOBI"等で実トラックURIをadd→play、数秒再生してFormatキャッシュ
#      が埋まるのを待つ(mpdaudioformat-patch.py検証と同じ待ち)。
#   2. currentsongでFormat: <rate>:16:<channels>を確認。
#   3. find "(AudioFormat == \"<その値>\")" → 修正前は
#      ACK [2@0] {find} Unknown filter type: AudioFormat、修正後はその曲がヒットする
#      ことを確認。
#   4. find "(AudioFormat =~ \"<rate>:*:*\")"(ワイルドカードマスク)でも同様にヒット。
#   5. 未再生(Format未解決)の別トラックのuriに対する`playlistfind`は
#      audio_format未定義のためAudioFormat条件に常にマッチしないことを確認
#      (実MPDのIsDefined()==falseと同じ挙動)。
#
# BACKLOG.mdを`grep -n -i "audioformat\|audio_format\|AudioFormatSongFilter"`で
# 確認したが既存パッチ(mpdaudioformat-patch.py等、status/Formatタグ表示側)との
# 重複はなく、フィルタ式の疑似タグとしてのAudioFormatは未着手だった。
#
# 旧式`TAG VALUE`列挙構文(`find AudioFormat "..."`)への配線は行わない: 実MPD本体
# `SongFilter::Parse(tag_string, value, ...)`のswitchにも`LOCATE_TAG_AUDIO_FORMAT`
# のcaseが無く`default:`(通常タグ扱い、未定義に近い挙動)に落ちる — prioと全く同じ
# 非対称性(mpdpriofilter-patch.py参照)のため、本パッチもこれに倣い新式`(TAG OP
# "VALUE")`フィルタ式にのみ配線する。
mp = "mopidy_mpd/protocol/music_db.py"
s = open(mp).read()

MARKER = "_mpd_parse_audio_format_filter_value"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    # --- 1. 新式フィルタ式パーサ: `(AudioFormat OP "SAMPLERATE:FORMAT:CHANNELS")` ---
    old_expr_parts = '''        if len(parts) == 2 and parts[0].strip("\\"'").lstrip("(").lower() == "prio":
'''
    assert s.count(old_expr_parts) == 1, f"expr_parts anchor count={s.count(old_expr_parts)}"
    new_expr_parts = '''        if len(parts) == 2 and parts[0].strip("\\"'").lstrip("(").lower() == "audioformat":
            # 実MPD (Filter.cxx LOCATE_TAG_AUDIO_FORMAT/AudioFormatSongFilter) の
            # `(AudioFormat == "RATE:FORMAT:CH")`/`(AudioFormat =~ "PATTERN")`。
            # base/modified-since/prio と同じ特殊疑似タグ。
            _audioformat_value = _mpd_parse_audio_format_filter_value(parts[1], value)
            if _neg_wrap:
                negatives.append(("uri", "audio_format", _audioformat_value))
            else:
                positives.append(("uri", "audio_format", _audioformat_value))
            continue
        if len(parts) == 2 and parts[0].strip("\\"'").lstrip("(").lower() == "prio":
'''
    s = s.replace(old_expr_parts, new_expr_parts, 1)

    # --- 2. _mpd_parse_audio_format_filter_value / _mpd_audio_format_matches:
    # _mpd_parse_prio_filter_value の直後 ---
    old_helper_anchor = '''def _mpd_since_matches(last_modified_ms, since_epoch):
'''
    assert s.count(old_helper_anchor) == 1, f"helper anchor count={s.count(old_helper_anchor)}"
    new_helper_anchor = '''_MPD_AUDIO_FORMAT_SAMPLE_FORMATS = {"8", "16", "24", "24_3", "32", "f", "dsd"}


def _mpd_parse_audio_format_filter_value(op, raw_value):
    """`(AudioFormat OP "RATE:FORMAT:CH")` の OP/VALUE をパースする。実MPD
    (Filter.cxx LOCATE_TAG_AUDIO_FORMAT) は演算子 `==`(完全一致、"*"不可)/
    `=~`(ワイルドカードマスク、各フィールドに"*"可)のみを許容し、他はここで
    ACKにする。VALUEは AudioParser.cxx ParseAudioFormat() 相当 (RATE/CHは
    数字、FORMATは8/16/24/24_3/32/f/dsdのいずれか)。"""
    if op == "==":
        mask = False
    elif op == "=~":
        mask = True
    else:
        raise exceptions.MpdArgError("'==' or '=~' expected")
    parts = raw_value.split(":")
    if len(parts) != 3:
        raise exceptions.MpdArgError(f"Invalid audio format: {raw_value}")
    rate_s, format_s, channels_s = parts
    if not (mask and rate_s == "*") and not re.fullmatch(r"\\d+", rate_s):
        raise exceptions.MpdArgError("Failed to parse the sample rate")
    if not (mask and format_s == "*") and format_s not in _MPD_AUDIO_FORMAT_SAMPLE_FORMATS:
        raise exceptions.MpdArgError(f"Invalid sample format: {format_s}")
    if not (mask and channels_s == "*") and not re.fullmatch(r"\\d+", channels_s):
        raise exceptions.MpdArgError("Failed to parse the channel count")
    return (mask, rate_s, format_s, channels_s)


def _mpd_audio_format_matches(uri, needle):
    """`AudioFormatSongFilter::Match()`相当: `song.audio_format.IsDefined() and
    song.audio_format.MatchMask(value)`。translator.get_song_audio_format(uri)
    が未解決(None)の曲は常に不一致 (実MPDのIsDefined()==falseと同じ)。"""
    mask, rate_s, format_s, channels_s = needle
    actual = translator.get_song_audio_format(uri)
    if not actual:
        return False
    actual_parts = actual.split(":")
    if len(actual_parts) != 3:
        return False
    actual_rate, actual_format, actual_channels = actual_parts
    if not (mask and rate_s == "*") and actual_rate != rate_s:
        return False
    if not (mask and format_s == "*") and actual_format != format_s:
        return False
    if not (mask and channels_s == "*") and actual_channels != channels_s:
        return False
    return True


def _mpd_since_matches(last_modified_ms, since_epoch):
'''
    s = s.replace(old_helper_anchor, new_helper_anchor, 1)

    # --- 3. 後段フィルタ (music_db.py: find/search/count等) ---
    old_negatives = '''        if kind == "priority":
            if 0 >= needle:
                return True
            continue
        values = _mpd_negative_field_values(track, field)
'''
    assert s.count(old_negatives) == 1, f"negatives anchor count={s.count(old_negatives)}"
    new_negatives = '''        if kind == "priority":
            if 0 >= needle:
                return True
            continue
        if kind == "audio_format":
            if _mpd_audio_format_matches(track.uri, needle):
                return True
            continue
        values = _mpd_negative_field_values(track, field)
'''
    s = s.replace(old_negatives, new_negatives, 1)

    old_positives = '''        if kind == "priority":
            if not (0 >= needle):
                return False
            continue
        if field == "any":
'''
    assert s.count(old_positives) == 1, f"positives anchor count={s.count(old_positives)}"
    new_positives = '''        if kind == "priority":
            if not (0 >= needle):
                return False
            continue
        if kind == "audio_format":
            if not _mpd_audio_format_matches(track.uri, needle):
                return False
            continue
        if field == "any":
'''
    s = s.replace(old_positives, new_positives, 1)

    open(mp, "w").write(s)
    print("patched music_db.py: find/search/count等のフィルタに "
          "(AudioFormat \"==\"/\"=~\" \"RATE:FORMAT:CH\") 疑似タグを配線")

    # --- 4. current_playlist.py: playlistfind/playlistsearch/searchplaylist
    # が共有する _pf_matches() は独立実装のため、同じkind="audio_format"分岐を
    # 追加しないとどのelifにも一致せず素通り(無条件で「合格」扱い)になる。
    cp = "mopidy_mpd/protocol/current_playlist.py"
    s3 = open(cp).read()

    MARKER3 = "_mpd_parse_audio_format_filter_value"
    if MARKER3 in s3:
        print("current_playlist.py already patched, skip")
    else:
        old_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _SORT_MAPPING,
    _mpd_added_since_matches,
    _mpd_base_dir_matches,
'''
        assert s3.count(old_cp_import) == 1, f"cp_import anchor count={s3.count(old_cp_import)}"
        new_cp_import = '''from mopidy_mpd.protocol.music_db import (
    _SEARCH_MAPPING,
    _SORT_MAPPING,
    _mpd_added_since_matches,
    _mpd_audio_format_matches,
    _mpd_base_dir_matches,
'''
        s3 = s3.replace(old_cp_import, new_cp_import, 1)

        old_cp_negatives = '''        if kind == "priority":
            if priority >= needle:
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        assert s3.count(old_cp_negatives) == 1, f"cp_negatives anchor count={s3.count(old_cp_negatives)}"
        new_cp_negatives = '''        if kind == "priority":
            if priority >= needle:
                return False
            continue
        if kind == "audio_format":
            if _mpd_audio_format_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if not values:
            continue
        if strip_diacritics and kind != "base_dir":
'''
        s3 = s3.replace(old_cp_negatives, new_cp_negatives, 1)

        old_cp_positives = '''        if kind == "priority":
            if not (priority >= needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if strip_diacritics and kind != "base_dir":
'''
        assert s3.count(old_cp_positives) == 1, f"cp_positives anchor count={s3.count(old_cp_positives)}"
        new_cp_positives = '''        if kind == "priority":
            if not (priority >= needle):
                return False
            continue
        if kind == "audio_format":
            if not _mpd_audio_format_matches(track.uri, needle):
                return False
            continue
        values = _pf_field_values(track, field)
        if strip_diacritics and kind != "base_dir":
'''
        s3 = s3.replace(old_cp_positives, new_cp_positives, 1)

        open(cp, "w").write(s3)
        print("patched current_playlist.py: playlistfind/playlistsearch/searchplaylist "
              "が共有する _pf_matches() に (AudioFormat \"==\"/\"=~\" \"RATE:FORMAT:CH\") "
              "を配線")
