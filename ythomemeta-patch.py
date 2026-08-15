# home-patch.py の browse (ytmusic:home:<n>) は Ref を返すだけで TRACKS を温めないため、
# 続く lookup() が getTrack() -> get_song() の videoDetails に落ちていた。videoDetails は
# YouTube 動画側のメタデータなので、YTM が持つ曲名ではなく動画タイトル (「今日の日は
# さようなら - Kyo no Hi wa Sayonara」が「Kyo no Hi wa Sayonara」になる等) とチャンネル名に
# なり、アルバムも失われる。rmpc の Home 配下だけ曲名がローマ字表記になるのはこれが原因。
# get_home() の持つ YTM 側メタデータを先にキャッシュへ入れて解決する。
# ただし get_home() には曲の長さが無いので、length=None を目印にして getTrack() 側で
# videoDetails から長さだけ1度補完する (Time/duration が 0 に退化しないように)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

if "YTMusic home: failed to cache track metadata" not in s:
    # 1) home セクションの中身を playlistToTracks() でキャッシュに載せる
    br_anchor = '''                if 0 <= _idx < len(_home):
                    for _it in (_home[_idx].get("contents") or []):
'''
    br_new = '''                if 0 <= _idx < len(_home):
                    _songs = [
                        _it
                        for _it in (_home[_idx].get("contents") or [])
                        if isinstance(_it, dict) and _it.get("videoId") and _it.get("title")
                    ]
                    if _songs:
                        try:
                            for _t in self.playlistToTracks({"tracks": _songs}):
                                if not _t.length:
                                    self.TRACKS[_t.uri.rsplit(":", 1)[-1]] = _t.replace(
                                        length=None
                                    )
                        except Exception:
                            logger.debug(
                                "YTMusic home: failed to cache track metadata",
                                exc_info=True,
                            )
                    for _it in (_home[_idx].get("contents") or []):
'''
    assert s.count(br_anchor) == 1, f"home anchor count={s.count(br_anchor)}"
    s = s.replace(br_anchor, br_new, 1)

    # 2) getTrack(): browse 由来キャッシュ (length is None) は長さだけ補完して温存する
    gt_anchor = '''    def getTrack(self, bId):
        if bId not in self.TRACKS:
            track = self.backend.api.get_song(bId)
            tv = track["videoDetails"]
            self.TRACKS[bId] = Track(
'''
    gt_new = '''    def getTrack(self, bId):
        _cached = self.TRACKS.get(bId)
        if _cached is None or _cached.length is None:
            track = self.backend.api.get_song(bId)
            tv = track["videoDetails"]
            _fresh = Track(
'''
    assert s.count(gt_anchor) == 1, f"getTrack anchor count={s.count(gt_anchor)}"
    s = s.replace(gt_anchor, gt_new, 1)

    tail_anchor = '''                last_modified=None,
            )
            try:
                self.addThumbnails(bId, tv["thumbnail"])
'''
    tail_new = '''                last_modified=None,
            )
            # get_home() 由来のメタデータの方が YTM の表記として正しいので温存し、
            # videoDetails にしか無い長さだけを入れる。
            self.TRACKS[bId] = (
                _fresh if _cached is None else _cached.replace(length=_fresh.length)
            )
            try:
                self.addThumbnails(bId, tv["thumbnail"])
'''
    assert s.count(tail_anchor) == 1, f"getTrack tail anchor count={s.count(tail_anchor)}"
    s = s.replace(tail_anchor, tail_new, 1)

    # 3) lookup() は TRACKS を直接見て getTrack() を飛ばしていたため、上の長さ補完が
    #    素通しされていた。キャッシュの判断は getTrack() の1か所に任せる。
    lu_anchor = '''        if (bId) in self.TRACKS:
            return [self.TRACKS[bId]]
        else:
            try:
                return [self.getTrack(bId)]
            except Exception:
                logger.exception('YTMusic failed to get track "%s"', bId)
        return []
'''
    lu_new = '''        try:
            return [self.getTrack(bId)]
        except Exception:
            logger.exception('YTMusic failed to get track "%s"', bId)
        return []
'''
    assert s.count(lu_anchor) == 1, f"lookup anchor count={s.count(lu_anchor)}"
    s = s.replace(lu_anchor, lu_new, 1)

    open(p, "w").write(s)
    print("patched library.py: home の曲メタデータを YTM 側の値でキャッシュ")
else:
    print("home track metadata cache already present, skip")
