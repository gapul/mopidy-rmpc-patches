# mopidy_ytmusic.playback.YTMusicPlaybackProvider が mopidy.backend.PlaybackProvider の
# is_live()/should_download() を一切オーバーライドしておらず、基底クラスの既定実装
# (mopidy/backend.py: 常に False を返す、"MAY be reimplemented by subclass" と明記) の
# ままになっている不具合。change_track() (playback.py) は
#     self.audio.set_uri(uri, live_stream=self.is_live(uri), download=self.should_download(uri))
# と実際にこの2メソッドの戻り値を GStreamer 側へ渡しているため、is_live() が常に False だと
# 現在配信中のライブ動画(YouTube Music の検索/browse結果に混ざりうるライブコンサート・
# 常時配信ラジオ的トラック)も「有限長ファイル」としてバッファリングされてしまう
# (live_stream=True は GStreamer 側のバッファリング無効化・一時停止時のデータ破棄という
# 実際の再生系への差分を持つ、mopidy/backend.py の is_live() docstring 参照)。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが(サブエージェントに調査を
# 委任した上で)再調査して新規発見した項目。
#
# 実データ確認: このリポジトリの env に同梱の yt-dlp (yt_dlp/extractor/youtube/_video.py)
# を実際に読み、公開動画抽出コードが info dict に `live_status`
# ("is_live"/"was_live"/"post_live"/"is_upcoming"/"not_live") と `is_live` (bool) を
# 実際にセットすることを確認済み (grep -n "'live_status':" 4178行目、
# YoutubeDL.py 2794-2798行目が live_status 欠落時に is_live/was_live から補完する処理も
# 確認)。ytdlp-patch.py が全面書き換えした _get_track() は既にこの info dict を
# 保持しているにも関わらず url/asr/audio_channels しか読んでおらず、live_status/is_live を
# 完全に無視していた。
#
# 既存パッチ未カバーの根拠: playback.py に触れる既存パッチ (ytdlp/ytcipherfail/
# ytaudioformat/ytsongformat/ytverifytrackurl) を grep -n "is_live\|should_download\|
# live_status" した結果 0件、いずれも cipher失敗・yt-dlp移行・audio format記録・
# 403検証のみで live/is_live 系には一切触れていない。
#
# 対策: change_track() が is_live(uri) を呼ぶ際の uri は self.translate_uri(track.uri) の
# 戻り値 (=_get_track() が返す解決済みストリームURL) そのものであり、ytaudioformat-patch.py
# の _audio_format/_audio_format_uri と同じ「直近1件のみ」の揮発性キャッシュで十分
# (change_track は translate_uri() 完了を待ってから同期的に is_live()/should_download() を
# 呼ぶため、is_live/should_downloadと同時に複数トラックの解決処理が競合することはない)。
# _get_track() の URL解決成功時に info.get("is_live")/info.get("live_status") から
# 実際のライブ判定を self._ytlive_url/self._ytlive_is_live へ記録し、is_live()は
# 引数のuriがこの直近解決結果と一致する時だけその値を返す (不一致なら安全側の False)。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = "_ytlive_is_live"
if MARKER in s:
    print("playback.py already patched (live stream), skip")
else:
    OLD_INIT = """        self.signatureTimestamp = None
        self.PyTubeCipher = None"""
    assert s.count(OLD_INIT) == 1, f"expected 1 occurrence of __init__ anchor (got {s.count(OLD_INIT)})"
    NEW_INIT = """        self.signatureTimestamp = None
        self.PyTubeCipher = None
        self._ytlive_url = None
        self._ytlive_is_live = False"""
    s = s.replace(OLD_INIT, NEW_INIT, 1)

    OLD_METHODS = """            logger.error('translate_uri error "%s"', str(e))
            return None

    def _get_track(self, bId):"""
    assert s.count(OLD_METHODS) == 1, f"expected 1 occurrence of translate_uri/_get_track anchor (got {s.count(OLD_METHODS)})"
    NEW_METHODS = '''            logger.error('translate_uri error "%s"', str(e))
            return None

    def is_live(self, uri):
        return bool(uri) and uri == self._ytlive_url and self._ytlive_is_live

    def _get_track(self, bId):'''
    s = s.replace(OLD_METHODS, NEW_METHODS, 1)

    OLD_TAIL = '''        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)
        return url'''
    assert s.count(OLD_TAIL) == 1, f"expected 1 occurrence of resolved-stream tail anchor (got {s.count(OLD_TAIL)})"
    NEW_TAIL = '''        self._ytlive_url = url
        try:
            self._ytlive_is_live = bool(info.get("is_live")) or info.get("live_status") == "is_live"
        except Exception:
            self._ytlive_is_live = False
        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)
        return url'''
    s = s.replace(OLD_TAIL, NEW_TAIL, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: is_live()が基底クラスの既定False固定のままで、配信中の"
        "ライブ動画もGStreamerに有限長ファイルとして渡ってしまう不具合を修正 "
        "(yt-dlpのinfo['is_live']/['live_status']から実際のライブ判定を記録しis_live()へ反映)"
    )
