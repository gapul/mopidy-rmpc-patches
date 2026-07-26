# mopidy_ytmusic.backend.py の scrobble_track() が丸ごと try/except 無しで実装されて
# いる不具合を発見。TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが
# mopidy_ytmusic のコード品質を再調査 (ytduration-patch.py 等これまでの一連の発見的
# パッチと同じ流儀) して発見した項目。
#
# scrobble_track() は core.CoreListener の track_playback_ended (scrobble_fe.py) から
# `mopidy.listener.send(YTMusicScrobbleListener, "scrobble_track", bId=bId)` 経由で
# 曲再生完了ごとに呼ばれるが、実体は YTMusicBackend 自身 (pykka.ThreadingActor) の
# メソッドとして実行される。同ファイルの _get_youtube_player()/_get_auto_playlists()
# など他の外部API呼び出しメソッドは例外なく `try/except Exception:
# logger.exception(...)` で保護されているのに対し、scrobble_track() だけが唯一
# 無保護で `player_response["playbackTracking"]["videostatsPlaybackUrl"]["baseUrl"]`
# という多段dictアクセスを行っている。scrobbleは再生完了後に独立して発行される
# 2回目のAPI呼び出しのため、対象動画が再生後に地域制限/削除/メンバー限定化等で
# playabilityStatus が ERROR/LOGIN_REQUIRED/UNPLAYABLE になり得ることは十分現実的で、
# その場合 player_response に "playbackTracking" キーが存在せず KeyError が発生する。
# pykka の Actor.on_failure は「メッセージ処理中の未捕捉例外はアクター停止の直前に
# 呼ばれる」仕様であり (pykka/_actor.py docstring: "immediately before the thread
# exits"、tell() 経由のメッセージ処理での未捕捉例外はアクターを停止させる)、
# YTMusicBackend はライブラリ/再生/プレイリスト提供を兼ねる唯一のバックエンドアクター
# のため、これが停止すると mopidy プロセスを再起動するまで YouTube Music 機能全体が
# 完全に使用不能になる (enable_scrobbling 有効時、曲を最後まで聴くたびに起こりうる
# 実害の大きいクラッシュ)。
#
# 対策: 他の外部API呼び出しメソッドと同じ流儀で本体全体を try/except Exception で
# 包み、失敗時は logger.exception でログするだけに留めてアクターを止めない。
p = "mopidy_ytmusic/backend.py"
s = open(p).read()

MARKER = 'logger.exception("YTMusic failed to scrobble track %s", bId)'
if MARKER in s:
    print("backend.py already patched (scrobble), skip")
else:
    OLD = '''    def scrobble_track(self, bId):
        # Called through YTMusicScrobbleListener
        # Let YTMusic know we're playing this track so it will be added to our history.
        CPN_ALPHABET = (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        )
        cpn = "".join(
            (CPN_ALPHABET[random.randint(0, 256) & 63] for _ in range(0, 16))
        )
        player_response = self.api._send_request(
            "player",
            {
                "playbackContext": {
                    "contentPlaybackContext": {
                        "signatureTimestamp": self.playback.signatureTimestamp,
                    },
                },
                "videoId": bId,
                "cpn": cpn,
            },
        )
        params = {
            "cpn": cpn,
            "ver": 2,
            "c": "WEB_REMIX",
        }
        tr = requests.get(
            player_response["playbackTracking"]["videostatsPlaybackUrl"][
                "baseUrl"
            ],
            params=params,
            headers=self.api.headers,
            proxies=self.api.proxies,
        )
        logger.debug("%d code from '%s'", tr.status_code, tr.url)
'''
    NEW = '''    def scrobble_track(self, bId):
        # Called through YTMusicScrobbleListener
        # Let YTMusic know we're playing this track so it will be added to our history.
        try:
            CPN_ALPHABET = (
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            )
            cpn = "".join(
                (CPN_ALPHABET[random.randint(0, 256) & 63] for _ in range(0, 16))
            )
            player_response = self.api._send_request(
                "player",
                {
                    "playbackContext": {
                        "contentPlaybackContext": {
                            "signatureTimestamp": self.playback.signatureTimestamp,
                        },
                    },
                    "videoId": bId,
                    "cpn": cpn,
                },
            )
            params = {
                "cpn": cpn,
                "ver": 2,
                "c": "WEB_REMIX",
            }
            tr = requests.get(
                player_response["playbackTracking"]["videostatsPlaybackUrl"][
                    "baseUrl"
                ],
                params=params,
                headers=self.api.headers,
                proxies=self.api.proxies,
            )
            logger.debug("%d code from '%s'", tr.status_code, tr.url)
        except Exception:
            logger.exception("YTMusic failed to scrobble track %s", bId)
'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of scrobble_track anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched backend.py: scrobble_track() を try/except で保護し、player応答に "
        "playbackTracking が無い場合等の未捕捉例外によるバックエンドアクター停止 "
        "(YouTube Music機能全体が使用不能になる) を防止"
    )
