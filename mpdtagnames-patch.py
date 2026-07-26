# mopidy_mpd/protocol/tagtype_list.py の TAGTYPE_LIST (`tagtypes`コマンドが
# 広告する既知タグ名集合) と music_db.py の _LIST_MAPPING/_LIST_NAME_MAPPING
# (find/search/list/count/filter式が認識するタグ名。_SEARCH_MAPPING/
# _SORT_MAPPINGは両者ともこれから自動導出される) が、実MPD本体が実際に認識する
# タグ名の一部(旧世代の18種+独自X-AlbumUriのみ)しかカバーしておらず、
# MPD 0.24以降に追加された標準タグ名を丸ごと未登録にしている不具合。
# TODO 全項目消化済みのため自走エージェントがgeneral-purposeサブエージェントへ
# 調査を委任し新規発見した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、gh apiで`src/tag/Names.cxx`を実際に取得し
# 確認) が認識するタグ名は本実装の18種に対し以下が丸ごと欠落している:
#   AlbumSort, TitleSort, Mood, OriginalDate, ComposerSort, Conductor, Work,
#   Movement, MovementNumber, ShowMovement, Ensemble, Location, Grouping,
#   DiscSubtitle, Label, MUSICBRAINZ_RELEASETRACKID, MUSICBRAINZ_WORKID,
#   MUSICBRAINZ_RELEASEGROUPID
# 実MPDはタグ名の認識(tag_name_parse系)とタグに実際の値があるかどうかを別々に
# 扱うため、対応データを持たないタグでも `find`/`search`/`list`/フィルタ式で
# 使用可能で、単に0件を返す(ACKにはならない)。対して本実装は
# `_LIST_MAPPING`/`_SEARCH_MAPPING`にキーが無いタグ名を渡されると即座に
# `ACK incorrect arguments`/`ACK Unknown tag type`/`ACK Unknown filter type`に
# なり、`list`/`sort`修飾子も同様に`ACK Unknown sort type`になる。実機
# (127.0.0.1:6601、mopidy-ytmusic backend)で実際に確認済み:
#   find mood "Chill"            -> ACK [2@0] {find} incorrect arguments
#   list mood                    -> ACK [2@0] {list} Unknown tag type: mood
#   find "(Mood == \"Chill\")"   -> ACK [2@0] {find} Unknown filter type: Mood
#
# rmpc視点での実害: rmpc-mpd/src/filter.rs の Tag::Custom(String) により
# Advanced Search で任意のタグ名を自由入力できる。mopidy-ytmusic backend は
# browse()で「Mood and Genre Playlists」を実際に公開しており(ytmoodgenre-
# patch.py既存)、ユーザーが自然に"Mood"というタグ名で検索を試みる導線がある。
# BACKLOG.mdをgrep -n -i "originaldate\|ensemble\|movementnumber\|composersort"
# で確認したが既出項目なし(未着手の新規ギャップ)。
#
# 注意(実装上の最重要点): mopidyのTrack/Album/Artistモデルにはこれらのタグ用
# フィールドがそもそも存在せず、mopidy core自体(mopidy/core/library.py の
# search()/get_distinct())が受け付けるqueryのフィールド名/get_distinct()の
# field引数を固定の既知集合(validation.SEARCH_FIELDS/DISTINCT_FIELDS)に
# 限定してハードバリデーションしている。そのため単純にこれらのタグ名を
# `_LIST_MAPPING`へ追加しqueryの値として`context.core.library.search()`/
# `get_distinct()`へそのまま渡すと、mopidy.exceptions.ValidationError
# (未捕捉、セッションが無応答のまま切断される。ACKにすらならず元のACKより
# 悪化する重大な回帰)が発生することを実機で確認した。
# 本パッチはこれらのタグを「タグ名としては認識するが、backendへは一切送らず
# 常に0件/空集合を返す」という実MPDの「対応データ無しタグ」相当の状態にする:
#   - find/search/count/findadd/searchadd/searchaddpl/searchplaylist:
#     既存の `(base "DIR")` 用ローカルpositives機構(mpdbasefilter-patch.py)
#     を流用し、query dict(backendへ丸投げされる)には一切書き込まず
#     ローカルpositives/negativesのみに積む。`_mpd_negative_field_values()`/
#     `_pf_field_values()`は未知フィールドに対し既に空リストを返す
#     フォールバックを持つため、positive条件は常に不成立(0件)、negative
#     条件は常に無効(対象曲を除外しない)という実MPD相当の挙動になる。
#   - list/count group TAG: `_mpd_list_grouped()`/`_mpd_count_grouped()`が
#     グループ化対象/列挙対象のタグとしてこれらを渡された場合、
#     `context.core.library.get_distinct()`を一切呼ばず即座に空を返す
#     (対応データが無いので列挙結果も常に空という実MPD相当の結果)。
tt = "mopidy_mpd/protocol/tagtype_list.py"
s = open(tt).read()

