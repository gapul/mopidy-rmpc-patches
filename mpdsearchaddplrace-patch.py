# mopidy_mpd/protocol/music_db.py の searchaddpl {NAME} {FILTER} ... は、
# 「context.core.playlists.lookup() でストアドプレイリストの現在の内容を読む →
# ローカルで検索結果とマージ → context.core.playlists.save()(または存在しなければ
# create())で書き戻す」という、mpdplaylisteditrace-patch.py/mpdplaylistrmrace-patch.py
# が stored_playlists.py の playlistadd/playlistclear/playlistdelete/playlistmove/
# rename/save/rm に対して _stored_playlist_edit_lock で直列化した read-modify-write
# と全く同型の複合操作を行っているにもかかわらず、music_db.py 自体には
# threading も Lock も一切無く、この保護の対象外のまま取り残されていた。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが再調査して新規発見した項目
# (mpdplaylisteditrace-patch.py の対象列挙は stored_playlists.py 内の6コマンドに
# 限定されており、別ファイル music_db.py の兄弟コマンドである searchaddpl は
# 元々スコープ外だった)。
#
# 実害: 接続Aが `playlistadd "P" trackA`、接続Bがほぼ同時に
# `searchaddpl "P" any "query"` を送ると、Aは _stored_playlist_edit_lock を
# 取った状態で読み取り→save()するが、Bはロックを一切取らずに独立して
# 「Pの内容を読む→検索結果を加えてsave()」してしまうため、Aのsave()とBのsave()の
# 間にBがロック無しで読み取りを行った場合、後勝ちのsave()が先行クライアントの
# 追加分を踏み潰す (lost update)。mpdplaylisteditrace-patch.py が既に詳述した通り、
# mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.save() は「渡された
# playlist.tracks を目的状態とし、save() 呼び出し時点でYTM側から改めて取得した
# 実際の状態との Counter 差分だけを add/remove API へ送る」設計のため、Bが古い
# 状態を土台に save() すると、Aが追加した曲は newCounts に含まれず removeCounts に
# 回り **実際にYouTube Music側から削除される**。両方とも OK が返り、ACKエラーは
# 一切出ないサイレントなデータ消失。searchaddpl は read と write の間に
# `context.core.library.search()` という時間のかかるネットワークI/Oを挟むため、
# playlistadd 同士のレースよりもさらにレース窓が長く発生しやすい。
#
# 修正: mpdplaylisteditrace-patch.py/mpdplaylistrmrace-patch.py が
# stored_playlists.py に導入した _stored_playlist_edit_lock を、
# translator.py にモジュールレベルの共有オブジェクトとして引き上げ
# (mpdcrossfade-patch.py 等と同じ「protocol/*.py 間で共有する揮発性状態は
# translator.py に置く」流儀)、stored_playlists.py 側の定義をこの共有オブジェクトへの
# 参照に置き換えた上で、music_db.py の searchaddpl の
# 「lookup()→search()→save()/create()」区間も同じロックで直列化する。
# stored_playlists.py 側の既存7箇所の `with _stored_playlist_edit_lock:` は
# ローカル変数名を変えていないため無修正で動作し、実体が同一のLockオブジェクトを
# 指すようになることで searchaddpl とも相互排他になる。

import re

# 1) translator.py: 全ファイル間で共有する _stored_playlist_edit_lock を新設
tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_stored_playlist_edit_lock"
if MARKER_T in t:
    print("mpdsearchaddplrace already applied to translator.py, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# stored_playlists.py (playlistadd/playlistclear/playlistdelete/\n"
        "# playlistmove/rename/save/rm) と music_db.py (searchaddpl) は、いずれも\n"
        "# 全クライアント接続間で共有される同一のストアドプレイリストに対し\n"
        "# 「読み取り→加工→save()」というread-modify-writeを行うため、両ファイルで\n"
        "# 共有する1個のLockで直列化する (mpdplaylisteditrace-patch.py/\n"
        "# mpdplaylistrmrace-patch.py が導入したロックを、別ファイルの兄弟コマンド\n"
        "# searchaddpl とも共有できるようtranslator.pyへ引き上げ、\n"
        "# mpdsearchaddplrace-patch.py)。\n"
        "_stored_playlist_edit_lock = threading.Lock()\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: _stored_playlist_edit_lock を共有オブジェクトとして追加")

# 2) stored_playlists.py: ローカル定義を translator.py の共有オブジェクトへの参照に置換
sp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(sp).read()

MARKER_S = "_stored_playlist_edit_lock = translator._stored_playlist_edit_lock"
if MARKER_S in s:
    print("mpdsearchaddplrace already applied to stored_playlists.py, skip")
else:
    assert "_stored_playlist_edit_lock = threading.Lock()\n" in s, (
        "mpdplaylisteditrace-patch.py must run before mpdsearchaddplrace-patch.py "
        "(missing local _stored_playlist_edit_lock definition in stored_playlists.py)"
    )
    old_def = "_stored_playlist_edit_lock = threading.Lock()\n"
    assert s.count(old_def) == 1, f"old_def count={s.count(old_def)}"
    new_def = (
        "_stored_playlist_edit_lock = translator._stored_playlist_edit_lock"
        "  # music_db.pyのsearchaddplと共有 (mpdsearchaddplrace-patch.py)\n"
    )
    s = s.replace(old_def, new_def, 1)
    open(sp, "w").write(s)
    print(
        "patched stored_playlists.py: _stored_playlist_edit_lock を"
        "translator.pyの共有オブジェクトへの参照に置換"
    )

# 3) music_db.py: searchaddpl のlookup()~save()/create()区間をロックで保護
mp = "mopidy_mpd/protocol/music_db.py"
m = open(mp).read()

