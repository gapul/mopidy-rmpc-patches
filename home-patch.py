# mopidy-ytmusic の browse ルートには YouTube Music の「ホーム」(Listen again /
# Forgotten favorites / 各種おすすめカルーセル) が無い。get_home() を browse に繋ぎ、
# ytmusic:home でセクション一覧、ytmusic:home:<n> でそのセクションの中身を返す。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

if "ytmusic:home" not in s:
    # 1) root に "Home" を先頭追加
    root_anchor = (
        '                dirs += [\n'
        '                    Ref.directory(uri="ytmusic:artist", name="Artists"),'
    )
    root_new = (
        '                dirs += [\n'
        '                    Ref.directory(uri="ytmusic:home", name="Home"),\n'
        '                    Ref.directory(uri="ytmusic:artist", name="Artists"),'
    )
    assert s.count(root_anchor) == 1, f"root anchor count={s.count(root_anchor)}"
    s = s.replace(root_anchor, root_new, 1)

    # 2) browse に home 分岐を注入
    home_branches = r'''        if uri == "ytmusic:home":
            refs = []
            try:
                for _i, _sec in enumerate(self.backend.api.get_home(limit=100)):
                    _t = _sec.get("title") or ("Section %d" % _i)
                    refs.append(Ref.directory(uri="ytmusic:home:%d" % _i, name=_t))
            except Exception:
                logger.exception("YTMusic get_home failed")
            return refs
        if uri.startswith("ytmusic:home:"):
            refs = []
            try:
                _idx = int(uri.split(":")[2])
                _home = self.backend.api.get_home(limit=100)
                if 0 <= _idx < len(_home):
                    for _it in (_home[_idx].get("contents") or []):
                        if not isinstance(_it, dict):
                            continue
                        _n = _it.get("title") or ""
                        if _it.get("videoId"):
                            refs.append(Ref.track(uri="ytmusic:track:%s" % _it["videoId"], name=_n))
                        elif _it.get("playlistId"):
                            refs.append(Ref.playlist(uri="ytmusic:playlist:%s" % _it["playlistId"], name=_n))
                        elif _it.get("podcastId") or "channel" in _it:
                            # ポッドキャスト番組 (browseId+podcastId+channel):
                            # mopidy_ytmusic に podcast browse/lookup が無く、album 扱いにすると
                            # 開いても常に空の「アルバム」フォルダになるため、素通しせず除外する。
                            continue
                        elif _it.get("browseId"):
                            _b = str(_it["browseId"])
                            if "subscribers" in _it or _b.startswith("UC"):
                                refs.append(Ref.artist(uri="ytmusic:artist:%s" % _b, name=_n))
                            else:
                                refs.append(Ref.album(uri="ytmusic:album:%s" % _b, name=_n))
            except Exception:
                logger.exception("YTMusic get_home section failed")
            return refs
'''
    br_anchor = (
        "        logger.debug('YTMusic browsing uri \"%s\"', uri)\n"
        '        if uri == "ytmusic:root":'
    )
    br_new = (
        "        logger.debug('YTMusic browsing uri \"%s\"', uri)\n"
        + home_branches
        + '        if uri == "ytmusic:root":'
    )
    assert s.count(br_anchor) == 1, f"browse anchor count={s.count(br_anchor)}"
    s = s.replace(br_anchor, br_new, 1)

    open(p, "w").write(s)
    print("patched library.py: ytmusic:home (get_home) を browse に追加")
else:
    print("ytmusic:home already present, skip")
