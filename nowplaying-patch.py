# mopidy-ytmusic の setup() に NowPlayingFrontend(nowplaying_fe.py) の登録を追記する。
# nowplaying_fe.py はビルド時に mopidy_ytmusic/ へ cp 済み(mopidy-env.nix)。
p = "mopidy_ytmusic/__init__.py"
s = open(p).read()

if "NowPlayingFrontend" not in s:
    anchor = '        registry.add("frontend", YTMusicScrobbleFE)\n'
    inject = anchor + (
        "        try:\n"
        "            from .nowplaying_fe import NowPlayingFrontend\n"
        '            registry.add("frontend", NowPlayingFrontend)\n'
        "        except Exception:\n"
        "            import logging as _l\n"
        '            _l.getLogger(__name__).exception("nowplaying register failed")\n'
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    s = s.replace(anchor, inject, 1)
    open(p, "w").write(s)
    print("registered NowPlayingFrontend")
else:
    print("NowPlayingFrontend already registered, skip")
