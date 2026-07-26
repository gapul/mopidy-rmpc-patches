# backend.py の parse_auto_playlists() ("Auto Playlists" ホーム相当、既定で
# auto_playlist_refresh=60分ごとに自動更新される、ytmusic:home とは別の旧来機構) が
# セクション/アイテムを1件も個別ガードせず処理しており、以下の実データで再現しうる
# 不具合により「1件でも構造が想定外だと Auto Playlists フォルダ全体が丸ごと更新に
# 失敗し古いキャッシュのまま固まる」実害がある。
#
# (1) `stitle = nav(car, CAROUSEL_TITLE + ["text"]).strip()` はタイトル欠落カルーセルで
#     nav() が KeyError を送出 (optional指定なし)。この例外は呼び出し元
#     `_get_auto_playlists()` の1個のtry/exceptでしか捕まらないため、以後に続く
#     全セクションの処理も道連れで中断し、self.library.ytbrowse は一切更新されない。
# (2) `ititle = nav(item, ["musicTwoRowItemRenderer"] + TITLE_TEXT).strip()` も同様に
#     タイトル欠落アイテムで KeyError、やはり全体を中断させる。
# (3) MUSIC_PAGE_TYPE_ALBUM 分岐の `ctype` は nav(..., True) で None を許容している
#     にもかかわらず、直後で `ititle + " (" + ctype + ")"` と無条件に文字列結合しており、
#     サブタイトルの1行目 (Album/Single 等の種別ラベル) を持たないアルバムで
#     `TypeError: can only concatenate str (not "NoneType") to str` を送出し、これも
#     全体を中断させる。
# (4) playlist 分岐の `for st in item[...]["subtitle"]["runs"]: ititle += st["text"]` は
#     "runs" 欠落や、テキストを持たない run (アイコン等) で KeyError を送出する。
#
# 対策: セクション単位・アイテム単位でそれぞれ try/except を追加し、1件の不具合が
# 他のセクション/アイテムを道連れにしないようにする (home-patch.py の isinstance ガード、
# ytparsegaps-patch.py の per-item フォールバックと同じ「1件落ちても全体は継続する」流儀)。
# あわせて ctype の None フォールバックも修正する。
p = "mopidy_ytmusic/backend.py"
s = open(p).read()

MARKER = "parse_auto_playlists: skipping malformed section"
if MARKER in s:
    print("backend.py already patched (ytautoplaylistfix), skip")
