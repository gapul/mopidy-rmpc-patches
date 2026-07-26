# mopidy_ytmusic.playback.py の update_cipher() が唯一 try/except による保護を持たず、
# バックグラウンドの youtube_player_refresh タイマースレッドを永久停止させうる不具合を
# 発見。TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが mopidy_ytmusic の
# コード品質を再調査 (ytscrobble-patch.py 等これまでの一連の発見的パッチと同じ流儀) して
# 発見した項目。
#
# backend.py の on_start() は RepeatingTimer(self._refresh_youtube_player, ...) という
# 素の threading.Thread サブクラスを起動する (デフォルト15分間隔、youtube_player_refresh
# config)。RepeatingTimer.run() (repeating_timer.py) は self._method() の呼び出しを
# 一切 try/except で保護していない。_refresh_youtube_player() 自身も無保護のまま
# self._get_youtube_player() (music.youtube.com への1回目のHTTP GET、こちらは
# try/except Exception: logger.exception(...) で保護済み) の戻り値URLが変化していれば
# self.playback.update_cipher(playerurl=url) を呼ぶ。update_cipher() はこのURLへの
# 2回目のHTTP GET (requests.get("https://music.youtube.com" + playerurl)) を
# 無保護で行っており、同ファイル内の唯一の非対称点になっている
# (_get_youtube_player()/_get_auto_playlists()/scrobble_track() は全て保護済み)。
# タイムアウト/DNS失敗/接続断/5xx等でこのGETが例外を投げると、例外は
# update_cipher() → _refresh_youtube_player() → RepeatingTimer.run() と無捕捉のまま
# 伝播し、run() 自体が例外で終了してスレッドがその場で死ぬ。RepeatingTimer.cancel()を
# 呼ぶ主体もいないため self._youtube_player_refresh_timer は backend 側からは
# 生きているつもりのまま参照が残り続け、以後 signatureTimestamp/Youtube_Player_URL は
# 二度と更新されない (自己復旧なし、mopidy.log への一度きりのTracebackのみで通知も無い)。
# 長時間稼働するmacmini常駐サーバでは15分間隔のうち一度でもネットワーク瞬断が起きれば
# 十分再現し、以後 scrobble_track() が送る signatureTimestamp が陳腐化したまま
# 静かに劣化し続ける実害がある。
#
# 対策: 同ファイル内の他の外部API呼び出しと同じ流儀で HTTP GET 以降を
# try/except Exception で包み、失敗時は logger.exception でログするだけに留めて
# スレッドを止めない。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = 'logger.exception("YTMusic failed to update signatureTimestamp.")'
if MARKER in s:
    print("playback.py already patched (update_cipher), skip")
else:
    OLD = '''    def update_cipher(self, playerurl):
        self.Youtube_Player_URL = playerurl
        response = requests.get("https://music.youtube.com" + playerurl)
        m = re.search(r"signatureTimestamp[:=](\\d+)", response.text)
        if m:
            self.signatureTimestamp = m.group(1)
            self.PyTubeCipher = None  # patched: pytube disabled
            logger.debug(
                "YTMusic updated signatureTimestamp to %s",
                self.signatureTimestamp,
            )
        else:
            logger.error("YTMusic unable to extract signatureTimestamp.")
            return None
'''
    NEW = '''    def update_cipher(self, playerurl):
        self.Youtube_Player_URL = playerurl
        try:
            response = requests.get("https://music.youtube.com" + playerurl)
            m = re.search(r"signatureTimestamp[:=](\\d+)", response.text)
        except Exception:
            logger.exception("YTMusic failed to update signatureTimestamp.")
            return None
        if m:
            self.signatureTimestamp = m.group(1)
            self.PyTubeCipher = None  # patched: pytube disabled
            logger.debug(
                "YTMusic updated signatureTimestamp to %s",
                self.signatureTimestamp,
            )
        else:
            logger.error("YTMusic unable to extract signatureTimestamp.")
            return None
'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of update_cipher anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: update_cipher() を try/except で保護し、"
        "signatureTimestamp取得用HTTP GET失敗による youtube_player_refresh "
        "RepeatingTimerスレッドの永久停止を防止"
    )
