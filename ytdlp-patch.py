import sys
p = "mopidy_ytmusic/playback.py"
s = open(p).read()
s = s.replace(
    "self.PyTubeCipher = Cipher(js=response.text)",
    "self.PyTubeCipher = None  # patched: pytube disabled",
)
marker = "    def _get_track(self, bId):"
idx = s.index(marker)
new_method = '''    def _get_track(self, bId):
        # patched: pytubeのcipher解読は壊れるためyt-dlpに委譲
        import yt_dlp
        watch_url = "https://music.youtube.com/watch?v=" + bId
        prefs = self.backend.stream_preference or [251, 250, 140, 249]
        fmt = "/".join(str(x) for x in prefs) + "/bestaudio/best"
        opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                "noplaylist": True, "format": fmt}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(watch_url, download=False)
        except Exception as e:
            logger.error("YTMusic yt-dlp failed for %s: %s", bId, str(e))
            return None
        url = info.get("url")
        if url is None:
            reqs = info.get("requested_formats") or []
            url = reqs[0].get("url") if reqs else None
        if url is None:
            fmts = info.get("formats") or []
            url = fmts[-1].get("url") if fmts else None
        if url is None:
            logger.error("YTMusic yt-dlp: no url for %s", bId)
            return None
        logger.info("YTMusic (yt-dlp) resolved stream for %s", bId)
        return url
'''
open(p, "w").write(s[:idx] + new_method)
print("patched playback.py")
