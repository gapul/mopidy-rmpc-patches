# find/search/findadd/searchadd/searchaddpl/playlistfind/playlistsearchが共有する
# `sort TYPE`修飾子(music_db.pyの_SORT_MAPPING)は"Last-Modified"を疑似sortタイプ
# として認識するが、実MPD本体で常にこれと対になっているはずの"Added"だけが
# 登録されておらず`sort Added`が即座に`ACK Unknown sort type: Added`になる
# 不具合を修正。TODO全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体(gh rawでsrc/command/DatabaseCommands.cxx ParseSortTag()を確認)は
#   if (StringIsEqualIgnoreCase(s, "Last-Modified"))
#       return TagType(SORT_TAG_LAST_MODIFIED);
#   if (StringIsEqualIgnoreCase(s, "Added"))
#       return TagType(SORT_TAG_ADDED);
# という隣接する2分岐でLast-Modified/Addedを常に有効な擬似sortタイプとして
# 対で登録しており(src/song/Filter.hxxでもSORT_TAG_LAST_MODIFIED/SORT_TAG_ADDED
# は隣接する定数)、QueueCommands.cxx(playlistfind/playlistsearch用)にも
# 同一の対が存在する。mopidy_mpd側は"last-modified"のみ_SORT_MAPPINGに
# 登録済みで"added"が丸ごと抜けていた。
#
# 既存のmpdadded-patch.pyはキュー内tlidの`Added:`タグ「表示」(MPD0.24+)を
# 実装したもので本項目とは無関係(sort修飾子の話ではない)。
#
# 修正: _SORT_MAPPINGに"added": "added"を追加するだけ(track_no/disc_no等と
# 同様の恒等マッピング)。mopidy.models.Trackにはaddedという属性が無いため
# 既存の_mpd_sort_value()の汎用フォールバック(getattr(track, field, None)
# or "")がfield=="added"に対して常に""を返し、安定ソートの無変化(no-op)と
# なる。これは実MPD自身がTitleSort/ComposerSort(Tag.cxx DecaySort()に
# フォールバック定義が無く「値が無ければ空扱い」)に対して取る挙動と
# 同じクラスの安全な振る舞いであり、新規のデータ捏造は不要。
# current_playlist.pyの_PF_SORT_MAPPING = dict(_SORT_MAPPING)
# (mpdplaylistfindsortprio-patch.py)はmusic_db.pyのこの辞書をそのまま
# 複製するため、この1箇所の修正でplaylistfind/playlistsearchにも自動的に
# 波及する。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = '"added": "added"'
if MARKER in s:
    print("sort Added support already present, skip")
else:
    old_mapping = '''_SORT_MAPPING.update(
    {
        "artistsort": "artistsort",
        "albumsort": "album",
        "albumartistsort": "albumartistsort",
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
        "added": "added",
    }
)
'''
    s = s.replace(old_mapping, new_mapping, 1)

    open(p, "w").write(s)
    print("patched music_db.py: sort Added 修飾子をサポート")
