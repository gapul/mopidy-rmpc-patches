# mpdsortvalue-patch.pyはfind/search等の応答本文にArtistSort/AlbumArtistSort
# タグ「値」(track.artists[].sortname)を出力するようにしたが、これは表示側だけの
# 修正で、`sort ArtistSort`/`sort AlbumArtistSort`修飾子が実際に使うソートキー
# (music_db.pyの`_mpd_sort_value`)は無関係のまま放置されていた別の不具合。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 現状: `_SORT_MAPPING`が`"artistsort": "artist"`/`"albumartistsort":
# "albumartist"`と、ArtistSort/AlbumArtistSort要求を最初から内部フィールド名
# "artist"/"albumartist"へ潰してしまうため、「ArtistSort由来のソートか」という
# 情報自体が`_mpd_sort_value(track, field)`へ渡る前に失われている。結果、
# `sort ArtistSort`は常に`sort Artist`と完全に同じ結果になり、
# track.artists[].sortnameがソート順に一切影響しない。
#
# 実MPD本体(raw.githubusercontent.comでsrc/tag/Tag.cxxを直接確認、WebFetchの
# 要約ではなく生ソースで確認): `Tag::GetSortValue(TagType type)`は
#   1. まずtype自身(例: TAG_ARTIST_SORT)の値を試す
#   2. 無ければ`DecaySort(type)`(ARTIST_SORT->ARTIST,
#      ALBUM_ARTIST_SORT->ALBUM_ARTIST)の値を試す
#   3. 無ければ`Fallback()`(ALBUM_ARTIST->ARTIST)経由でGetSortValueを再帰
# という3段フォールバックで、ArtistSortは「ArtistSort値→Artist値→空」、
# AlbumArtistSortは「AlbumArtistSort値→AlbumArtist値→Artist値→空」の順に
# 解決される。つまり実MPDは常にSORT版タグを最優先し、無い時だけ非SORT版へ
# フォールバックするが、mopidy_mpdは最初からSORT版タグの存在を無視し常に
# 非SORT版のみを使っている。
#
# 修正: `_SORT_MAPPING`で"artistsort"/"albumartistsort"を"artist"/
# "albumartist"へ潰さず独立フィールド名のまま渡すよう変更し、
# `_mpd_sort_value`に"artistsort"/"albumartistsort"分岐を追加。
# 既存の"albumartist"分岐が既に「album.artists→無ければartist」という
# Fallback(ALBUM_ARTIST->ARTIST)相当のフォールバックを持つため、
# "albumartistsort"は「album.artists[].sortname→無ければ既存"albumartist"
# 分岐(album.artists[].name→無ければartist)」に委譲するだけで実MPDの
# 3段フォールバック全体を再現できる。current_playlist.pyの
# playlistfind/playlistsearch(`_PF_SORT_MAPPING = dict(_SORT_MAPPING)`、
# `_mpd_sort_value`を共有、mpdplaylistfindsortprio-patch.py)は
# music_db.pyのこの2つのオブジェクトをそのまま再利用しているため、
# ここを直すだけで両方に自動的に波及する。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'field == "artistsort"'
if MARKER in s:
    print("ArtistSort/AlbumArtistSort sort-key support already present, skip")
else:
    old_mapping = '''_SORT_MAPPING.update(
    {
        "artistsort": "artist",
        "albumsort": "album",
        "albumartistsort": "albumartist",
        "last-modified": "last_modified",
    }
)
'''
    assert s.count(old_mapping) == 1, f"mapping anchor count={s.count(old_mapping)}"
    new_mapping = '''_SORT_MAPPING.update(
    {
        "artistsort": "artistsort",
        "albumsort": "album",
        "albumartistsort": "albumartistsort",
        "last-modified": "last_modified",
    }
)
'''
    s = s.replace(old_mapping, new_mapping, 1)

    old_value = '''def _mpd_sort_value(track, field):
    if field == "artist":
        return ", ".join(a.name for a in track.artists if a.name).lower()
    if field == "albumartist":
        artists = track.album.artists if track.album else []
        value = ", ".join(a.name for a in artists if a.name)
        return value.lower() if value else _mpd_sort_value(track, "artist")
'''
    assert s.count(old_value) == 1, f"value anchor count={s.count(old_value)}"
    new_value = '''def _mpd_sort_value(track, field):
    if field == "artistsort":
        value = ", ".join(a.sortname for a in track.artists if a.sortname)
        return value.lower() if value else _mpd_sort_value(track, "artist")
    if field == "albumartistsort":
        artists = track.album.artists if track.album else []
        value = ", ".join(a.sortname for a in artists if a.sortname)
        return value.lower() if value else _mpd_sort_value(track, "albumartist")
    if field == "artist":
        return ", ".join(a.name for a in track.artists if a.name).lower()
    if field == "albumartist":
        artists = track.album.artists if track.album else []
        value = ", ".join(a.name for a in artists if a.name)
        return value.lower() if value else _mpd_sort_value(track, "artist")
'''
    s = s.replace(old_value, new_value, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: sort ArtistSort/AlbumArtistSort が"
        "sortname値を実MPD相当の3段フォールバックで参照するよう修正"
    )
