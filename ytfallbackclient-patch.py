# googlevideo に締め出されると通常の音声フォーマット (251/140 など) の URL は全部 403 に
# なるが、TV クライアント経由で取れる format 18 (360p mp4 の中の AAC 音声) は通ることがある
# (2026-08-16 の締め出し中に実測: 251 も 140 も 403、tv_simply の 18 だけ 206)。
# 音質は落ちるし映像ぶんの帯域も無駄になるので普段は使わないが、鳴らないよりはましなので
# 2回目の解決だけこちらに逃がす。
p = "mopidy_ytmusic/playback.py"
s = open(p).read()

if "player_client" not in s:
    sig_anchor = "    def _get_track_once(self, bId, force=False):\n"
    assert s.count(sig_anchor) == 1, f"signature anchor count={s.count(sig_anchor)}"
    s = s.replace(
        sig_anchor, "    def _get_track_once(self, bId, force=False, client=None):\n", 1
    )

    opts_anchor = '''        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "noplaylist": True, "format": fmt}
'''
    opts_new = '''        if client:
            # TV クライアントは音声のみのフォーマットを出さないことがあるので 18 も許す
            fmt = fmt + "/18"
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "noplaylist": True, "format": fmt}
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
'''
    assert s.count(opts_anchor) == 1, f"opts anchor count={s.count(opts_anchor)}"
    s = s.replace(opts_anchor, opts_new, 1)

    retry_anchor = '''        logger.info("YTMusic: retrying stream resolution for %s", bId)
        url = self._get_track_once(bId, force=True)
'''
    retry_new = '''        logger.info(
            "YTMusic: retrying stream resolution for %s via the TV client", bId
        )
        url = self._get_track_once(bId, force=True, client="tv_simply")
'''
    assert s.count(retry_anchor) == 1, f"retry anchor count={s.count(retry_anchor)}"
    s = s.replace(retry_anchor, retry_new, 1)

    open(p, "w").write(s)
    print("patched playback.py: 2回目の解決を TV クライアントに逃がす")
else:
    print("player_client fallback already present, skip")