MARKER = "MUSICBRAINZ_RELEASETRACKID"
if MARKER in s:
    print("tagtype_list.py already patched, skip")
else:
    old_tail = '''    "MUSICBRAINZ_TRACKID",
    "X-AlbumUri",
}
'''
    assert s.count(old_tail) == 1, f"tagtype_list.py anchor count={s.count(old_tail)}"
    new_tail = '''    "MUSICBRAINZ_TRACKID",
    "X-AlbumUri",
    "AlbumSort",
    "TitleSort",
    "Mood",
    "OriginalDate",
    "ComposerSort",
    "Conductor",
    "Work",
    "Movement",
    "MovementNumber",
    "ShowMovement",
    "Ensemble",
    "Location",
    "Grouping",
    "DiscSubtitle",
    "Label",
    "MUSICBRAINZ_RELEASETRACKID",
    "MUSICBRAINZ_WORKID",
    "MUSICBRAINZ_RELEASEGROUPID",
}
'''
    s = s.replace(old_tail, new_tail, 1)
    open(tt, "w").write(s)
    print("patched tagtype_list.py: 実MPD(Names.cxx)準拠の未登録タグ名18種をTAGTYPE_LISTへ追加")

mp = "mopidy_mpd/protocol/music_db.py"
m = open(mp).read()

MARKER2 = "_PHANTOM_TAG_FIELDS"
if MARKER2 in m:
    print("music_db.py already patched for extra tag names, skip")
