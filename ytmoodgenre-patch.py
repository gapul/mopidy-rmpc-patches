# library.py の browse() `ytmusic:mood:<params>:<browseId>` (Mood and Genre
# Playlists の各カテゴリページ、例: 「Feel Good」) が、セクション内の全アイテムを
# 無条件に「musicTwoRowItemRenderer = プレイリスト/アルバムタイル (browseEndpoint
# 持ち)」と決め打ちして browseId を nav() で取り出す不具合を修正。
#
# 実機 (dev mopidy 6601, ytmusic 実アカウント) で `lsinfo "YouTube Music/Mood and
# Genre Playlists/<カテゴリ>"` を全カテゴリ実際に叩いて mopidy.log の警告
# (本パッチの前段実装が出す "YTMusic skipping unparseable mood/genre item"、
# DEBUGDUMP付きの調査用一時ビルドで) の実データを解析して特定した。
# 一部カテゴリ (例: 演歌/懐メロ系) は musicTwoRowItemRenderer タイルが
# プレイリストではなく「単曲のミュージックビデオ」を指しており、
# 'navigationEndpoint': {'watchEndpoint': {'videoId': ...}} を持つのみで
# 'navigationEndpoint': {'browseEndpoint': {'browseId': ...}} が存在しない
# (実データ例: {'musicTwoRowItemRenderer': {'title': {'runs': [{'text':
# 'ジンギスカン - Genghis khan (Dschinghis Khan) Odottemita'}]}, ...
# 'navigationEndpoint': {'watchEndpoint': {'videoId': 'DHbIIBmqHsw', ...}}}})。
# 現状の実装は NAVIGATION_BROWSE_ID を無条件 nav() で取りに行きKeyErrorを送出し、
# さらに1アイテム分の処理が for ループ全体を包む唯一の try/except の中にあるため、
# この1件のKeyErrorでそのカテゴリページの全セクション・全アイテムが道連れになり
# 空リストになる (ret を作りかけても return できず except 節に落ちる)。
#
# 別途 musicCarouselShelfRenderer/gridRenderer 直下に musicTwoRowItemRenderer
# ではなく musicResponsiveListItemRenderer (個々の楽曲を表す list item) を
# 混在させるカテゴリもあるため、それも合わせて対応する。
#
# 対策: アイテムごとに実際に持つ鍵で分岐する。
#   - musicTwoRowItemRenderer + browseEndpoint.browseId: 従来通り Ref.playlist。
#   - musicTwoRowItemRenderer + watchEndpoint.videoId (browseIdなし): 単曲の
#     ミュージックビデオ扱いで Ref.track として拾う。
#   - musicResponsiveListItemRenderer: 既存の ythistory-patch/ytliked-patch と
#     同じく ytmusicapi.parsers.playlists.parse_playlist_items() で videoId/title
#     を取り出し Ref.track として扱う (このカテゴリページ限定の楽曲であり、
#     ライブラリに存在しないためアルバム/アーティスト解決はできず Track ではなく
#     browse 用の Ref.track に留める)。
#   - どちらでもない/パース失敗: そのアイテムだけ warning ログを出して読み飛ばし、
#     残りのアイテム・セクションは継続する (1件の異常が全体を道連れにしない、
#     ytparsegaps-patch/ytautoplaylistfix-patch と同じ流儀)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "YTMusic skipping unparseable mood/genre item"
if MARKER in s:
    print("library.py already patched (ytmoodgenre), skip")
else:
    OLD_IMPORTS = """from ytmusicapi.navigation import (
    MUSIC_SHELF,
    NAVIGATION_BROWSE_ID,
    SECTION_LIST,
    SINGLE_COLUMN_TAB,
    TITLE_TEXT,
    nav,
)
from ytmusicapi.parsers.playlists import parse_playlist_items"""
    NEW_IMPORTS = """from ytmusicapi.navigation import (
    MRLIR,
    MUSIC_SHELF,
    NAVIGATION_BROWSE_ID,
    NAVIGATION_VIDEO_ID,
    SECTION_LIST,
    SINGLE_COLUMN_TAB,
    TITLE_TEXT,
    nav,
)
from ytmusicapi.parsers.playlists import parse_playlist_items"""
    assert s.count(OLD_IMPORTS) == 1, f"expected 1 occurrence of imports anchor (got {s.count(OLD_IMPORTS)})"
    s = s.replace(OLD_IMPORTS, NEW_IMPORTS, 1)

    OLD = """                    if len(key):
                        for item in nav(sect, key):
                            title = nav(
                                item, ["musicTwoRowItemRenderer"] + TITLE_TEXT
                            ).strip()
                            #                           if 'subtitle' in item['musicTwoRowItemRenderer']:
                            #                               title += ' ('
                            #                               for st in item['musicTwoRowItemRenderer']['subtitle']['runs']:
                            #                                   title += st['text']
                            #                               title += ')'
                            brId = nav(
                                item,
                                ["musicTwoRowItemRenderer"]
                                + NAVIGATION_BROWSE_ID,
                            )
                            ret.append(
                                Ref.playlist(
                                    uri=f"ytmusic:playlist:{brId}", name=title
                                )
                            )
                return ret"""
    NEW = """                    if len(key):
                        for item in nav(sect, key):
                            try:
                                if "musicTwoRowItemRenderer" in item:
                                    row = item["musicTwoRowItemRenderer"]
                                    title = nav(row, TITLE_TEXT, True)
                                    title = title.strip() if title else ""
                                    brId = nav(row, NAVIGATION_BROWSE_ID, True)
                                    vidId = nav(row, NAVIGATION_VIDEO_ID, True)
                                    if brId:
                                        ret.append(
                                            Ref.playlist(
                                                uri=f"ytmusic:playlist:{brId}",
                                                name=title,
                                            )
                                        )
                                    elif vidId:
                                        # プレイリストではなく単曲のミュージック
                                        # ビデオを指すタイル (browseEndpointなし)
                                        ret.append(
                                            Ref.track(
                                                uri=f"ytmusic:track:{vidId}",
                                                name=title,
                                            )
                                        )
                                    else:
                                        logger.warning(
                                            'YTMusic skipping unparseable mood/genre item on "%s": '
                                            "musicTwoRowItemRenderer without browseId/videoId",
                                            uri,
                                        )
                                elif MRLIR in item:
                                    songs = parse_playlist_items([item])
                                    song = songs[0] if songs else None
                                    if song and song.get("videoId"):
                                        ret.append(
                                            Ref.track(
                                                uri=f"ytmusic:track:{song['videoId']}",
                                                name=song.get("title") or "",
                                            )
                                        )
                            except Exception:
                                logger.warning(
                                    'YTMusic skipping unparseable mood/genre item on "%s": keys=%s',
                                    uri,
                                    list(item.keys()) if isinstance(item, dict) else type(item),
                                )
                return ret"""
    assert s.count(OLD) == 1, f"expected 1 occurrence of mood/genre item anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: ytmusic:mood: (Mood and Genre Playlists の各カテゴリ) が"
        "単曲のミュージックビデオを指すmusicTwoRowItemRenderer (browseEndpointなし)"
        "やmusicResponsiveListItemRenderer (曲のlist item) をプレイリストタイル"
        "決め打ちで扱いKeyErrorになり、そのアイテム1件のせいでカテゴリページ全体が"
        "空になる不具合を修正。単曲itemはRef.trackとして拾い、未知形状は1件だけ"
        "読み飛ばして残りを継続するようにした"
    )
