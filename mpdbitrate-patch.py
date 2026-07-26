# `status` 応答の `bitrate` (instantaneous bitrate in kbps) が mopidy-ytmusic での
# 実再生中も常に `0` を返してしまう件。status.py の `_status_bitrate()` は
# `current_tl_track.track.bitrate` (mopidy core標準の Track.bitrate フィールド)
# をそのまま返すが、mopidy_ytmusic/library.py の Track() 生成箇所は
# `bitrate=0` を無条件でハードコードしており、None(未知)ではなく確定値0を
# 返すため `_status_bitrate()` の `if ... is None: return 0` 分岐を経ずそのまま
# 0が返り続ける (詳細調査・実データ確認は対になる ytbitrate-patch.py 側参照)。
#
# 実装: mpdaudioformat-patch.py/mpdaudioformatpreload-patch.py が status の
# `audio` フィールド向けに確立した「translator.py にuriキー付き揮発性キャッシュを
# 持ち、status.py が現在曲のuriで引く。値の書き込みはmopidy_mpd側では行わず、
# 各バックエンド拡張(ytbitrate-patch.py等)に委ねる」という設計をそのまま
# bitrateへ横展開する。ただしaudioフォーマットは最初単一値ストアで実装し
# 後からgapless先読みレース対策でuriキー付きキャッシュへ改修する二度手間を
# 踏んだため (mpdaudioformatpreload-patch.py)、本パッチは最初からuriキー付き
# キャッシュとして実装し同じ手戻りを避ける。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_bitrate_cache"
if MARKER_T in t:
    print("translator.py already patched (bitrate cache), skip")
else:
    anchor = (
        "def get_song_audio_format(uri):\n"
        "    # status の audio フィールド/曲メタデータの Format タグ共用。\n"
        "    # 指定した曲(uri)が解決済みならその値(不明なら None)、未解決なら None。\n"
        "    if not uri:\n"
        "        return None\n"
        "    return _audio_format_cache.get(uri)\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    addition = (
        anchor
        + "\n\n"
        + "# status の bitrate (instantaneous bitrate, kbps) 用の揮発性ストア。\n"
        + "# _audio_format_cache と同じ設計 (曲(uri)ごとに別エントリ、古い順に破棄)。\n"
        + "# mopidy core 自体はこの情報を外部へ公開しないため、ytbitrate-patch.py\n"
        + "# (mopidy_ytmusic) がストリーム解決時に判明した実測ビットレートを書き込む。\n"
        + "_bitrate_cache = {}\n"
        + "_BITRATE_CACHE_MAX = 8\n"
        + "\n"
        + "\n"
        + "def set_song_bitrate(value, uri=None):\n"
        + "    if not uri:\n"
        + "        return\n"
        + "    _bitrate_cache[uri] = value\n"
        + "    while len(_bitrate_cache) > _BITRATE_CACHE_MAX:\n"
        + "        _bitrate_cache.pop(next(iter(_bitrate_cache)))\n"
        + "\n"
        + "\n"
        + "def get_song_bitrate(uri):\n"
        + "    # status の bitrate フィールド用。指定した曲(uri)が解決済みならその値\n"
        + "    # (不明なら None)、未解決なら None。\n"
        + "    if not uri:\n"
        + "        return None\n"
        + "    return _bitrate_cache.get(uri)\n"
    )
    t = t.replace(anchor, addition, 1)
    open(tp, "w").write(t)
    print("patched translator.py: bitrate (status用) の曲(uri)ごとの揮発性キャッシュを追加")

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER_S = "get_song_bitrate"
if MARKER_S in s:
    print("status.py already patched (bitrate uses cache), skip")
else:
    OLD_S = (
        "def _status_bitrate(futures):\n"
        "    current_tl_track = futures[\"playback.current_tl_track\"].get()\n"
        "    if current_tl_track is None:\n"
        "        return 0\n"
        "    if current_tl_track.track.bitrate is None:\n"
        "        return 0\n"
        "    return current_tl_track.track.bitrate\n"
    )
    assert s.count(OLD_S) == 1, f"OLD_S count={s.count(OLD_S)}"
    NEW_S = (
        "def _status_bitrate(futures):\n"
        "    current_tl_track = futures[\"playback.current_tl_track\"].get()\n"
        "    if current_tl_track is None:\n"
        "        return 0\n"
        "    cached = translator.get_song_bitrate(current_tl_track.track.uri)\n"
        "    if cached is not None:\n"
        "        return cached\n"
        "    if current_tl_track.track.bitrate is None:\n"
        "        return 0\n"
        "    return current_tl_track.track.bitrate\n"
    )
    s = s.replace(OLD_S, NEW_S, 1)
    open(sp, "w").write(s)
    print(
        "patched status.py: bitrate をtranslatorの曲(uri)キャッシュ優先で返すよう修正 "
        "(mopidy_ytmusicのTrack.bitrate=0固定に隠れず実測値を反映)"
    )
