# `status` 応答に `audio` (samplerate:bits:channels, 実際にデコード中のフォーマット)
# フィールドが一度も出力されない件: mopidy-mpd 3.3.0 の status.py はこのフィールドを
# 一切扱っていない (docstring に仕様の説明はあるが実装が無い)。
#
# rmpc 本体 (mierak/rmpc) を実際に clone して調査したところ、rmpc-mpd/src/commands/
# status.rs の `Status.audio` (status応答の "audio" キー専用パースフィールド) が
# 実際に `Status::samplerate()`/`bits()`/`channels()` (audio文字列を ":" 分割して
# パース) として使われており、rmpc/src/ui/panes/mod.rs の `StatusProperty::SampleRate()`/
# `Bits()`/`Channels()` (テーマでステータスバーに配置可能なプロパティ、
# rmpc/src/config/theme/properties.rs で定義) が実際にこの値を描画に使う実装と確認した。
# 既定のテーマ設定では使われないオプトイン機能だが、audio フィールドが常に欠落している
# 限り、ユーザーがテーマでこれらのプロパティを配置しても永久に空欄のままになる
# 実害あるギャップ。
#
# 実装: crossfade/mixrampdb と同じ流儀で translator.py にモジュールレベルの揮発性
# ストアを追加。値の書き込みは mopidy_mpd 側からは行わない (mopidy core 自体は
# 実際にデコード中の音声フォーマットを外部へ公開する仕組みを持たないため、decoders
# パッチと同種の限界)。代わりに ytaudioformat-patch.py (mopidy_ytmusic) が
# ストリーム解決 (yt-dlp) 時に判明した実際のサンプルレート/チャンネル数を書き込む
# (mopidy_ytmusic 拡張が無効な環境でも安全に動くよう、書き込み側は try/except で
# 本モジュールの import 失敗を許容する)。
#
# 既知の制約: bits (ビット深度) は yt-dlp の format 情報からは得られないため、
# GStreamer の一般的なデコード出力 (16-bit PCM) を仮定した固定値 "16" を使う
# (decoders パッチの静的プラグイン一覧と同種の割り切り。実際のパイプラインが
# 別のビット深度で出力していても、この値はそれを反映しない)。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_audio_format"
if MARKER_T in t:
    print("translator.py already patched (audio format store), skip")
else:
    anchor = "def get_playtime():\n    return int(_playtime_ms / 1000)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        anchor
        + "\n\n"
        + "# audio (status.py) 用の揮発性ストア。実 MPD の「デコーダが実際に出力している\n"
        + "# フォーマット」(samplerate:bits:channels) 相当。mopidy core 自体はこの情報を\n"
        + "# 外部へ公開しないため (decoders/mixrampdb と同種の限界)、ytaudioformat-patch.py\n"
        + "# (mopidy_ytmusic) がストリーム解決時に判明したサンプルレート/チャンネル数を書き込む。\n"
        + "_audio_format = None\n"
        + "\n"
        + "\n"
        + "def set_audio_format(value):\n"
        + "    global _audio_format\n"
        + "    _audio_format = value\n"
        + "\n"
        + "\n"
        + "def get_audio_format():\n"
        + "    return _audio_format\n"
    )
    t = t.replace(anchor, store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: audio format の揮発性ストアを追加")

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER_S = "_status_audio"
if MARKER_S in s:
    print("status.py already patched (audio field), skip")
else:
    old_duration_block = (
        '        duration = _status_duration(futures)\n'
        "        if duration is not None:\n"
        '            result.append(("duration", duration))\n'
        "    return result\n"
    )
    assert s.count(old_duration_block) == 1, f"old_duration_block count={s.count(old_duration_block)}"
    new_duration_block = (
        '        duration = _status_duration(futures)\n'
        "        if duration is not None:\n"
        '            result.append(("duration", duration))\n'
        "        audio_format = _status_audio(futures)\n"
        "        if audio_format:\n"
        '            result.append(("audio", audio_format))\n'
        "    return result\n"
    )
    s = s.replace(old_duration_block, new_duration_block, 1)

    old_tail = "def _status_mixrampdb(futures):\n    return translator.get_mixrampdb()\n"
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        old_tail
        + "\n\n"
        + "def _status_audio(futures):\n"
        + "    return translator.get_audio_format()\n"
    )
    s = s.replace(old_tail, new_tail, 1)

    open(sp, "w").write(s)
    print("patched status.py: audio (再生中のみ、値がある時だけ) フィールドを追加")
