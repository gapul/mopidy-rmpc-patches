# mopidy_ytmusic.library.py の parseSearch() が、search album/search artist の応答に
# 含まれるアルバム/シングルの "year" キーへ計4箇所で未ガードの添字アクセス
# (result["year"] / album["year"] x2 / single["year"]) をしており、ytmusicapi が
# "year" を一度もセットしないケースで KeyError クラッシュする不具合を発見。
# TODO 全項目消化済みのため自走エージェントが rmpc 側の未実装コマンド調査 (新規ギャップ
# なしと確認済み) に続き、ytartistcache-patch.py/ytduration-patch.py/
# ytuploaddurationfix-patch.py が同種のバグを発見してきた実績を踏まえ mopidy_ytmusic の
# コード品質を再調査して発見した項目。
#
# ytmusicapi 1.12.1 (parsers/browsing.py) を実際にソース確認したところ、search
# album/artist 応答内のアルバム・シングルはいずれも共通の `_parse_album_single_subtitle()`
# を経由しており、その実装は:
#   if type_or_year := nav(result, SUBTITLE, True):
#       if type_or_year.isnumeric():
#           album_or_single["year"] = type_or_year
#       else:
#           album_or_single["type"] = type_or_year
#           if (year := nav(result, SUBTITLE2, True)) and year.isnumeric():
#               album_or_single["year"] = year
#   return album_or_single
# subtitle が数値そのものでなく (例: "Album"/"EP" 等の種別文字列)、かつ SUBTITLE2 が
# 存在しないか数値でない場合、"year" キーは一度もセットされない。つまり "year" は
# ytmusicapi の実装上 常に保証されたキーではなく、実データで普通に欠落しうる。
#
# 実害箇所(mopidy_ytmusic/library.py parseSearch()):
# 1. resultType=="album" 分岐の `date = result["year"]`: 自身の try/except で
#    ローカルに捕捉されるため search 全体は落ちないが、"year" 欠落のアルバム単体が
#    `search album "X"` の結果から静かに消える。
# 2. resultType=="artist" 分岐 (get_artist() のアルバム/シングル一覧を丸ごと
#    self.ARTISTS 登録後に処理する箇所) の `date=album["year"]` (2箇所:
#    get_artist_albums() 経由/artistq["albums"]["results"]直接の両経路) と
#    `date=single["year"]`: この3箇所はいずれもアーティスト1件分の処理全体を包む
#    唯一の try/except の中にあり、どれか1つでも "year" が欠けると例外が
#    artistToTracks/album/singles/songs の残り処理全てを巻き込んで中断させ、
#    `search artist "NAME"` がアーティスト自体は返しつつアルバム/シングル/曲を
#    まるごと0件にしてしまう (albumToTracks が既に同種の日付欠落を "0000"
#    フォールバックで解決済みなのと同じ根本原因の別経路)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'date = result.get("year", "0000")'
if MARKER in s:
    print("library.py already patched (parseSearch year fallback), skip")
else:
    # (1) resultType == "album" 分岐
    OLD_RESULT_YEAR = '                    try:\n                        if result["browseId"] not in self.ALBUMS:\n                            date = result["year"]\n'
    NEW_RESULT_YEAR = '                    try:\n                        if result["browseId"] not in self.ALBUMS:\n                            date = result.get("year", "0000")\n'
    assert s.count(OLD_RESULT_YEAR) == 1, (
        f"expected 1 occurrence of result['year'] anchor (got {s.count(OLD_RESULT_YEAR)})"
    )
    s = s.replace(OLD_RESULT_YEAR, NEW_RESULT_YEAR, 1)

    # (2) resultType == "artist" 分岐: get_artist_albums() 経由 / artistq["albums"]["results"] 直接
    #     の2箇所は完全に同一テキストのため一括置換 (両方とも同じフォールバックが正しい)
    OLD_ALBUM_YEAR = (
        '                                            artists=[\n'
        '                                                self.ARTISTS[result["browseId"]]\n'
        '                                            ],\n'
        '                                            date=album["year"],\n'
        '                                            musicbrainz_id="",\n'
    )
    NEW_ALBUM_YEAR = (
        '                                            artists=[\n'
        '                                                self.ARTISTS[result["browseId"]]\n'
        '                                            ],\n'
        '                                            date=album.get("year", "0000"),\n'
        '                                            musicbrainz_id="",\n'
    )
    assert s.count(OLD_ALBUM_YEAR) == 2, (
        f"expected 2 occurrences of album['year'] anchor (got {s.count(OLD_ALBUM_YEAR)})"
    )
    s = s.replace(OLD_ALBUM_YEAR, NEW_ALBUM_YEAR)

    # (3) resultType == "artist" 分岐: singles
    OLD_SINGLE_YEAR = '                                        artists=[self.ARTISTS[result["browseId"]]],\n                                        date=single["year"],\n'
    NEW_SINGLE_YEAR = '                                        artists=[self.ARTISTS[result["browseId"]]],\n                                        date=single.get("year", "0000"),\n'
    assert s.count(OLD_SINGLE_YEAR) == 1, (
        f"expected 1 occurrence of single['year'] anchor (got {s.count(OLD_SINGLE_YEAR)})"
    )
    s = s.replace(OLD_SINGLE_YEAR, NEW_SINGLE_YEAR, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch() の album/artist分岐 (計4箇所) の "
        '"year" 決め打ちアクセスを .get(..., "0000") フォールバックへ修正'
    )
