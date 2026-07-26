# mopidy_ytmusic.playback.YTMusicPlaybackProvider._get_track() (ytaudioformat-patch.py) が
# 曲のサンプルレート/チャンネル数 (status の audio フィールド用) を translator.py の
# 揮発性ストア (_audio_format/_audio_format_uri) へ記録する際、`if asr and channels:` の
# 中でしか set_audio_format() を呼ばないため、新しく解決した曲で yt-dlp の info dict に
# asr/audio_channels (と requested_formats 経由のフォールバックも) が一切含まれない場合、
# set_audio_format() が丸ごとスキップされ _audio_format/_audio_format_uri が「直前に
# 解決できた別の曲」の値のまま残ってしまう不具合。TODO/既知の残課題を全項目消化済みの
# ため自走エージェントが(サブエージェントに調査を委任した上で)再調査して新規発見した項目。
#
# mopidy_mpd/protocol/status.py の _status_audio() は translator.get_audio_format() を
# 現在再生中の曲の uri と一切突き合わせず無条件に返す設計 (mpdaudioformat-patch.py 検証時点
# では「曲切替のたびに新曲の asr/channels が必ず取得できる」前提だったため無害だった)。
# 一方 track_to_mpd_format() 経由の Format タグ (get_song_audio_format()) は uri が
# _audio_format_uri と一致する時だけ値を返す設計のため、この場合はそもそも古い曲の uri と
# 不一致になり正しく Format タグを出さない — つまり status の audio フィールドと
# currentsong/playlistinfo の Format タグが矛盾した状態のまま無期限に (次に asr/channels の
# 取得に成功する曲へ切り替わるまで) 残り続ける。
#
# 実際に asr/audio_channels が欠落しうるケース: 直前のコミット (ytlivestream-patch.py) で
# ライブ配信曲の is_live() 対応が入ったが、ライブ配信の HLS 系フォーマットは yt-dlp の
# info dict に asr/audio_channels を含まないことが多く (requested_formats 経由の
# フォールバックも同様に欠落しうる)、まさにこの取りこぼしパスを実際に踏む。ライブ配信に
# 限らず、yt-dlp がこれらのキーを提供できない任意のフォーマット解決でも同様に発生する。
#
# 既存パッチ未カバーの根拠: ytaudioformat-patch.py/mpdaudioformat-patch.py/
# mpdsongformat-patch.py/ytsongformat-patch.py はいずれも「新曲へ切り替わるたびに
# set_audio_format() が必ず呼ばれる」ことを前提にしており、`if asr and channels:` の
# 条件式そのものを grep で確認したが、この呼び出しスキップ時の「前の曲の値が残留する」
# 副作用には触れていない。
#
# 対策: ytlivestream-patch.py の self._ytlive_url/self._ytlive_is_live と同じ「新しく解決
# した曲の uri を必ず記録し、値が不明なら None にする」設計に揃える。`if asr and channels:`
# の条件分岐を外し、set_audio_format() を常に (新曲の uri を伴って) 呼び、値は
# asr/channels が両方取れた時だけ実フォーマット文字列、それ以外は None にする。
# get_audio_format() が None を返せば status.py の `if audio_format:` で audio フィールド
# 自体を出さない (既存の仕組みのまま、mpdaudioformat-patch.py 側は無変更)。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = '"%d:16:%d" % (int(asr), int(channels)) if asr and channels else None'
if MARKER in s:
    print("playback.py already patched (audio format stale-on-unknown), skip")
else:
    OLD = """        try:
            asr = info.get("asr")
            channels = info.get("audio_channels")
            if not asr or not channels:
                reqs = info.get("requested_formats") or []
                if reqs:
                    asr = asr or reqs[0].get("asr")
                    channels = channels or reqs[0].get("audio_channels")
            if asr and channels:
                from mopidy_mpd import translator as _mpd_translator
                _mpd_translator.set_audio_format(
                    "%d:16:%d" % (int(asr), int(channels)),
                    uri="ytmusic:track:%s" % bId,
                )
        except Exception:
            logger.debug(
                "YTMusic: failed to record audio format for status",
                exc_info=True,
            )"""
    assert s.count(OLD) == 1, f"expected 1 occurrence of audio-format anchor (got {s.count(OLD)})"
    NEW = """        try:
            asr = info.get("asr")
            channels = info.get("audio_channels")
            if not asr or not channels:
                reqs = info.get("requested_formats") or []
                if reqs:
                    asr = asr or reqs[0].get("asr")
                    channels = channels or reqs[0].get("audio_channels")
            from mopidy_mpd import translator as _mpd_translator
            _mpd_translator.set_audio_format(
                "%d:16:%d" % (int(asr), int(channels)) if asr and channels else None,
                uri="ytmusic:track:%s" % bId,
            )
        except Exception:
            logger.debug(
                "YTMusic: failed to record audio format for status",
                exc_info=True,
            )"""
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: 曲切替時にasr/channelsが取得できないと"
        "set_audio_format()自体がスキップされ、statusのaudioフィールドが"
        "前の曲の値のまま残留する不具合を修正 (新曲のuriを伴い常にset_audio_formatを呼び、"
        "値不明時はNoneにする)"
    )
