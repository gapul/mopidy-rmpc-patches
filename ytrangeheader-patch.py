# googlevideo は Range ヘッダの無い GET を弾く/絞るようになった (2026-08-16 実測: 素の GET は
# 403 か 8-30 KiB/s、`Range: bytes=0-` を付けると 5-14 MiB/s)。GStreamer の souphttpsrc は
# 最初のリクエストを素の GET で投げるため、再生ボタンを押してから音が出るまで約 17 秒かかり、
# verify_track_url の HEAD も 403 を食って再生可能な曲を unplayable として捨てていた。
# PlaybackProvider.on_source_setup() で souphttpsrc に Range と yt-dlp が使ったヘッダを載せ、
# HEAD 側も同じヘッダで投げるようにして両方を根元から直す。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "on_source_setup" not in s:
    # 1) 解決時に yt-dlp が使うヘッダ (User-Agent 等) を控えておく
    hdr_anchor = "        self._ytlive_url = url\n"
    hdr_new = (
        "        self._ytdlp_http_headers = dict(info.get(\"http_headers\") or {})\n"
        "        self._ytlive_url = url\n"
    )
    assert s.count(hdr_anchor) == 1, f"headers anchor count={s.count(hdr_anchor)}"
    s = s.replace(hdr_anchor, hdr_new, 1)

    # 2) verify を再生と同じ形のリクエストにする。HEAD は googlevideo が気まぐれに 403 を
    #    返すことがあり (同じ URL への Range 付き GET は 206)、再生できる曲を
    #    unplayable として捨ててしまう。1バイトだけの Range 付き GET に置き換える。
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

    # 3) change_track() は mopidy 本体の実装をコピーした古いもので、本体側が後から足した
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

    # 4) souphttpsrc に Range とヘッダを載せる
    s = s.rstrip("\n") + '''

    def on_source_setup(self, source):
        # 再生に使う GStreamer のソース要素 (souphttpsrc) に、yt-dlp が使ったのと同じ
        # ヘッダと Range を載せる。Range が無いと googlevideo が 403/絞りで返してくる。
        headers = dict(getattr(self, "_ytdlp_http_headers", None) or {})
        ua = headers.pop("User-Agent", None) or headers.pop("user-agent", None)
        headers["Range"] = "bytes=0-"
        try:
            if ua:
                source.set_property("user-agent", ua)
        except Exception:
            logger.debug("YTMusic: failed to set user-agent on source", exc_info=True)
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
    print("patched playback.py: souphttpsrc/HEAD に Range ヘッダを付与")
else:
    print("on_source_setup already present, skip")