MARKER_M = "with _stored_playlist_edit_lock:"
if MARKER_M in m:
    print("mpdsearchaddplrace already applied to music_db.py, skip")
else:
    # 3a) 共有ロックへのモジュールレベル参照を追加
    old_import = (
        "from mopidy_mpd import exceptions, protocol, translator\n"
        "\n"
        "_LIST_MAPPING = {\n"
    )
    assert m.count(old_import) == 1, f"old_import count={m.count(old_import)}"
    new_import = (
        "from mopidy_mpd import exceptions, protocol, translator\n"
        "\n"
        "# stored_playlists.pyの編集系コマンドと共有するLock\n"
        "# (mpdsearchaddplrace-patch.py)。searchaddplもストアドプレイリストへの\n"
        "# read-modify-writeを行うため、直列化に参加する。\n"
        "_stored_playlist_edit_lock = translator._stored_playlist_edit_lock\n"
        "\n"
        "_LIST_MAPPING = {\n"
    )
    m = m.replace(old_import, new_import, 1)

    # 3b) searchaddpl(): lookup()~save()/create()区間をロックで保護
    old_body = (
        "    uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "    playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "    old_tracks = list(playlist.tracks) if playlist else []\n"
        "    if _position is not None and _position > len(old_tracks):\n"
        '        raise exceptions.MpdArgError("Bad position")\n'
        "\n"
        "    try:\n"
        "        query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "    except ValueError:\n"
        "        return\n"
        "    _negatives = _mpd_pop_negatives(query)\n"
        "    _positives = _mpd_pop_positives(query)\n"
        '    _strip_diacritics = "strip_diacritics" in getattr(\n'
        '        context.session, "string_normalization", ()\n'
        "    )\n"
        "    results = context.core.library.search(query).get()\n"
        "    _new_tracks = _mpd_filter_negatives(\n"
        "        _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics\n"
        "    )\n"
        "    _new_tracks = _mpd_filter_positives(\n"
        "        _new_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics\n"
        "    )\n"
        "    if _sort_field:\n"
        "        _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)\n"
        "    if _window is not None:\n"
        "        _new_tracks = _new_tracks[_window]\n"
        "\n"
        "    if _position is None:\n"
        "        tracks = old_tracks + _new_tracks\n"
        "    else:\n"
        "        tracks = old_tracks[:_position] + _new_tracks + old_tracks[_position:]\n"
        "\n"
        "    if not playlist:\n"
        "        playlist = context.core.playlists.create(playlist_name).get()\n"
        "        if playlist is None:\n"
        '            default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
        "            raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
        "    playlist = playlist.replace(tracks=tracks)\n"
        "    saved_playlist = context.core.playlists.save(playlist).get()\n"
        "    if saved_playlist is None:\n"
        "        raise exceptions.MpdFailedToSavePlaylist(\n"
        "            urllib.parse.urlparse(playlist.uri).scheme\n"
        "        )\n"
    )
    assert m.count(old_body) == 1, f"old_body count={m.count(old_body)}"
    new_body = (
        "    with _stored_playlist_edit_lock:\n"
        "        uri = context.lookup_playlist_uri_from_name(playlist_name)\n"
        "        playlist = uri is not None and context.core.playlists.lookup(uri).get()\n"
        "        old_tracks = list(playlist.tracks) if playlist else []\n"
        "        if _position is not None and _position > len(old_tracks):\n"
        '            raise exceptions.MpdArgError("Bad position")\n'
        "\n"
        "        try:\n"
        "            query = _query_from_mpd_search_parameters(parameters, _SEARCH_MAPPING)\n"
        "        except ValueError:\n"
        "            return\n"
        "        _negatives = _mpd_pop_negatives(query)\n"
        "        _positives = _mpd_pop_positives(query)\n"
        '        _strip_diacritics = "strip_diacritics" in getattr(\n'
        '            context.session, "string_normalization", ()\n'
        "        )\n"
        "        results = context.core.library.search(query).get()\n"
        "        _new_tracks = _mpd_filter_negatives(\n"
        "            _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics\n"
        "        )\n"
        "        _new_tracks = _mpd_filter_positives(\n"
        "            _new_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics\n"
        "        )\n"
        "        if _sort_field:\n"
        "            _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)\n"
        "        if _window is not None:\n"
        "            _new_tracks = _new_tracks[_window]\n"
        "\n"
        "        if _position is None:\n"
        "            tracks = old_tracks + _new_tracks\n"
        "        else:\n"
        "            tracks = old_tracks[:_position] + _new_tracks + old_tracks[_position:]\n"
        "\n"
        "        if not playlist:\n"
        "            playlist = context.core.playlists.create(playlist_name).get()\n"
        "            if playlist is None:\n"
        '                default_scheme = context.dispatcher.config["mpd"]["default_playlist_scheme"]\n'
        "                raise exceptions.MpdFailedToSavePlaylist(default_scheme)\n"
        "        playlist = playlist.replace(tracks=tracks)\n"
        "        saved_playlist = context.core.playlists.save(playlist).get()\n"
        "        if saved_playlist is None:\n"
        "            raise exceptions.MpdFailedToSavePlaylist(\n"
        "                urllib.parse.urlparse(playlist.uri).scheme\n"
        "            )\n"
    )
    m = m.replace(old_body, new_body, 1)

    open(mp, "w").write(m)
    print(
        "patched music_db.py: searchaddplのlookup()~search()~save()/create()区間を"
        "stored_playlists.pyと共有する_stored_playlist_edit_lockで直列化し、"
        "playlistadd等の他の編集系コマンドとのlost update"
        "(YTMusicバックエンドでは先行クライアントの追加分が実際にYouTube Music側から"
        "削除されるサイレントなデータ消失)を解消"
    )
