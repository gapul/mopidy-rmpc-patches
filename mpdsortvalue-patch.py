# mpdtagnames2-patch.pyはArtistSort/AlbumArtistSortをfind/list/フィルタ式で
# 認識できるようにした(mopidy core.library.search()の固定フィールド集合に
# 対応が無いため常に0件のみ許容する"phantom"タグとして登録)が、これは
# 「検索キーとして使えない」ことへの対応であって「既に取得済みTrackオブジェクト
# のArtist.sortname値を出力に含める」こととは無関係のまま放置されていた別の
# 不具合。translator.pyのtrack_to_mpd_format()(currentsong/playlistinfo/
# find/search等全コマンドが共有)はtrack.artists/track.album.artistsから
# Artist/AlbumArtistは出すのに対応するsortname値(ArtistSort/AlbumArtistSort)
# は一切読まずどの応答にも出力しない。同関数内のMUSICBRAINZ_ALBUMARTISTID/
# MUSICBRAINZ_ARTISTIDも同じくphantom(search不可)扱いだが、取得済みの値は
# concat_multi_valuesで出力する既存パターンがあり、ArtistSort/AlbumArtistSort
# だけがこの対称性から漏れていた。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# mopidy_ytmusic/library.pyはArtist(name=..., sortname=a["name"], ...)を
# 全てのArtist生成箇所(search/album/playlist/artist各ブラウズ経路、計11箇所)
# で実際に非空値付きで生成しており、値は既に存在するのにtranslator.pyが
# それを読まず捨てているだけの純粋なデータロス。mierak/rmpc
# (rmpcd/src/lua/lualib/mpd/types/song.rs)はsongメタデータを固定enumでなく
# 生のHashMap<String, MetadataTag>として保持し、artist_sort/
# album_artist_sortという専用Luaゲッターがmetadata["artistsort"]/
# metadata["albumartistsort"]を直接参照するため、ユーザーのLuaテーマ/
# スクリプトがsong.artist_sortを使うと本backendに対しては常にnilになる。
#
# 実機(127.0.0.1:6601、mopidy-ytmusic実アカウント)で修正前を確認済み:
#   find artist "YOASOBI" -> Artist: YOASOBI行は出るがArtistSort行が無い
#   (tagtypes応答にはArtistSort/AlbumArtistSort共に既に含まれ矛盾)
#
# 修正: Artist/AlbumArtistと全く同じmulti_tag_list()呼び出しパターンで
# sortname属性からArtistSort/AlbumArtistSortを追加出力するだけ(値の無い
# Artistはmulti_tag_list内部で自動的にスキップされ既存のtagtypes無効化/
# フィルタ式非対応には無変更)。
tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER = 'multi_tag_list(track.artists, "sortname", "ArtistSort")'
if MARKER in t:
    print("translator.py already patched for ArtistSort/AlbumArtistSort value output, skip")
else:
    old_artist = '''        *multi_tag_list(track.artists, "name", "Artist"),
        ("Album", track.album and track.album.name or ""),
    ]
'''
    assert t.count(old_artist) == 1, f"Artist anchor count={t.count(old_artist)}"
    new_artist = '''        *multi_tag_list(track.artists, "name", "Artist"),
        *multi_tag_list(track.artists, "sortname", "ArtistSort"),
        ("Album", track.album and track.album.name or ""),
    ]
'''
    t = t.replace(old_artist, new_artist, 1)

    old_albumartist = '''    if track.album is not None and track.album.artists:
        result += multi_tag_list(track.album.artists, "name", "AlbumArtist")

        musicbrainz_ids = concat_multi_values(
'''
    assert t.count(old_albumartist) == 1, f"AlbumArtist anchor count={t.count(old_albumartist)}"
    new_albumartist = '''    if track.album is not None and track.album.artists:
        result += multi_tag_list(track.album.artists, "name", "AlbumArtist")
        result += multi_tag_list(
            track.album.artists, "sortname", "AlbumArtistSort"
        )

        musicbrainz_ids = concat_multi_values(
'''
    t = t.replace(old_albumartist, new_albumartist, 1)

    open(tp, "w").write(t)
    print(
        "patched translator.py: ArtistSort/AlbumArtistSortの値出力を"
        "Artist/AlbumArtistと同じmulti_tag_listパターンで追加"
    )
