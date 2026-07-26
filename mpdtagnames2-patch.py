# mpdtagnames-patch.py が追加した「実MPD(Names.cxx)には存在するがmopidyの
# Track/Album/Artistモデルには対応フィールドが無いタグ群」の"phantomタグ"機構
# (タグ名としては認識、backendへは送らず常に空/0件を返す)は18種を追加したが、
# それ以前から存在していた"base"19種のタグのうち以下5種が元々
# _LIST_MAPPING/_LIST_NAME_MAPPING/_PHANTOM_TAG_FIELDSに未登録のまま
# 放置されていた不具合。TAGTYPE_LIST(tagtypes応答)には元々含まれるため
# 「tagtypesは対応を広告するのにfind/list/フィルタ式では使えない」という
# 同種の非対称が引き続き残っていた:
#   ArtistSort, AlbumArtistSort, Name, MUSICBRAINZ_ALBUMARTISTID, X-AlbumUri
# TODO 全項目消化済みのため自走エージェントがgeneral-purposeサブエージェントへ
# 調査を委任し新規発見した項目 (mpdtagnames-patch.py適用後の残存ギャップ)。
#
# 実機(127.0.0.1:6601、mopidy-ytmusic backend)で修正前の不具合を確認済み:
#   find artistsort "Test"              -> ACK [2@0] {find} incorrect arguments
#   find AlbumArtistSort "Test"         -> ACK [2@0] {find} incorrect arguments
#   find Name "Test"                    -> ACK [2@0] {find} incorrect arguments
#   find MUSICBRAINZ_ALBUMARTISTID "x"  -> ACK [2@0] {find} incorrect arguments
#   find "X-AlbumUri" "Test"            -> ACK [2@0] {find} incorrect arguments
#   list ArtistSort                     -> ACK [2@0] {list} Unknown tag type: ArtistSort
#   find "(ArtistSort == \"Test\")"     -> ACK [2@0] {find} Unknown filter type: ArtistSort
# 一方 `tagtypes` 応答には5タグとも既に含まれており対応広告と実際の扱いが矛盾していた。
#
# mopidyのTrack/Album/ArtistモデルにはArtistSort/AlbumArtistSort用のソート専用
# フィールドが無く(Artist.sortnameはあるがmopidy core.library.search()の固定
# フィールド集合SEARCH_FIELDS/DISTINCT_FIELDSには含まれずbackendへ渡すと
# ValidationErrorで無応答切断になる、mpdtagnames-patch.py参照)、
# MUSICBRAINZ_ALBUMARTISTID/Nameも同様に固定フィールド集合に無い
# (X-AlbumUriはmopidy独自導入タグでそもそも対応フィールド概念が無い)。
# よってmpdtagnames-patch.pyと全く同じ「phantomタグ」機構
# (_PHANTOM_TAG_FIELDS)へこの5種を追加登録するだけでよい。書き込みサイト側の
# 分岐コード(旧式/新式パーサ、list_grouped/count_grouped)は
# mpdtagnames-patch.pyが既に汎用化済みのため変更不要、3つの集合
# (_LIST_MAPPING/_LIST_NAME_MAPPING/_PHANTOM_TAG_FIELDS)にキーを足すだけで足りる。
mp = "mopidy_mpd/protocol/music_db.py"
m = open(mp).read()

MARKER = "musicbrainz_albumartistid"
if MARKER in m:
    print("music_db.py already patched for artistsort/albumartistsort/name/musicbrainz_albumartistid/x-albumuri, skip")
else:
    old_list_mapping_tail = '''    "musicbrainz_releasetrackid": "musicbrainz_releasetrackid",
    "musicbrainz_workid": "musicbrainz_workid",
    "musicbrainz_releasegroupid": "musicbrainz_releasegroupid",
}
'''
    assert m.count(old_list_mapping_tail) == 1, f"_LIST_MAPPING tail anchor count={m.count(old_list_mapping_tail)}"
    new_list_mapping_tail = '''    "musicbrainz_releasetrackid": "musicbrainz_releasetrackid",
    "musicbrainz_workid": "musicbrainz_workid",
    "musicbrainz_releasegroupid": "musicbrainz_releasegroupid",
    # mpdtagnames-patch.py適用後もなお未登録のまま残っていた"base"タグ5種
    # (tagtypesは広告するがfind/list/フィルタ式では使えなかった非対称の続き)。
    # mopidy core.library側に対応フィールドが無いため同じくphantom扱い。
    "artistsort": "artistsort",
    "albumartistsort": "albumartistsort",
    "name": "name",
    "musicbrainz_albumartistid": "musicbrainz_albumartistid",
    "x-albumuri": "x-albumuri",
}
'''
    m = m.replace(old_list_mapping_tail, new_list_mapping_tail, 1)

    old_name_mapping_tail = '''    "musicbrainz_releasetrackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_workid": "MUSICBRAINZ_WORKID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
}
'''
    assert m.count(old_name_mapping_tail) == 1, f"_LIST_NAME_MAPPING tail anchor count={m.count(old_name_mapping_tail)}"
    new_name_mapping_tail = '''    "musicbrainz_releasetrackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_workid": "MUSICBRAINZ_WORKID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
    "artistsort": "ArtistSort",
    "albumartistsort": "AlbumArtistSort",
    "name": "Name",
    "musicbrainz_albumartistid": "MUSICBRAINZ_ALBUMARTISTID",
    "x-albumuri": "X-AlbumUri",
}
'''
    m = m.replace(old_name_mapping_tail, new_name_mapping_tail, 1)

    old_phantom_tail = '''    "musicbrainz_releasetrackid", "musicbrainz_workid",
    "musicbrainz_releasegroupid",
})
'''
    assert m.count(old_phantom_tail) == 1, f"_PHANTOM_TAG_FIELDS tail anchor count={m.count(old_phantom_tail)}"
    new_phantom_tail = '''    "musicbrainz_releasetrackid", "musicbrainz_workid",
    "musicbrainz_releasegroupid",
    "artistsort", "albumartistsort", "name", "musicbrainz_albumartistid",
    "x-albumuri",
})
'''
    m = m.replace(old_phantom_tail, new_phantom_tail, 1)

    open(mp, "w").write(m)
    print(
        "patched music_db.py: ArtistSort/AlbumArtistSort/Name/"
        "MUSICBRAINZ_ALBUMARTISTID/X-AlbumUriの5タグをphantomとして"
        "_LIST_MAPPING/_LIST_NAME_MAPPING/_PHANTOM_TAG_FIELDSへ追加登録"
    )
