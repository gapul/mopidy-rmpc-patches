# YouTube はストリーム解決を短時間に叩きすぎると IP ごと 403 を返すようになる
# (2026-08-16 に実際に踏んで、しばらく一切再生できなくなった)。そうなると
# コード側で何をしても直らず、時間を置くしか手が無い。
# 踏まないための歯止めを入れる:
#   1. 解決の最小間隔をあける (連打しない)
#   2. 連続で弾かれたら「締め出された」と判断し、一定時間は解決を止める
#      (ここで叩き続けると締め出しが延びるだけなので、諦めるほうが早く戻る)
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "_yt_gate" not in s:
    state = '''_YT_MIN_INTERVAL = 1.0  # 解決と解決の間に最低これだけあける (秒)
_YT_FAIL_LIMIT = 5  # 連続でこの回数弾かれたら締め出されたと判断する
_YT_COOLDOWN = 600  # 締め出されたあと解決を止めておく時間 (秒)
_yt_gate = {"last": 0.0, "fails": 0, "blocked_until": 0.0}


def _yt_gate_enter():
    """解決してよければ True。締め出し中なら False。必要なら間隔があくまで待つ。"""
    now = time.time()
    if _yt_gate["blocked_until"] > now:
        return False
    wait = _YT_MIN_INTERVAL - (now - _yt_gate["last"])
    if wait > 0:
        time.sleep(wait)
    _yt_gate["last"] = time.time()
    return True


def _yt_gate_result(ok):
    if ok:
        _yt_gate["fails"] = 0
        return
    _yt_gate["fails"] += 1
    if _yt_gate["fails"] >= _YT_FAIL_LIMIT:
        _yt_gate["blocked_until"] = time.time() + _YT_COOLDOWN
        _yt_gate["fails"] = 0
        logger.warning(
            "YTMusic: 解決に連続で失敗したため %d 秒間は YouTube への解決を止めます "
            "(叩き続けると締め出しが延びるため)",
            _YT_COOLDOWN,
        )


class YTMusicPlaybackProvider('''
    anchor = "class YTMusicPlaybackProvider("
    assert s.count(anchor) == 1, f"class anchor count={s.count(anchor)}"
    s = s.replace(anchor, state, 1)

    old = '''    def _get_track(self, bId):
        url = self._get_track_once(bId)
        if url:
            return url
        # 解決したばかりの URL が 403 になることがあるので、キャッシュを使わずもう一度だけ。
        logger.info("YTMusic: retrying stream resolution for %s", bId)
        return self._get_track_once(bId, force=True)
'''
    new = '''    def _get_track(self, bId):
        if not _yt_gate_enter():
            logger.warning(
                "YTMusic: YouTube に締め出されているため %s の解決を見送ります", bId
            )
            return None
        url = self._get_track_once(bId)
        _yt_gate_result(bool(url))
        if url:
            return url
        # 解決したばかりの URL が 403 になることがあるので、キャッシュを使わずもう一度だけ。
        if not _yt_gate_enter():
            return None
        logger.info("YTMusic: retrying stream resolution for %s", bId)
        url = self._get_track_once(bId, force=True)
        _yt_gate_result(bool(url))
        return url
'''
    assert s.count(old) == 1, f"wrapper anchor count={s.count(old)}"
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print("patched playback.py: 解決の間隔制限と締め出し時のクールダウン")
else:
    print("_yt_gate already present, skip")
