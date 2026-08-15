# googlevideo は range 指定の無いリクエストを絞る (2026-08-16 実測: 素の GET は 12 KiB/s、
# range を付けると 13 MiB/s)。GStreamer の souphttpsrc は最初のリクエストに Range ヘッダを
# 付けないので、再生ボタンを押してから音が出るまで約 17 秒かかっていた。また
# verify_track_url の HEAD は googlevideo が気まぐれに 403 を返すため、再生できる曲を
# unplayable として捨てていた。
#   - URL に `&range=0-<size-1>` を付けて丸ごと要求する。ヘッダではなく URL 側にするのは、
#     souphttpsrc がシーク時に自分で足す Range ヘッダと衝突させないため (この形なら
#     シークは 206 + 正しい Content-Range で通ることを実測済み)。
#   - verify を再生と同じ形 (Range 付き GET) にする。
#   - on_source_setup() で yt-dlp が使ったのと同じ User-Agent 等を souphttpsrc に載せる。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "on_source_setup" not in s:
    # 1) 解決した URL に range パラメータを付ける (ライブは除く)
    url_anchor = '''        if url is None:
            logger.error("YTMusic yt-dlp: no url for %s", bId)
            return None
'''
    url_new = '''        if url is None:
            logger.error("YTMusic yt-dlp: no url for %s", bId)
            return None
        if not (info.get("is_live") or info.get("live_status") == "is_live"):
            _size = info.get("filesize") or info.get("filesize_approx")
            if _size and "&range=" not in url:
                url = url + "&range=0-%d" % (int(_size) - 1)
'''
    assert s.count(url_anchor) == 1, f"url anchor count={s.count(url_anchor)}"
    s = s.replace(url_anchor, url_new, 1)

    # 2) yt-dlp が使うヘッダ (User-Agent 等) を控えておく
    hdr_anchor = "        self._ytlive_url = url\n"
    hdr_new = (
        "        self._ytdlp_http_headers = dict(info.get(\"http_headers\") or {})\n"
        "        self._ytlive_url = url\n"
    )
    assert s.count(hdr_anchor) == 1, f"headers anchor count={s.count(hdr_anchor)}"
    s = s.replace(hdr_anchor, hdr_new, 1)

    # 3) verify を再生と同じ形のリクエストにする (HEAD は誤検知で曲を捨てる)
    head_anchor = "                verify = requests.head(url, timeout=5, allow_redirects=True)\n"
    head_new = (
        "                _vh = dict(info.get(\"http_headers\") or {})\n"
        "                _vh[\"Range\"] = \"bytes=0-0\"\n"
        "                verify = requests.get(\n"
        "                    url, timeout=5, allow_redirects=True, headers=_vh, stream=True\n"
        "                )\n"
        "                verify.close()\n"
    )
    assert s.count(head_anchor) == 1, f"head anchor count={s.count(head_anchor)}"
    s = s.replace(head_anchor, head_new, 1)

    # 4) change_track() は mopidy 本体の実装をコピーした古いもので、本体側が後から足した
    #    set_source_setup_callback() の呼び出しが無い。これが無いと on_source_setup が
    #    一度も呼ばれないので、set_uri の直前に足す。
    ct_anchor = '''        if not uri:
            return False
        self.audio.set_uri(
'''
    ct_new = '''        if not uri:
            return False
        self.audio.set_source_setup_callback(self.on_source_setup).get()
        self.audio.set_uri(
'''
    assert s.count(ct_anchor) == 1, f"change_track anchor count={s.count(ct_anchor)}"
    s = s.replace(ct_anchor, ct_new, 1)

    # 5) souphttpsrc に yt-dlp と同じヘッダを載せる (Range は URL 側で指定済みなので載せない。
    #    載せるとシーク時に souphttpsrc が足す Range と二重になり再生が止まる)
    s = s.rstrip("\n") + '''

    def on_source_setup(self, source):
        headers = dict(getattr(self, "_ytdlp_http_headers", None) or {})
        ua = headers.pop("User-Agent", None) or headers.pop("user-agent", None)
        headers.pop("Range", None)
        try:
            if ua:
                source.set_property("user-agent", ua)
        except Exception:
            logger.debug("YTMusic: failed to set user-agent on source", exc_info=True)
        if not headers:
            return
        try:
            from gi.repository import Gst

            st = Gst.Structure.new_empty("extra-headers")
            for k, v in headers.items():
                st.set_value(k, str(v))
            source.set_property("extra-headers", st)
        except Exception:
            logger.debug("YTMusic: failed to set extra-headers on source", exc_info=True)
'''
    open(p, "w").write(s)
    print("patched playback.py: URL に range を付け、verify を GET 化、ヘッダを source に設定")
else:
    print("on_source_setup already present, skip")
