# status の bitrate フィールド(mpdbitrate-patch.py が mopidy_mpd 側に追加した
# uriキー付き揮発性キャッシュ、mopidy_mpd/translator.py の set_song_bitrate/
# get_song_bitrate)へ実データを供給する側。
#
# mopidy_ytmusic/library.py の Track() 生成箇所 (playlistToTracks/
# uploadArtistToTracks/uploadAlbumToTracks/albumToTracks/getTrack/parseSearch の
# 計6箇所) はいずれも `bitrate=0` を無条件でハードコードしており、mopidy core
# 標準の Track.bitrate フィールド経由では実測値を一切表現できない。
#
# 一方 `_get_track()` (ytdlp-patch.py 由来) は既に yt-dlp の解決結果 (info dict)
# から asr/audio_channels を取り出し ytaudioformat-patch.py 経由で status の
# `audio` フィールドへ供給しているが、同じ info dict に含まれる `abr` (実測
# 平均ビットレート、kbps単位) は一切参照・伝播されていなかった。
#
# 実データ確認: yt-dlp で実際に公開動画を解決したところ、選択されるフォーマット
# (format=251/250/140/249/bestaudio/best、asr/channelsと同じ優先順位) の info dict
# トップレベルに `abr` (例: 128.93) が直接含まれることを確認済み (映像+音声を
# 後段結合する requested_formats 経由になるケースへのフォールバックも
# asr/channelsと同様に用意)。
#
# 実装: _get_track() の末尾、asr/channels を記録する既存の try ブロックの直後に
# 同じ形の try ブロックを追加し、abr を "%d" % round(abr) 形式にして
# mopidy_mpd.translator の曲(uri)キー付きキャッシュへ書き込む。mopidy_mpd 拡張が
# 無効な環境でも壊れないよう import ごと try/except で保護し、失敗しても
# 再生自体には一切影響しない (ログにdebugのみ、既存のaudio format記録と対称)。
#
# 既知の制約: abr は yt-dlp が算出する「平均」ビットレートであり、実MPDが返す
# 「瞬間 (instantaneous)」ビットレートとは厳密には一致しない (audioフィールドの
# bits固定値16と同種の割り切り)。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = "set_song_bitrate"
if MARKER in s:
    print("playback.py already patched (bitrate), skip")
else:
    anchor = (
        "            from mopidy_mpd import translator as _mpd_translator\n"
        "            _mpd_translator.set_audio_format(\n"
        "                \"%d:16:%d\" % (int(asr), int(channels)) if asr and channels else None,\n"
        "                uri=\"ytmusic:track:%s\" % bId,\n"
        "            )\n"
        "        except Exception:\n"
        "            logger.debug(\n"
        "                \"YTMusic: failed to record audio format for status\",\n"
        "                exc_info=True,\n"
        "            )\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    addition = (
        anchor
        + "        try:\n"
        + "            abr = info.get(\"abr\")\n"
        + "            if not abr:\n"
        + "                reqs = info.get(\"requested_formats\") or []\n"
        + "                if reqs:\n"
        + "                    abr = reqs[0].get(\"abr\")\n"
        + "            from mopidy_mpd import translator as _mpd_translator\n"
        + "            _mpd_translator.set_song_bitrate(\n"
        + "                round(abr) if abr else None,\n"
        + "                uri=\"ytmusic:track:%s\" % bId,\n"
        + "            )\n"
        + "        except Exception:\n"
        + "            logger.debug(\n"
        + "                \"YTMusic: failed to record bitrate for status\",\n"
        + "                exc_info=True,\n"
        + "            )\n"
    )
    s = s.replace(anchor, addition, 1)
    open(p, "w").write(s)
    print("patched playback.py: yt-dlp解決結果の実測ビットレート(abr)をstatusのbitrateフィールド用に記録")
