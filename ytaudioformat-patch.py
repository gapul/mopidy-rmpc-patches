# mpdaudioformat-patch.py (mopidy_mpd) が追加した `status` の `audio`
# (samplerate:bits:channels) フィールドへ実データを供給する側。ytdlp-patch.py が
# 書き換えた `_get_track()` はストリームURLを解決する yt-dlp の info dict を既に
# 持っているが、そこに含まれる実際のサンプルレート/チャンネル数 (yt-dlp の `asr`/
# `audio_channels`) を一切利用していなかったため、mopidy_mpd 側に実フォーマットを
# 伝える手段が存在しなかった。
#
# 実データ確認: yt-dlp (このリポジトリの env 内) で実際に公開動画を解決したところ、
# `format=251/250/140/249/bestaudio/best` (ytdlp-patch.py と同じ prefs) で選ばれる
# 音声専用フォーマットは info dict のトップレベルに `asr`(サンプルレート,
# 例: 48000)/`audio_channels`(例: 2) を直接含むことを確認済み (映像+音声を後段で
# 結合する `requested_formats` 経由になるケースへのフォールバックも用意)。
#
# 実装: _get_track() の最後 (URL解決成功、ログ出力・return url の直前) で
# asr/audio_channels を取り出し、"{asr}:16:{channels}" (bits は yt-dlp から得られ
# ないため GStreamer の一般的な PCM デコード出力 16-bit を仮定した固定値、
# mpdaudioformat-patch.py の既知の制約欄で明記) の形式にして mopidy_mpd.translator
# の揮発性ストアへ書き込む。mopidy_mpd 拡張が無効な環境でも壊れないよう import ごと
# try/except で保護し、失敗しても再生自体には一切影響しない (ログにdebugのみ)。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = "_mpd_translator.set_audio_format"
if MARKER in s:
    print("playback.py already patched (audio format), skip")
else:
    old_tail = (
        '        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)\n'
        "        return url\n"
    )
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        "        try:\n"
        "            asr = info.get(\"asr\")\n"
        "            channels = info.get(\"audio_channels\")\n"
        "            if not asr or not channels:\n"
        "                reqs = info.get(\"requested_formats\") or []\n"
        "                if reqs:\n"
        "                    asr = asr or reqs[0].get(\"asr\")\n"
        "                    channels = channels or reqs[0].get(\"audio_channels\")\n"
        "            if asr and channels:\n"
        "                from mopidy_mpd import translator as _mpd_translator\n"
        "                _mpd_translator.set_audio_format(\n"
        "                    \"%d:16:%d\" % (int(asr), int(channels))\n"
        "                )\n"
        "        except Exception:\n"
        "            logger.debug(\n"
        "                \"YTMusic: failed to record audio format for status\",\n"
        "                exc_info=True,\n"
        "            )\n"
        + old_tail
    )
    s = s.replace(old_tail, new_tail, 1)
    open(p, "w").write(s)
    print("patched playback.py: yt-dlp解決結果からサンプルレート/チャンネル数をstatus用に記録")
