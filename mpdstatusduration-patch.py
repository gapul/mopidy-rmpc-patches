# `status` 応答に `duration` (MPD 0.20+、現在再生中の曲の長さ、小数秒) が一度も
# 出力されない件。mopidy-mpd 3.3.0 の status.py `status()` は state が
# playing/paused のとき `time`(非推奨レガシー)/`elapsed`/`bitrate` の3行だけを
# 追加しており、後継フィールド `duration` を一切出力しない (mpdduration-patch.py
# が既に対応済みの `track_to_mpd_format()` の曲メタデータ側 `duration` とは別物 —
# こちらは playlistinfo 等の個々の曲の duration タグ、今回のものは `status` 応答
# 自体が持つ「現在再生中の曲の長さ」フィールド)。TODO 全項目消化済みのため
# 自走エージェントが rmpc 本体 (mierak/rmpc) を実際に clone してソース確認した
# ところ、rmpc-mpd/src/commands/status.rs の `Status.duration` (status応答の
# `duration` キーをパースする専用フィールド) が実際に以下2箇所で使われている
# 実害ある新規ギャップと判明:
#   (1) rmpc/src/ui/panes/progress_bar.rs — 再生位置プログレスバーの表示比率
#       `value = elapsed / duration` の分母。`duration == Duration::ZERO` だと
#       常に `value = 0.0` に固定され、実際にどれだけ再生が進んでいても
#       プログレスバーが常に空のまま描画される。
#   (2) 同ファイルのマウスクリックによるシーク処理
#       `second_to_seek_to = duration * (クリックX位置比率)` — duration が常に
#       ZERO のため計算結果が常に0になり、プログレスバー上のどこをクリックしても
#       曲の先頭(0秒)へシークされてしまう。
# 実 MPD (MusicPlayerDaemon/MPD src/command/PlayerCommands.cxx を実際に clone して
# ソース確認) は `time`/`elapsed`/`bitrate` と同じ
# `player_status.state != PlayerState::STOP` (playing/paused) の条件下で、かつ
# 曲の長さが既知 (`total_time` が negative でない) の場合のみ
# `duration: {:1.3f}\n` を追加で出力する仕様と判明。
#
# 実装: 既存の `_status_time_total(futures)` (曲の長さをミリ秒で返す、無ければ0)
# と同じ current_tl_track.track.length を参照するが、実 MPD の「長さ不明なら
# 行自体を省略する」仕様に合わせるため、0 とは区別して None を返す専用の
# `_status_duration(futures)` を新設し、time/elapsed/bitrate と同じ if ブロック内で
# None でないときだけ結果へ追加する。

pp = "mopidy_mpd/protocol/status.py"
s = open(pp).read()

MARKER = "_status_duration"
if MARKER in s:
    print("status.py already patched, skip")
else:
    old_block = (
        "    if futures[\"playback.state\"].get() in (\n"
        "        PlaybackState.PLAYING,\n"
        "        PlaybackState.PAUSED,\n"
        "    ):\n"
        '        result.append(("time", _status_time(futures)))\n'
        '        result.append(("elapsed", _status_time_elapsed(futures)))\n'
        '        result.append(("bitrate", _status_bitrate(futures)))\n'
        "    return result\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    if futures[\"playback.state\"].get() in (\n"
        "        PlaybackState.PLAYING,\n"
        "        PlaybackState.PAUSED,\n"
        "    ):\n"
        '        result.append(("time", _status_time(futures)))\n'
        '        result.append(("elapsed", _status_time_elapsed(futures)))\n'
        '        result.append(("bitrate", _status_bitrate(futures)))\n'
        "        duration = _status_duration(futures)\n"
        "        if duration is not None:\n"
        '            result.append(("duration", duration))\n'
        "    return result\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    old_helper = (
        "def _status_time_total(futures):\n"
        "    current_tl_track = futures[\"playback.current_tl_track\"].get()\n"
        "    if current_tl_track is None:\n"
        "        return 0\n"
        "    elif current_tl_track.track.length is None:\n"
        "        return 0\n"
        "    else:\n"
        "        return current_tl_track.track.length\n"
    )
    assert s.count(old_helper) == 1, f"old_helper count={s.count(old_helper)}"

    new_helper = old_helper + (
        "\n"
        "\n"
        "def _status_duration(futures):\n"
        "    current_tl_track = futures[\"playback.current_tl_track\"].get()\n"
        "    if current_tl_track is None or current_tl_track.track.length is None:\n"
        "        return None\n"
        "    return round(current_tl_track.track.length / 1000, 3)\n"
    )
    s = s.replace(old_helper, new_helper, 1)

    open(pp, "w").write(s)
    print("patched status.py: duration (MPD0.20+, 現在曲の長さ) を追加")
