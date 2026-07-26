# music_db.py の `find()` は docstring 通り GMPC 由来の `find album "X" artist "Y"`
# (アルバムの曲一覧取得) 用途のため、query に "artist"/"albumartist"/"composer"/
# "performer" があれば _artist_as_track() の、"album" があれば _album_as_track() の
# プレースホルダ変換(架空の Track、Time は常に0)をスキップし実トラックのみを返す
# ガードを持つ。一方 `search()` は docstring 自身が「find とパラメータの意味は同じ、
# 大文字小文字を区別しない点のみ違う」と明記するにもかかわらずこのガードが無く、
# artists/albums のプレースホルダを無条件に結果へ混入させてしまう非対称な不具合。
# TODO 全項目消化済みのため自走エージェントが調査して新規発見・追加した項目。
#
# 実害: rmpc (mierak/rmpc) の検索ペイン (src/ui/panes/search/mod.rs) は既定で
# fold_case (大文字小文字を区別しない) が有効な場合 MPD の `search` コマンドを使う。
# Album/Artist 列を対象に検索すると、find では実トラックのみ返る場面でも search では
# 無関係な全アルバム/全アーティスト分のプレースホルダ行が実データの前に大量に
# 列挙され、実データがノイズに埋もれる。
#
# 検証: dev mopidy (127.0.0.1:6601、mopidy-ytmusic 実アカウント) で
# `find album "THE BOOK for,"` は実12曲のみを返す (ytfindalbumtracks-patch.py 適用済み)
# のに対し、`search album "the book for,"` (部分一致・大文字小文字無視) は無関係な
# 十数アルバム分の _album_as_track() プレースホルダが混入したうえで実12曲が続くことを
# 確認済み。既存 BACKLOG のytfindalbumtracks-patch.py項目はこの現象に触れているが、
# それは「mopidy_ytmusic/library.py 側の search() の別バグ修正」の回帰確認メモであり、
# music_db.py 側の find/search 非対称自体を不具合として扱ってはいない。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "def search(context, *args):\n    \"\"\"\n    *musicpd.org, music database section:*\n\n        ``search {TYPE} {WHAT} [...]``"
assert MARKER in s, "search() の想定シグネチャ/docstringが見つからない"

old_block = (
    '    results = context.core.library.search(query).get()\n'
    '    artists = [_artist_as_track(a) for a in _get_artists(results)]\n'
    '    albums = [_album_as_track(a) for a in _get_albums(results)]\n'
    '    tracks = _get_tracks(results)\n'
    '    result_tracks = artists + albums + tracks\n'
)

MARKER_DONE = (
    '    results = context.core.library.search(query).get()\n'
    '    result_tracks = []\n'
    '    if (\n'
    '        "artist" not in query\n'
)
if MARKER_DONE in s:
    print("music_db.py already patched (search placeholder guard), skip")
else:
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '    results = context.core.library.search(query).get()\n'
        '    result_tracks = []\n'
        '    if (\n'
        '        "artist" not in query\n'
        '        and "albumartist" not in query\n'
        '        and "composer" not in query\n'
        '        and "performer" not in query\n'
        '    ):\n'
        '        result_tracks += [_artist_as_track(a) for a in _get_artists(results)]\n'
        '    if "album" not in query:\n'
        '        result_tracks += [_album_as_track(a) for a in _get_albums(results)]\n'
        '    result_tracks += _get_tracks(results)\n'
    )
    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: search() が find() と同じ "
        "artist/albumartist/composer/performer/album ガードを持つよう修正 "
        "(query が該当タグを直接指定する場合は artists/albums プレースホルダを混入させない)"
    )