else:
    # --- 1. _LIST_MAPPING / _LIST_NAME_MAPPING: タグ名の認識と表示名 ---
    old_list_mapping = '''_LIST_MAPPING = {
    "album": "album",
    "albumartist": "albumartist",
    "artist": "artist",
    "comment": "comment",
    "composer": "composer",
    "date": "date",
    "disc": "disc_no",
    "file": "uri",
    "filename": "uri",
    "genre": "genre",
    "musicbrainz_albumid": "musicbrainz_albumid",
    "musicbrainz_artistid": "musicbrainz_artistid",
    "musicbrainz_trackid": "musicbrainz_trackid",
    "performer": "performer",
    "title": "track_name",
    "track": "track_no",
}
'''
    assert m.count(old_list_mapping) == 1, f"_LIST_MAPPING anchor count={m.count(old_list_mapping)}"
    new_list_mapping = '''_LIST_MAPPING = {
    "album": "album",
    "albumartist": "albumartist",
    "artist": "artist",
    "comment": "comment",
    "composer": "composer",
    "date": "date",
    "disc": "disc_no",
    "file": "uri",
    "filename": "uri",
    "genre": "genre",
    "musicbrainz_albumid": "musicbrainz_albumid",
    "musicbrainz_artistid": "musicbrainz_artistid",
    "musicbrainz_trackid": "musicbrainz_trackid",
    "performer": "performer",
    "title": "track_name",
    "track": "track_no",
    # 実MPD(Names.cxx)には存在するがmopidyのTrack/Album/Artistモデルには
    # 対応フィールドが無いタグ群。恒等マッピングでタグ名として認識だけ
    # させ、backendへは送らない(_PHANTOM_TAG_FIELDS、下記参照)。
    "albumsort": "albumsort",
    "titlesort": "titlesort",
    "mood": "mood",
    "originaldate": "originaldate",
    "composersort": "composersort",
    "conductor": "conductor",
    "work": "work",
    "movement": "movement",
    "movementnumber": "movementnumber",
    "showmovement": "showmovement",
    "ensemble": "ensemble",
    "location": "location",
    "grouping": "grouping",
    "discsubtitle": "discsubtitle",
    "label": "label",
    "musicbrainz_releasetrackid": "musicbrainz_releasetrackid",
    "musicbrainz_workid": "musicbrainz_workid",
    "musicbrainz_releasegroupid": "musicbrainz_releasegroupid",
}

# _LIST_MAPPING/_SEARCH_MAPPING経由で認識はされるが、mopidy core自体
# (mopidy/core/library.py search()/get_distinct())が固定の既知フィールド
# 集合でqueryを検証するため、これらのフィールド名をbackendへ渡すと
# mopidy.exceptions.ValidationError(未捕捉)でセッションが落ちてしまう。
# find/search/count等の呼び出し元はこの集合に該当するフィールドをquery
# dictへは書き込まず、ローカルのpositives/negatives判定のみで処理する
# (常に0件/対象外という実MPDの「対応データ無しタグ」相当の挙動)。
_PHANTOM_TAG_FIELDS = frozenset({
    "albumsort", "titlesort", "mood", "originaldate", "composersort",
    "conductor", "work", "movement", "movementnumber", "showmovement",
    "ensemble", "location", "grouping", "discsubtitle", "label",
    "musicbrainz_releasetrackid", "musicbrainz_workid",
    "musicbrainz_releasegroupid",
})
'''
    m = m.replace(old_list_mapping, new_list_mapping, 1)

    old_name_mapping = '''_LIST_NAME_MAPPING = {
    "album": "Album",
    "albumartist": "AlbumArtist",
    "artist": "Artist",
    "comment": "Comment",
    "composer": "Composer",
    "date": "Date",
    "disc_no": "Disc",
    "genre": "Genre",
    "performer": "Performer",
    "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID",
    "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_trackid": "MUSICBRAINZ_TRACKID",
    "track_name": "Title",
    "track_no": "Track",
    "uri": "file",
}
'''
    assert m.count(old_name_mapping) == 1, f"_LIST_NAME_MAPPING anchor count={m.count(old_name_mapping)}"
    new_name_mapping = '''_LIST_NAME_MAPPING = {
    "album": "Album",
    "albumartist": "AlbumArtist",
    "artist": "Artist",
    "comment": "Comment",
    "composer": "Composer",
    "date": "Date",
    "disc_no": "Disc",
    "genre": "Genre",
    "performer": "Performer",
    "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID",
    "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_trackid": "MUSICBRAINZ_TRACKID",
    "track_name": "Title",
    "track_no": "Track",
    "uri": "file",
    "albumsort": "AlbumSort",
    "titlesort": "TitleSort",
    "mood": "Mood",
    "originaldate": "OriginalDate",
    "composersort": "ComposerSort",
    "conductor": "Conductor",
    "work": "Work",
    "movement": "Movement",
    "movementnumber": "MovementNumber",
    "showmovement": "ShowMovement",
    "ensemble": "Ensemble",
    "location": "Location",
    "grouping": "Grouping",
    "discsubtitle": "DiscSubtitle",
    "label": "Label",
    "musicbrainz_releasetrackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_workid": "MUSICBRAINZ_WORKID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
}
'''
    m = m.replace(old_name_mapping, new_name_mapping, 1)

    # --- 2. 旧式引数列パーサ: phantomタグはqueryへ書かずpositivesのみへ ---
    old_legacy_write = '''        value = parameters.pop(0)
        if value.strip():
            query.setdefault(field, []).append(value)
    _mpdfindmultitag_positives = [
'''
    assert m.count(old_legacy_write) == 1, f"legacy_write anchor count={m.count(old_legacy_write)}"
    new_legacy_write = '''        value = parameters.pop(0)
        if value.strip():
            if field in _PHANTOM_TAG_FIELDS:
                # backendへは送らずbase同様ローカルpositiveとしてのみ扱う
                # (常に0件、上記_PHANTOM_TAG_FIELDS参照)。
                _mpdbasefilter_positives.append((field, "exact", value))
            else:
                query.setdefault(field, []).append(value)
    _mpdfindmultitag_positives = [
'''
    m = m.replace(old_legacy_write, new_legacy_write, 1)

    # --- 3. 新式フィルタ式パーサ: 同様にqueryへ書かずpositives/negativesのみへ ---
    old_expr_write = '''            if _op_is_neg_token != _neg_wrap:
                negatives.append((field, _kind, value))
            else:
                query.setdefault(field, []).append(value)
                positives.append((field, _kind, value))
'''
    assert m.count(old_expr_write) == 1, f"expr_write anchor count={m.count(old_expr_write)}"
    new_expr_write = '''            if _op_is_neg_token != _neg_wrap:
                negatives.append((field, _kind, value))
            else:
                if field not in _PHANTOM_TAG_FIELDS:
                    query.setdefault(field, []).append(value)
                positives.append((field, _kind, value))
'''
    m = m.replace(old_expr_write, new_expr_write, 1)

    old_require_positive = '''    if require_positive and not query and not has_base_positive:
        raise exceptions.MpdArgError("incorrect arguments")
'''
    assert m.count(old_require_positive) == 1, f"require_positive anchor count={m.count(old_require_positive)}"
    new_require_positive = '''    if require_positive and not query and not has_base_positive and not positives:
        raise exceptions.MpdArgError("incorrect arguments")
'''
    m = m.replace(old_require_positive, new_require_positive, 1)

    # --- 4. list/count の group化列挙: get_distinct()にphantomを渡さない ---
    old_list_grouped = '''def _mpd_list_grouped(context, field, name, query, groups, window=None):
    # window (musicpd.org 仕様) は実 MPD の PrintUniqueTags 同様、最外周の階層
    # (group 指定時はその一番外側の group、無指定時は TYPE 自体) にのみ適用し、
    # 内側の階層 (再帰呼び出し) には渡さず常に全件を返す。
    if not groups:
        values = sorted(v for v in context.core.library.get_distinct(field, query).get() if v)
        if window is not None:
            values = values[window]
        return [(name, v) for v in values]
    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = sorted(v for v in context.core.library.get_distinct(gfield, query).get() if v)
'''
    assert m.count(old_list_grouped) == 1, f"list_grouped anchor count={m.count(old_list_grouped)}"
    new_list_grouped = '''def _mpd_list_grouped(context, field, name, query, groups, window=None):
    # window (musicpd.org 仕様) は実 MPD の PrintUniqueTags 同様、最外周の階層
    # (group 指定時はその一番外側の group、無指定時は TYPE 自体) にのみ適用し、
    # 内側の階層 (再帰呼び出し) には渡さず常に全件を返す。
    if not groups:
        if field in _PHANTOM_TAG_FIELDS:
            # mopidy core の get_distinct() は固定フィールド集合しか受け付けず
            # 未知フィールドは ValidationError で落ちるため呼ばない
            # (対応データ無しタグなので実MPD相当の結果は常に空)。
            return []
        values = sorted(v for v in context.core.library.get_distinct(field, query).get() if v)
        if window is not None:
            values = values[window]
        return [(name, v) for v in values]
    gfield = groups[0]
    if gfield in _PHANTOM_TAG_FIELDS:
        return []
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = sorted(v for v in context.core.library.get_distinct(gfield, query).get() if v)
'''
    m = m.replace(old_list_grouped, new_list_grouped, 1)

    old_count_grouped = '''    gfield = groups[0]
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
'''
    assert m.count(old_count_grouped) == 1, f"count_grouped anchor count={m.count(old_count_grouped)}"
    new_count_grouped = '''    gfield = groups[0]
    if gfield in _PHANTOM_TAG_FIELDS:
        return []
    gname = _LIST_NAME_MAPPING.get(gfield, gfield)
    gvalues = context.core.library.get_distinct(gfield, query).get()
    rows = []
    for gvalue in sorted(v for v in gvalues if v):
'''
    m = m.replace(old_count_grouped, new_count_grouped, 1)

    open(mp, "w").write(m)
    print(
        "patched music_db.py: 実MPD準拠の未登録タグ名18種をタグ名としては認識、"
        "backendへは送らず常に空/0件を返すよう追加 (_PHANTOM_TAG_FIELDS)"
    )
