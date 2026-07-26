# dev mopidy (6601, ytmusic 実アカウント) を実際に叩いて発見した不具合を修正する。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが mopidy.log を
# 監視する中で `YTMusic: skipping unparseable search result ('artist')` という
# 警告 (ytparsegaps-patch.py が追加した parseSearch() 最外周の per-item try/except
# による最終フォールバック) を発見し、原因を追った。
#
# ytmusicapi の search() は通常の "Artists" カテゴリの結果とは別に、検索語がよく
# 知られたアーティスト名と厳密一致する場合 (実データ "BTS" 等で再現) 、専用の
# "Top result" カード (ytmusicapi/parsers/search.py の parse_top_result()) を
# 結果リストの先頭に追加する。このカードが resultType=="artist" のとき、
# parse_top_result() は browseId を一切設定せず、単数形の "artist" (アーティスト名
# 文字列) キーの代わりに parse_song_runs() が返す複数形の "artists" (dict のリスト)
# キーを持つ、通常の "Artists" カテゴリ結果とは異なる形の dict を返す。
#
# parseSearch() の artist 分岐は browseId/artist キーが常に存在する前提で書かれて
# おり、(1) `field == "artist" and ... result["artist"] ...` (完全一致判定、
# find コマンドの exact=True 経路) と (2) `self.backend.api.get_artist(result["browseId"])`
# が Top result カードに対し KeyError を送出する。後者は try で保護されているが、
# その except 節自身が `logger.exception(..., result["artist"])` で同じ
# KeyError をもう一度送出してしまい (albums 取得失敗時の
# `logger.warning(..., result["artist"])` も同様)、本来のエラー原因を隠したまま
# ytparsegaps-patch.py の最外周 per-item except まで伝播する。機能上はその1件の
# 結果が静かにスキップされるだけで search 全体やプロセスは落ちないが、
# (a) Top result カードとして返ってきたアーティスト (検索語と厳密一致する
# もっとも確からしい候補) が常に失われる、(b) ログが本当の原因 (browseId 欠落)
# ではなく二次的な KeyError を報告し診断を妨げる、という実害がある。
#
# 対策: artist 分岐の先頭で browseId 欠落を検知し (Top result 由来と判定できる
# ため) 早期に continue でスキップする。あわせて例外ハンドラ2箇所の
# `result["artist"]` を `result.get("artist", result.get("browseId", "?"))`
# に変え、想定外の形の dict が来ても二次例外でログを汚さないようにする。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'if "browseId" not in result:\n                        # YTMusic'
if MARKER in s:
    print("library.py already patched (yttopresultartist), skip")
else:
    OLD1 = (
        '                elif result["resultType"] == "artist":\n'
        '                    if field == "artist" and not any(\n'
        '                        q.casefold() == result["artist"].casefold() for q in queries\n'
        '                    ):\n'
        '                        continue\n'
        '                    try:\n'
        '                        artistq = self.backend.api.get_artist(result["browseId"])\n'
    )
    NEW1 = (
        '                elif result["resultType"] == "artist":\n'
        '                    if "browseId" not in result:\n'
        '                        # YTMusic の "Top result" カード扱いのartistはbrowseId/\n'
        '                        # artist(単数)キーを持たずparse_song_runsの"artists"(複数)\n'
        '                        # 構造になるため解決不能、静かにスキップする\n'
        '                        continue\n'
        '                    if field == "artist" and not any(\n'
        '                        q.casefold() == result.get("artist", "").casefold() for q in queries\n'
        '                    ):\n'
        '                        continue\n'
        '                    try:\n'
        '                        artistq = self.backend.api.get_artist(result["browseId"])\n'
    )
    assert s.count(OLD1) == 1, f"expected 1 occurrence of artist分岐冒頭 anchor (got {s.count(OLD1)})"
    s = s.replace(OLD1, NEW1, 1)

    OLD2 = (
        '                                except Exception:\n'
        '                                    logger.warning(\n'
        '                                        "YTMusic failed getting albums for artist %s via get_artist_albums",\n'
        '                                        result["artist"],\n'
        '                                    )\n'
        '                                    albums = []\n'
    )
    NEW2 = (
        '                                except Exception:\n'
        '                                    logger.warning(\n'
        '                                        "YTMusic failed getting albums for artist %s via get_artist_albums",\n'
        '                                        result.get("artist", result.get("browseId", "?")),\n'
        '                                    )\n'
        '                                    albums = []\n'
    )
    assert s.count(OLD2) == 1, f"expected 1 occurrence of get_artist_albums except anchor (got {s.count(OLD2)})"
    s = s.replace(OLD2, NEW2, 1)

    OLD3 = (
        '                    except Exception:\n'
        '                        logger.exception(\n'
        '                            "YTMusic failed parsing artist %s", result["artist"]\n'
        '                        )\n'
    )
    NEW3 = (
        '                    except Exception:\n'
        '                        logger.exception(\n'
        '                            "YTMusic failed parsing artist %s",\n'
        '                            result.get("artist", result.get("browseId", "?")),\n'
        '                        )\n'
    )
    assert s.count(OLD3) == 1, f"expected 1 occurrence of artist分岐末尾except anchor (got {s.count(OLD3)})"
    s = s.replace(OLD3, NEW3, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() artist分岐がTop resultカード "
        "(browseId欠落、artist単数キーの代わりにartists複数キー) を"
        "二次的なKeyErrorで診断不能にしたまま失っていた不具合を修正"
    )
