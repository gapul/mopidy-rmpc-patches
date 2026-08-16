# _get_track() は毎回 yt-dlp で解決し直していたので、同じ曲をもう一度選ぶだけでも
# 1〜2秒待たされていた (曲を選んでから音が出るまでの時間のほとんどはこれ)。
# googlevideo の URL は URL 自身が持つ expire まで有効なので、videoId をキーに
# キャッシュして使い回す。キャッシュに当たれば yt-dlp も verify も走らないので
# 待ち時間は GStreamer のバッファリングだけになる。
# ライブはキャッシュしない (URL が意味を持たないため)。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "_ytdlp_url_cache" not in s:
    imp_anchor = "import re\nfrom urllib.parse import parse_qs\n"
    assert s.count(imp_anchor) == 1, f"import anchor count={s.count(imp_anchor)}"
    s = s.replace(imp_anchor, "import re\nimport time\nfrom urllib.parse import parse_qs\n", 1)

    head_anchor = '''    def _get_track(self, bId):
        # patched: pytubeのcipher解読は壊れるためyt-dlpに委譲
        import yt_dlp
'''
    head_new = '''    def _get_track(self, bId):
        # patched: pytubeのcipher解読は壊れるためyt-dlpに委譲
        import yt_dlp
        _cache = getattr(self, "_ytdlp_url_cache", None)
        if _cache is None:
            _cache = self._ytdlp_url_cache = {}
        _hit = _cache.get(bId)
        if _hit and _hit["exp"] > time.time():
            self._ytdlp_http_headers = _hit["headers"]
            self._ytlive_url = _hit["url"]
            self._ytlive_is_live = _hit["live"]
            try:
                from mopidy_mpd import translator as _mpd_translator

                _mpd_translator.set_audio_format(
                    _hit["audio"], uri="ytmusic:track:%s" % bId
                )
                _mpd_translator.set_song_bitrate(
                    _hit["bitrate"], uri="ytmusic:track:%s" % bId
                )
            except Exception:
                logger.debug(
                    "YTMusic: failed to restore cached stream metadata", exc_info=True
                )
            logger.info("YTMusic (yt-dlp) reused cached stream for %s", bId)
            return _hit["url"]
'''
    assert s.count(head_anchor) == 1, f"head anchor count={s.count(head_anchor)}"
    s = s.replace(head_anchor, head_new, 1)

    tail_anchor = '''        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)
        return url
'''
    tail_new = '''        if not self._ytlive_is_live:
            try:
                _reqs = info.get("requested_formats") or []
                _first = _reqs[0] if _reqs else {}
                _asr = info.get("asr") or _first.get("asr")
                _ch = info.get("audio_channels") or _first.get("audio_channels")
                _abr = info.get("abr") or _first.get("abr")
                # URL 自身が持つ expire (unix秒) まで有効。少し手前で切って使う。
                _exp = int(
                    (parse_qs(url.split("?", 1)[-1]).get("expire") or [0])[0] or 0
                )
                if _exp <= 0:
                    _exp = int(time.time()) + 3600
                _cache[bId] = {
                    "url": url,
                    "exp": _exp - 300,
                    "headers": getattr(self, "_ytdlp_http_headers", {}),
                    "live": False,
                    "audio": "%d:16:%d" % (int(_asr), int(_ch)) if _asr and _ch else None,
                    "bitrate": round(_abr) if _abr else None,
                }
                while len(_cache) > 256:
                    _cache.pop(next(iter(_cache)))
            except Exception:
                logger.debug("YTMusic: failed to cache stream url", exc_info=True)
        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)
        return url
'''
    assert s.count(tail_anchor) == 1, f"tail anchor count={s.count(tail_anchor)}"
    s = s.replace(tail_anchor, tail_new, 1)

    open(p, "w").write(s)
    print("patched playback.py: 解決済みストリーム URL を expire までキャッシュ")
else:
    print("_ytdlp_url_cache already present, skip")
