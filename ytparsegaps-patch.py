# ytartistnoexpand-patch.py の実機検証 (browseId欠落アーティストの実データブラウズ) で
# 新規発見した、parseSearch()/browse() の既存3件の不具合をまとめて修正する。
#
# (1) parseSearch() の song/album 分岐は共通して `for a in result["artists"]:` を使うが、
#     "artists" キー自体を持たない結果 (実データで再現: "indie" の any 検索で実際に
#     `KeyError: 'artists'` を送出 — dev mopidy 実機で `search any "indie"` を叩いたところ
#     album 分岐 (`if result["browseId"] not in self.ALBUMS:` の直後) で再現し、search
#     結果が丸ごと空になることを確認済み) に対し `KeyError: 'artists'` を送出する。
#     個別の try/except に守られているため search 全体は落ちないが、その1件が静かに
#     結果から消える (album 分岐は例外を握り潰した時点で当該アルバムが salbums に
#     一切追加されないため、song 分岐の結果まで含め search 全体が空応答になりうる)。
#     対策: 両分岐とも result.get("artists") or [] にフォールバックし、アーティスト情報が
#     無くてもトラック/アルバム自体は結果に含める。
#
# (2) parseSearch() の artist 分岐は、"albums"/"params" がある場合に
#     get_artist_albums() を呼ぶが、その内部で ytmusicapi/navigation.py の nav() が
#     musicCarouselShelfRenderer キー不在で KeyError を送出することがある (実データ
#     "Indie Soull" で再現)。この呼び出しはアーティスト1件分の処理全体を包む唯一の
#     try/except の中にあるため、albums取得の失敗が後続の singles/songs 処理まで
#     道連れにして中断させ、そのアーティストのアルバム・曲が丸ごと0件になる。
#     対策: get_artist_albums() の呼び出しだけを個別の try/except で囲み、失敗しても
#     albums=[] として singles/songs の処理を継続する。
#
# (3) library.py の browse() `ytmusic:artist:<id>` (非アップロード) 分岐は、
#     artistToTracks() が正真正銘0曲のアーティストで None を返すケース (実データ
#     "The Indie Hippies"/"Indie Lust") を `[Ref.track(...) for t in tracks]` で
#     未ガードのままイテレートし TypeError を送出する。外側の try/except で握り潰され
#     最終的に browse() は空リストへフォールスルーするためユーザー影響は無いが、
#     ログに ERROR + Traceback が毎回出る。対策: `tracks or []` にフォールバックする。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "for a in result.get(\"artists\") or []:"
if MARKER in s:
    print("library.py already patched (ytparsegaps), skip")
else:
    # (1) parseSearch() song/album 両分岐: result["artists"] の欠落ガード
    #     (ytartist-patch.py/ytartistcache-patch.py と同じく、song/album 両分岐に
    #     全く同一テキストが2箇所存在するため一括置換)
    OLD1 = '                            for a in result["artists"]:\n'
    NEW1 = '                            for a in result.get("artists") or []:\n'
    assert s.count(OLD1) == 2, f"expected 2 occurrences of result['artists'] anchor (got {s.count(OLD1)})"
    s = s.replace(OLD1, NEW1)

    # (2) parseSearch() artist 分岐: get_artist_albums() 呼び出しを個別 try/except で保護
    OLD2 = (
        '                        if "albums" in artistq:\n'
        '                            if "params" in artistq["albums"]:\n'
        '                                albums = self.backend.api.get_artist_albums(\n'
        '                                    artistq["channelId"],\n'
        '                                    artistq["albums"]["params"],\n'
        '                                )\n'
        '                                for album in albums:\n'
    )
    NEW2 = (
        '                        if "albums" in artistq:\n'
        '                            if "params" in artistq["albums"]:\n'
        '                                try:\n'
        '                                    albums = self.backend.api.get_artist_albums(\n'
        '                                        artistq["channelId"],\n'
        '                                        artistq["albums"]["params"],\n'
        '                                    )\n'
        '                                except Exception:\n'
        '                                    logger.warning(\n'
        '                                        "YTMusic failed getting albums for artist %s via get_artist_albums",\n'
        '                                        result["artist"],\n'
        '                                    )\n'
        '                                    albums = []\n'
        '                                for album in albums:\n'
    )
    assert s.count(OLD2) == 1, f"expected 1 occurrence of get_artist_albums anchor (got {s.count(OLD2)})"
    s = s.replace(OLD2, NEW2, 1)

    # (3) browse() ytmusic:artist:<id> (非アップロード) 分岐: tracks=None ガード
    OLD3 = (
        '                    res = self.backend.api.get_artist(bId)\n'
        '                    tracks = self.artistToTracks(res)\n'
        '                    logger.debug(\n'
        '                        \'YTMusic found %d songs for artist "%s" in library\',\n'
        '                        len(res["songs"]),\n'
        '                        res["name"],\n'
        '                    )\n'
        '                    return [Ref.track(uri=t.uri, name=t.name) for t in tracks]\n'
    )
    NEW3 = (
        '                    res = self.backend.api.get_artist(bId)\n'
        '                    tracks = self.artistToTracks(res)\n'
        '                    logger.debug(\n'
        '                        \'YTMusic found %d songs for artist "%s" in library\',\n'
        '                        len(res["songs"]),\n'
        '                        res["name"],\n'
        '                    )\n'
        '                    return [Ref.track(uri=t.uri, name=t.name) for t in tracks or []]\n'
    )
    assert s.count(OLD3) == 1, f"expected 1 occurrence of browse artist anchor (got {s.count(OLD3)})"
    s = s.replace(OLD3, NEW3, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() song/album分岐のartistsキー欠落KeyError、"
        "artist分岐のget_artist_albums()失敗が後続songs処理まで道連れにする不具合、"
        "browse() artist分岐のtracks=None未ガードイテレートを修正"
    )
