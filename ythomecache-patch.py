# ホームの一覧を開くたびに get_home(limit=100) を叩き直していた。これは継続取得を
# 伴うので実測 3.2-3.7秒かかる。しかも「Home を開く (セクション一覧)」と
# 「セクションを開く (中身)」で別々に呼ぶので、曲一覧に辿り着くまでに2回走る。
# 数分単位では中身が変わらないフィードなので、短い TTL で使い回す。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

if "_home_cached" not in s:
    method = '''    def _home_cached(self, ttl=300):
        # get_home() は継続取得を伴い数秒かかる。ホームのフィードは数分では変わらないので
        # TTL 付きで使い回す (セクション一覧 → セクションの中身、で2回呼ばれるのも1回で済む)。
        import time as _time

        now = _time.time()
        cached = getattr(self, "_home_cache", None)
        if cached is not None and cached[0] > now:
            return cached[1]
        data = self.backend.api.get_home(limit=100)
        self._home_cache = (now + ttl, data)
        return data

    def browse(self, uri):'''
    anchor = "    def browse(self, uri):"
    assert s.count(anchor) == 1, f"browse anchor count={s.count(anchor)}"
    s = s.replace(anchor, method, 1)

    a1 = "                for _i, _sec in enumerate(self.backend.api.get_home(limit=100)):"
    assert s.count(a1) == 1, f"list anchor count={s.count(a1)}"
    s = s.replace(a1, "                for _i, _sec in enumerate(self._home_cached()):", 1)

    a2 = "                _home = self.backend.api.get_home(limit=100)"
    assert s.count(a2) == 1, f"section anchor count={s.count(a2)}"
    s = s.replace(a2, "                _home = self._home_cached()", 1)

    open(p, "w").write(s)
    print("patched library.py: get_home の結果を短い TTL でキャッシュ")
else:
    print("_home_cached already present, skip")
