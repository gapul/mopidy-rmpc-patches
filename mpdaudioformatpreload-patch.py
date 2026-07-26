# mpdaudioformat-patch.py/mpdsongformat-patch.py が追加した status の `audio` /
# 曲メタデータの `Format` (samplerate:bits:channels) は、translator.py の単一値
# 揮発性ストア (`_audio_format`/`_audio_format_uri`、直近に解決した1曲分だけを
# 覚える設計) に依存している。だが mopidy core の gapless 先読み
# (`mopidy/core/playback.py` の `_on_about_to_finish()`、現在曲Aがまだ再生完了する
# 前に次曲Bの `backend.playback.change_track()` を呼ぶ) と、明示的な
# `play()`/`playid()` (`PlaybackController._change()`、`_pending_tl_track` に
# セットしてから `backend.playback.change_track()` → `play()` を呼ぶ) は、
# いずれも「実際に現在曲として確定する (`_current_tl_track` への昇格、
# `_on_stream_changed()` で行われる) 」より前に `change_track()` を呼ぶ。
# `mopidy_ytmusic/playback.py` の `_get_track()` (ytaudioformat-patch.py/
# ytaudioformatstale-patch.py) はこの `change_track()` の中で同期的に
# `set_audio_format(fmt, uri=B)` を呼ぶため、A がまだ実際に鳴っている間に
# ストアが B の値で上書きされてしまう。
#
# 結果、A 再生中のこの窓では: `status` の `audio` は B のフォーマット (または
# B が asr/channels 未取得なら値自体が消える) を返し、一方 `currentsong`/
# `playlistinfo` の `Format` タグは uri 不一致 (ストアは既に B の uri) のため
# A の Format が消える — 「A を再生中」と報告しつつ A の音声フォーマットだけ
# 先に失われる内部矛盾が生じる。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが (Explore サブエージェントへの調査委任を経て) 新規発見した項目。
#
# 既存 BACKLOG 項目 (mpdseekplayerrace, blocked) との違い: あちらは
# `_pending_tl_track`/`_current_tl_track` のどちらが「意図した曲」かをMPD層から
# 同期的に見分ける必要があり、mopidy core に公開APIが無くスコープ外だった。
# 本件は「曲(uri)ごとに別々の値を覚える」だけで解決でき、mopidy core 側の
# 昇格タイミングを一切問わずに済むため、mopidy_mpd 側だけで修正可能。
#
# 対策: 単一値の `_audio_format`/`_audio_format_uri` を、uri をキーとした
# 辞書キャッシュへ置き換える。`set_audio_format(value, uri=...)` は該当 uri
# のエントリだけを更新し、他の uri (現在曲Aなど) の値は上書きされない。
# `status` の `audio` フィールドも (`_status_bitrate` と同じ流儀で)
# `futures["playback.current_tl_track"]` から現在曲の uri を取り、その uri の
# 値だけを返すよう変更する (無条件の「直近の1件」ではなく「現在曲の値」に統一)。
# 無制限に増え続けないよう最大件数を設け、古い順に破棄する。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_audio_format_cache"
if MARKER_T in t:
    print("translator.py already patched (audio format cache), skip")
else:
    OLD_T = (
        "_audio_format = None\n"
        "_audio_format_uri = None\n"
        "\n"
        "\n"
        "def set_audio_format(value, uri=None):\n"
        "    global _audio_format, _audio_format_uri\n"
        "    _audio_format = value\n"
        "    _audio_format_uri = uri\n"
        "\n"
        "\n"
        "def get_audio_format():\n"
        "    return _audio_format\n"
        "\n"
        "\n"
        "def get_song_audio_format(uri):\n"
        "    # 曲メタデータの Format タグ用。直近に解決した曲(uri)と一致する時だけ返す。\n"
        "    if uri and _audio_format and uri == _audio_format_uri:\n"
        "        return _audio_format\n"
        "    return None\n"
    )
    assert t.count(OLD_T) == 1, f"OLD_T count={t.count(OLD_T)}"
    NEW_T = (
        "# 曲(uri)ごとに別エントリを持つキャッシュ。gapless先読みで次曲の値が\n"
        "# 書き込まれても、まだ再生中の現在曲のエントリは上書きされない。\n"
        "# 無制限に増え続けないよう古い順(挿入順)に破棄する。\n"
        "_audio_format_cache = {}\n"
        "_AUDIO_FORMAT_CACHE_MAX = 8\n"
        "\n"
        "\n"
        "def set_audio_format(value, uri=None):\n"
        "    if not uri:\n"
        "        return\n"
        "    _audio_format_cache[uri] = value\n"
        "    while len(_audio_format_cache) > _AUDIO_FORMAT_CACHE_MAX:\n"
        "        _audio_format_cache.pop(next(iter(_audio_format_cache)))\n"
        "\n"
        "\n"
        "def get_song_audio_format(uri):\n"
        "    # status の audio フィールド/曲メタデータの Format タグ共用。\n"
        "    # 指定した曲(uri)が解決済みならその値(不明なら None)、未解決なら None。\n"
        "    if not uri:\n"
        "        return None\n"
        "    return _audio_format_cache.get(uri)\n"
    )
    t = t.replace(OLD_T, NEW_T, 1)
    open(tp, "w").write(t)
    print("patched translator.py: audio format ストアを曲(uri)ごとのキャッシュへ変更 (gapless先読みでの現在曲の値の上書きを防止)")

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER_S = "_status_audio(futures):\n    current_tl_track"
if MARKER_S in s:
    print("status.py already patched (audio field uses current track), skip")
else:
    OLD_S = (
        "def _status_audio(futures):\n"
        "    return translator.get_audio_format()\n"
    )
    assert s.count(OLD_S) == 1, f"OLD_S count={s.count(OLD_S)}"
    NEW_S = (
        "def _status_audio(futures):\n"
        "    current_tl_track = futures[\"playback.current_tl_track\"].get()\n"
        "    if current_tl_track is None:\n"
        "        return None\n"
        "    return translator.get_song_audio_format(current_tl_track.track.uri)\n"
    )
    s = s.replace(OLD_S, NEW_S, 1)
    open(sp, "w").write(s)
    print("patched status.py: audio フィールドを「直近に解決した曲」ではなく現在曲(uri一致)の値に統一 (gapless先読み中の次曲値混入を修正)")
