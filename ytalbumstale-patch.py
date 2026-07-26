# mopidy_ytmusic.library.py の parseSearch() のうち、実際のリリース年 ("year") を
# 持つ3箇所 (resultType=="album"分岐、resultType=="artist"分岐の get_artist_albums()/
# artistq["albums"]["results"] 経由のalbums、同分岐のsingles) が、いずれも
# `if X["browseId"] not in self.ALBUMS:` というガードの内側でのみ self.ALBUMS を
# 構築しており、同じ browseId のアルバムが先に他経路(resultType=="song"分岐、
# playlistToTracks()、uploadArtistToTracks()。いずれも date="0000" 固定の
# プレースホルダしか作れない)で self.ALBUMS に登録済みだと、実在する year を
# 一切反映せず古いプレースホルダを永久に使い続ける不具合を発見。
#
# ytstalecache-patch.py が self.TRACKS について「一度でも簡易版で書き込まれると
# 二度と豊富なデータで上書きされない」不具合を修正し、ytalbumfix-patch.py/
# ytuploadfix-patch.py が albumToTracks()/uploadAlbumToTracks() の self.ALBUMS
# ガードを既に無条件上書きに修正済みだが、parseSearch() 内の上記3箇所の
# self.ALBUMS ガードだけは対称性が欠けたまま残っていた
# (resultType=="song"分岐・artist経由songs分岐の self.ALBUMS ガードは date="0000"
# しか作れず実データを持たないため、上書き済みでも意味がなく対象外)。
#
# 実害: mopidy再起動直後に「同じアルバムの曲」を含む search/find が先に
# resultType=="song" 側でヒットすると、そのアルバムは date="0000" のまま
# self.ALBUMS に焼き付く。続けて `find album "NAME"`/`search album "NAME"`
# (resultType=="album"分岐) や `find albumartist "ARTIST"` 由来のアーティスト
# ブラウズ(get_artist_albums()/singles) で同じ browseId が実際の year を伴って
# 返ってきても反映されず、以後 mopidy プロセスの寿命が尽きるまで
# `Date: 0000` を返し続ける (rmpc のアルバム年表示・`sort Date` を汚染する)。
#
# 修正: 3箇所の `if X not in self.ALBUMS:` を `if True:  # ...` へ変更し、
# 常に最新の year で self.ALBUMS を再構築する (comment-outでガード自体の
# 意図を残しつつ無条件上書きにする、ytalbumfix-patch.py 等と同じ方針)。

p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "既存分のdateが古い場合でも実データで上書きする"
if MARKER in s:
    print("library.py already patched (albumstale), skip")
else:
    OLD_ALBUM = '                        if result["browseId"] not in self.ALBUMS:'
    NEW_ALBUM = (
        '                        if True:  # result["browseId"] not in self.ALBUMS: '
        f'({MARKER})'
    )
    assert s.count(OLD_ALBUM) == 1, (
        f"expected 1 occurrence of parseSearch album-branch ALBUMS-guard anchor (got {s.count(OLD_ALBUM)})"
    )
    s = s.replace(OLD_ALBUM, NEW_ALBUM, 1)

    OLD_ARTIST_ALBUMS = '                                    if album["browseId"] not in self.ALBUMS:'
    NEW_ARTIST_ALBUMS = (
        '                                    if True:  # album["browseId"] not in self.ALBUMS: '
        f'({MARKER})'
    )
    assert s.count(OLD_ARTIST_ALBUMS) == 2, (
        f"expected 2 occurrences of parseSearch artist->albums ALBUMS-guard anchor (got {s.count(OLD_ARTIST_ALBUMS)})"
    )
    s = s.replace(OLD_ARTIST_ALBUMS, NEW_ARTIST_ALBUMS)

    OLD_SINGLES = '                                if single["browseId"] not in self.ALBUMS:'
    NEW_SINGLES = (
        '                                if True:  # single["browseId"] not in self.ALBUMS: '
        f'({MARKER})'
    )
    assert s.count(OLD_SINGLES) == 1, (
        f"expected 1 occurrence of parseSearch artist->singles ALBUMS-guard anchor (got {s.count(OLD_SINGLES)})"
    )
    s = s.replace(OLD_SINGLES, NEW_SINGLES, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: parseSearch()のalbum分岐/artist経由albums・singles分岐(計3箇所)が"
        "実dateを持つ新データで既存の0000プレースホルダを上書きしない不具合を修正"
    )