else:
    OLD = '''def parse_auto_playlists(res):
    browse = []
    for sect in res:
        car = []
        if "musicImmersiveCarouselShelfRenderer" in sect:
            car = nav(sect, ["musicImmersiveCarouselShelfRenderer"])
        elif "musicCarouselShelfRenderer" in sect:
            car = nav(sect, ["musicCarouselShelfRenderer"])
        else:
            continue
        stitle = nav(car, CAROUSEL_TITLE + ["text"]).strip()
        browse.append(
            {
                "name": stitle,
                "uri": "ytmusic:auto:"
                + hashlib.md5(stitle.encode("utf-8")).hexdigest(),
                "items": [],
            }
        )
        for item in nav(car, ["contents"]):
            brId = nav(
                item,
                ["musicTwoRowItemRenderer"] + TITLE + NAVIGATION_BROWSE_ID,
                True,
            )
            if brId is None or brId == "VLLM":
                continue
            pagetype = nav(
                item,
                [
                    "musicTwoRowItemRenderer",
                    "navigationEndpoint",
                    "browseEndpoint",
                    "browseEndpointContextSupportedConfigs",
                    "browseEndpointContextMusicConfig",
                    "pageType",
                ],
                True,
            )
            ititle = nav(item, ["musicTwoRowItemRenderer"] + TITLE_TEXT).strip()
            if pagetype == "MUSIC_PAGE_TYPE_PLAYLIST":
                if "subtitle" in item["musicTwoRowItemRenderer"]:
                    ititle += " ("
                    for st in item["musicTwoRowItemRenderer"]["subtitle"][
                        "runs"
                    ]:
                        ititle += st["text"]
                    ititle += ")"
                browse[-1]["items"].append(
                    {
                        "type": "playlist",
                        "uri": f"ytmusic:playlist:{brId}",
                        "name": ititle,
                    }
                )
            elif pagetype == "MUSIC_PAGE_TYPE_ARTIST":
                browse[-1]["items"].append(
                    {
                        "type": "artist",
                        "uri": f"ytmusic:artist:{brId}",
                        "name": ititle + " (Artist)",
                    }
                )
            elif pagetype == "MUSIC_PAGE_TYPE_ALBUM":
                artist = nav(
                    item,
                    ["musicTwoRowItemRenderer", "subtitle", "runs", -1, "text"],
                    True,
                )
                ctype = nav(
                    item,
                    ["musicTwoRowItemRenderer", "subtitle", "runs", 0, "text"],
                    True,
                )
                if artist is not None:
                    browse[-1]["items"].append(
                        {
                            "type": "album",
                            "uri": f"ytmusic:album:{brId}",
                            "name": artist
                            + " - "
                            + ititle
                            + " ("
                            + ctype
                            + ")",
                        }
                    )
                else:
                    browse[-1]["items"].append(
                        {
                            "type": "album",
                            "uri": f"ytmusic:album:{brId}",
                            "name": ititle + " (" + ctype + ")",
                        }
                    )
    return browse
'''
    assert s.count(OLD) == 1, f"parse_auto_playlists anchor count={s.count(OLD)}"

    NEW = '''def parse_auto_playlists(res):
    browse = []
    for sect in res:
        try:
            car = []
            if "musicImmersiveCarouselShelfRenderer" in sect:
                car = nav(sect, ["musicImmersiveCarouselShelfRenderer"])
            elif "musicCarouselShelfRenderer" in sect:
                car = nav(sect, ["musicCarouselShelfRenderer"])
            else:
                continue
            stitle = nav(car, CAROUSEL_TITLE + ["text"], True)
            if stitle is None:
                continue
            stitle = stitle.strip()
            browse.append(
                {
                    "name": stitle,
                    "uri": "ytmusic:auto:"
                    + hashlib.md5(stitle.encode("utf-8")).hexdigest(),
                    "items": [],
                }
            )
            for item in nav(car, ["contents"]):
                try:
                    brId = nav(
                        item,
                        ["musicTwoRowItemRenderer"] + TITLE + NAVIGATION_BROWSE_ID,
                        True,
                    )
                    if brId is None or brId == "VLLM":
                        continue
                    pagetype = nav(
                        item,
                        [
                            "musicTwoRowItemRenderer",
                            "navigationEndpoint",
                            "browseEndpoint",
                            "browseEndpointContextSupportedConfigs",
                            "browseEndpointContextMusicConfig",
                            "pageType",
                        ],
                        True,
                    )
                    ititle = nav(
                        item, ["musicTwoRowItemRenderer"] + TITLE_TEXT, True
                    )
                    if ititle is None:
                        continue
                    ititle = ititle.strip()
                    if pagetype == "MUSIC_PAGE_TYPE_PLAYLIST":
                        if "subtitle" in item["musicTwoRowItemRenderer"]:
                            ititle += " ("
                            for st in item["musicTwoRowItemRenderer"][
                                "subtitle"
                            ].get("runs", []):
                                ititle += st.get("text", "")
                            ititle += ")"
                        browse[-1]["items"].append(
                            {
                                "type": "playlist",
                                "uri": f"ytmusic:playlist:{brId}",
                                "name": ititle,
                            }
                        )
                    elif pagetype == "MUSIC_PAGE_TYPE_ARTIST":
                        browse[-1]["items"].append(
                            {
                                "type": "artist",
                                "uri": f"ytmusic:artist:{brId}",
                                "name": ititle + " (Artist)",
                            }
                        )
                    elif pagetype == "MUSIC_PAGE_TYPE_ALBUM":
                        artist = nav(
                            item,
                            [
                                "musicTwoRowItemRenderer",
                                "subtitle",
                                "runs",
                                -1,
                                "text",
                            ],
                            True,
                        )
                        ctype = (
                            nav(
                                item,
                                [
                                    "musicTwoRowItemRenderer",
                                    "subtitle",
                                    "runs",
                                    0,
                                    "text",
                                ],
                                True,
                            )
                            or ""
                        )
                        if artist is not None:
                            browse[-1]["items"].append(
                                {
                                    "type": "album",
                                    "uri": f"ytmusic:album:{brId}",
                                    "name": artist
                                    + " - "
                                    + ititle
                                    + " ("
                                    + ctype
                                    + ")",
                                }
                            )
                        else:
                            browse[-1]["items"].append(
                                {
                                    "type": "album",
                                    "uri": f"ytmusic:album:{brId}",
                                    "name": ititle + " (" + ctype + ")",
                                }
                            )
                except Exception:
                    logger.debug(
                        "YTMusic parse_auto_playlists: skipping malformed item",
                        exc_info=True,
                    )
                    continue
        except Exception:
            logger.debug(
                "YTMusic parse_auto_playlists: skipping malformed section",
                exc_info=True,
            )
            continue
    return browse
'''
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched backend.py: parse_auto_playlists() のセクション/アイテム単位の "
        "例外ガードを追加(タイトル欠落・runs欠落によるKeyErrorが全体を巻き込んで "
        "中断するのを防止)、MUSIC_PAGE_TYPE_ALBUM分岐のctype=None文字列結合TypeErrorを修正"
    )
