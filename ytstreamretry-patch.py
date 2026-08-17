# googlevideo は解決したばかりの URL でも散発的に 403 を返す (同じ曲で数十秒のうちに
# 200 と 403 が入れ替わるのを実測)。今の _get_track() は
#   - キャッシュに当たったときは検証せずそのまま返す
#   - 検証に落ちたら None を返して諦める
# ので、死んだ URL を掴むと再生できないまま終わっていた。
#   1. キャッシュに当たった URL も 1 バイトだけ取って生きているか確かめる (数十ミリ秒)
#   2. 駄目ならキャッシュを捨てて、解決からもう一度やり直す
# にして、たまに再生できない状態をなくす。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "_get_track_once" not in s:
    def_anchor = "    def _get_track(self, bId):\n"
    assert s.count(def_anchor) == 1, f"def anchor count={s.count(def_anchor)}"
    s = s.replace(def_anchor, "    def _get_track_once(self, bId, force=False):\n", 1)

    hit_anchor = '''        _hit = _cache.get(bId)
        if _hit and _hit["exp"] > time.time():
'''
    hit_new = '''        _hit = None if force else _cache.get(bId)
        if _hit and _hit["exp"] > time.time() and not self._stream_url_alive(_hit["url"], _hit["headers"]):
            _cache.pop(bId, None)
            _hit = None
        if _hit and _hit["exp"] > time.time():
'''
    assert s.count(hit_anchor) == 1, f"hit anchor count={s.count(hit_anchor)}"
    s = s.replace(hit_anchor, hit_new, 1)

    # googlevideo が返す URL の 2/3 ほどは「Range ヘッダ無しの GET」を 403 で弾く
    # (Range 付きなら同じ URL で 206。2026-08-16 に6回中4回で再現)。souphttpsrc は
    # 最初のリクエストに Range を付けないので、これが「たまに再生できない」の正体。
    # Range をヘッダで付けると souphttpsrc がシーク時に足す Range と二重になって
    # 再生が止まるため、併せて should_download を有効にする。こうすると mopidy が
    # downloadbuffer を挟んで曲を丸ごと取り、シークはローカルのバッファで処理されるので
    # HTTP リクエストは最初の1回だけになり、二重にならない。
    src_anchor = '''        headers = dict(getattr(self, "_ytdlp_http_headers", None) or {})
        ua = headers.pop("User-Agent", None) or headers.pop("user-agent", None)
        headers.pop("Range", None)
'''
    src_new = '''        headers = dict(getattr(self, "_ytdlp_http_headers", None) or {})
        ua = headers.pop("User-Agent", None) or headers.pop("user-agent", None)
        headers["Range"] = "bytes=0-"
'''
    assert s.count(src_anchor) == 1, f"source anchor count={s.count(src_anchor)}"
    s = s.replace(src_anchor, src_new, 1)

    dl_anchor = "    def is_live(self, uri):\n"
    dl_new = '''    def should_download(self, uri):
        # 曲を丸ごとバッファさせる。シークが新しい HTTP リクエストを発生させなくなるので、
        # on_source_setup で付けた Range と衝突しない (ライブは対象外)。
        return bool(uri) and not self.is_live(uri)

    def is_live(self, uri):
'''
    assert s.count(dl_anchor) == 1, f"is_live anchor count={s.count(dl_anchor)}"
    s = s.replace(dl_anchor, dl_new, 1)

    # 検証は「GStreamer と同じか、それより厳しい形」でないと意味がない。Range 付きなら
    # 通るのに Range 無しだと 403 になる URL が実在し (6回中4回)、Range 付きで検証すると
    # 「検証は通るのに再生できない」になる。Range 無しで確かめる。
    vh_anchor = '''                _vh["Range"] = "bytes=0-0"
'''
    vh_new = '''                _vh.pop("Range", None)
'''
    assert s.count(vh_anchor) == 1, f"verify anchor count={s.count(vh_anchor)}"
    s = s.replace(vh_anchor, vh_new, 1)

    s = s.rstrip("\n") + '''

    def _stream_url_alive(self, url, headers):
        # 再生と同じ形 (Range 付き GET) で 1 バイトだけ取って確かめる。
        # ネットワーク側で失敗したときは判断できないので生きている扱いにする
        # (ここで捨てると回線が不安定なだけで毎回解決し直しになる)。
        if not self.backend.verify_track_url:
            return True
        try:
            _h = dict(headers or {})
            _h.pop("Range", None)
            r = requests.get(url, timeout=5, allow_redirects=True, headers=_h, stream=True)
            r.close()
        except Exception:
            return True
        return r.status_code < 400

    def _get_track(self, bId):
        url = self._get_track_once(bId)
        if url:
            return url
        # 解決したばかりの URL が 403 になることがあるので、キャッシュを使わずもう一度だけ。
        logger.info("YTMusic: retrying stream resolution for %s", bId)
        return self._get_track_once(bId, force=True)
'''
    open(p, "w").write(s)
    print("patched playback.py: キャッシュ URL の生存確認と解決のリトライ")
else:
    print("_get_track_once already present, skip")
