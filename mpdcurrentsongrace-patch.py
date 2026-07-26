# mopidy_mpd/protocol/status.py の `currentsong` と current_playlist.py の
# `playlistid {SONGID}` / `plchanges {VERSION}` (version一致時の分岐) に共通して
# 残っていた TOCTOU レース。自走エージェントが TODO/既知の残課題を全項目消化済みの
# ため mopidy_mpd のコード品質を再調査して発見した項目 (prio/moveid/swapid の
# TOCTOUレース群と同根だが、書き込み系コマンドの修正時にはスコープ外だった読み取り系
# コマンドに同型の欠陥が残っていた)。
#
# 3箇所とも共通の構造上の欠陥を持つ:
#   1. `currentsong`: `tl_track = core.playback.get_current_tl_track().get()` (呼び出し1)
#      の後、別の core 呼び出しとして `position = core.tracklist.index(tl_track).get()`
#      (呼び出し2) を行う。
#   2. `playlistid {SONGID}`: `tl_tracks = core.tracklist.filter({"tlid": [tlid]}).get()`
#      (呼び出し1) の後、`position = core.tracklist.index(tl_tracks[0]).get()` (呼び出し2)。
#   3. `plchanges`: version一致 (メタデータ更新のみ) 分岐で `currentsong` と全く同じ
#      `get_current_tl_track()` → `index(tl_track)` の2段階。
#
# `mopidy/core/tracklist.py` の `index(tl_track)` は該当曲がもはやキューに存在しなければ
# `ValueError` を握り潰して `None` を返す実装 (gh api で実装確認済み)。呼び出し1と呼び出し2
# は別々の pykka actor 往復のため、間隙で別クライアントが `delete`/`clear` 等により該当曲を
# キューから外すと `position=None` になる。`mopidy_mpd/translator.py` の
# `track_to_mpd_format()` は `if position is not None and tlid is not None:` の内側でしか
# `Pos`/`Id`/`Range`/`Prio`/`Added` を出力しないため、この場合これらのフィールドが
# 例外もACKも無くサイレントに応答から丸ごと欠落する。
#
# rmpc (mierak/rmpc) は `get_status_and_current_song()` で `status`+`currentsong` を
# command_list で毎回セットで送り (player idle wakeup時=最頻出経路)、返ってきた
# `Song.id` を `event_loop.rs` の `is_new_song = new_song_id.is_some() && new_song_id !=
# current_song_id` で「曲が変わったか」の判定に使う。`playlistid`/`plchanges` も同種の
# クライアントの曲同定に使われる。Idの欠落によりこの判定がサイレントに誤る実害がある。
#
# 修正方針: `currentsong`/`plchanges` は読み取り専用コマンドで ACK による失敗の余地が
# 無いため (musicpd.org 仕様上、こういうケースでのエラー応答は定義されていない)、
# mpdswapstalepos-patch.py 等が書き込み系コマンドで確立した `tracklist.version` による
# 楽観的排他制御を「割り込みを検知したら取り直す (bounded retry)」形で転用する:
# 呼び出し前後で version が不変なら割り込みが無かったことを意味し、得られた
# position は正しい。割り込みがあれば最大 `_TRACKLIST_SNAPSHOT_RETRIES` 回まで
# 取り直し、それでも収束しない極端なケースでは最後に得られた値をそのまま返す
# (現状の「常にサイレントに欠落」より確実に改善するため、収束しなくても悪化はしない)。
# `playlistid {SONGID}` はより単純に、`get_tl_tracks()` 1回のスナップショットに対し
# ローカルで位置を求めることで2回の core 呼び出し自体を1回へ一本化し、レースそのものを
# 解消した (`playlistinfo`/`plchangesposid` が既に同じ「1回のスナップショット+ローカル
# enumerate」の流儀を使っており、これに揃えた形)。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

STATUS_MARKER = "_TRACKLIST_SNAPSHOT_RETRIES"
if STATUS_MARKER in s:
    print("currentsong race already patched, skip")
else:
    old_import = (
        "import pykka\n"
        "\n"
        "from mopidy.core import PlaybackState\n"
        "from mopidy_mpd import exceptions, protocol, translator\n"
    )
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = old_import + (
        "\n"
        "# currentsong() が get_current_tl_track()/tracklist.index() の間の割り込みを\n"
        "# 検知して取り直す際の上限回数 (通常は初回で収束する)。\n"
        "_TRACKLIST_SNAPSHOT_RETRIES = 5\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_currentsong = (
        "    tl_track = context.core.playback.get_current_tl_track().get()\n"
        "    stream_title = context.core.playback.get_stream_title().get()\n"
        "    if tl_track is not None:\n"
        "        position = context.core.tracklist.index(tl_track).get()\n"
        "        return translator.track_to_mpd_format(\n"
        "            tl_track,\n"
        "            position=position,\n"
        "            stream_title=stream_title,\n"
        "            tagtypes=context.session.tagtypes,\n"
        "        )\n"
    )
    assert s.count(old_currentsong) == 1, f"old_currentsong count={s.count(old_currentsong)}"
    new_currentsong = (
        "    stream_title = context.core.playback.get_stream_title().get()\n"
        "    # get_current_tl_track()とtracklist.index(tl_track)は別々のcore呼び出しで、\n"
        "    # 間に他クライアントのdelete/clear等が割り込むとindex()がValueErrorを握り潰し\n"
        "    # Noneを返し、Pos/Id等がサイレントに欠落する(prio/moveid/swapidのTOCTOUレース\n"
        "    # と同根)。versionが前後で不変なことを確認し、割り込みがあれば取り直す。\n"
        "    tl_track = None\n"
        "    position = None\n"
        "    for _ in range(_TRACKLIST_SNAPSHOT_RETRIES):\n"
        "        version = context.core.tracklist.get_version().get()\n"
        "        tl_track = context.core.playback.get_current_tl_track().get()\n"
        "        if tl_track is None:\n"
        "            return\n"
        "        position = context.core.tracklist.index(tl_track).get()\n"
        "        if context.core.tracklist.get_version().get() == version:\n"
        "            break\n"
        "    return translator.track_to_mpd_format(\n"
        "        tl_track,\n"
        "        position=position,\n"
        "        stream_title=stream_title,\n"
        "        tagtypes=context.session.tagtypes,\n"
        "    )\n"
    )
    s = s.replace(old_currentsong, new_currentsong, 1)

    open(sp, "w").write(s)
    print(
        "patched status.py: currentsongのget_current_tl_track()/tracklist.index()間の"
        "TOCTOUレースでPos/Idがサイレントに欠落する不具合を修正 (tracklist.versionの"
        "楽観的排他制御でbounded retry)"
    )

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

CP_MARKER = "_TRACKLIST_SNAPSHOT_RETRIES"
if CP_MARKER in s:
    print("playlistid/plchanges race already patched, skip")
else:
    old_import = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_pop_negatives,\n"
        "    _mpd_pop_positives,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = old_import + (
        "\n"
        "# plchanges() が version一致(メタデータ更新)分岐で割り込みを検知して取り直す際の\n"
        "# 上限回数 (通常は初回で収束する)。\n"
        "_TRACKLIST_SNAPSHOT_RETRIES = 5\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_playlistid = (
        "    if tlid is not None:\n"
        '        tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "        if not tl_tracks:\n"
        '            raise exceptions.MpdNoExistError("No such song")\n'
        "        position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "        return translator.track_to_mpd_format(\n"
        "            tl_tracks[0], context.session.tagtypes, position=position\n"
        "        )\n"
        "    else:\n"
        "        return translator.tracks_to_mpd_format(\n"
        "            context.core.tracklist.get_tl_tracks().get(),\n"
        "            context.session.tagtypes,\n"
        "        )\n"
    )
    assert s.count(old_playlistid) == 1, f"old_playlistid count={s.count(old_playlistid)}"
    new_playlistid = (
        "    if tlid is not None:\n"
        "        # filter({\"tlid\": [tlid]})とindex(tl_tracks[0])は別々のcore呼び出しで、\n"
        "        # 間に他クライアントが該当曲をdeleteするとindex()がNoneを返しPos/Idが\n"
        "        # サイレントに欠落する(currentsong/plchangesと同根のTOCTOU)。\n"
        "        # get_tl_tracks()1回のスナップショットに対しローカルで位置を求めることで\n"
        "        # 単一core呼び出しに一本化し、レースそのものを解消する。\n"
        "        for position, tl_track in enumerate(\n"
        "            context.core.tracklist.get_tl_tracks().get()\n"
        "        ):\n"
        "            if tl_track.tlid == tlid:\n"
        "                return translator.track_to_mpd_format(\n"
        "                    tl_track, context.session.tagtypes, position=position\n"
        "                )\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    else:\n"
        "        return translator.tracks_to_mpd_format(\n"
        "            context.core.tracklist.get_tl_tracks().get(),\n"
        "            context.session.tagtypes,\n"
        "        )\n"
    )
    s = s.replace(old_playlistid, new_playlistid, 1)

    old_plchanges = (
        "    # XXX Naive implementation that returns all tracks as changed\n"
        "    tracklist_version = context.core.tracklist.get_version().get()\n"
        "    if version < tracklist_version:\n"
        "        return translator.tracks_to_mpd_format(\n"
        "            context.core.tracklist.get_tl_tracks().get(),\n"
        "            context.session.tagtypes,\n"
        "        )\n"
        "    elif version == tracklist_version:\n"
        "        # A version match could indicate this is just a metadata update, so\n"
        "        # check for a stream ref and let the client know about the change.\n"
        "        stream_title = context.core.playback.get_stream_title().get()\n"
        "        if stream_title is None:\n"
        "            return None\n"
        "\n"
        "        tl_track = context.core.playback.get_current_tl_track().get()\n"
        "        position = context.core.tracklist.index(tl_track).get()\n"
        "        return translator.track_to_mpd_format(\n"
        "            tl_track,\n"
        "            context.session.tagtypes,\n"
        "            position=position,\n"
        "            stream_title=stream_title,\n"
        "        )\n"
    )
    assert s.count(old_plchanges) == 1, f"old_plchanges count={s.count(old_plchanges)}"
    new_plchanges = (
        "    # XXX Naive implementation that returns all tracks as changed\n"
        "    # version一致(メタデータ更新のみ)分岐のget_current_tl_track()/tracklist.index()\n"
        "    # はcurrentsongと同じTOCTOUレースを持つ(別々のcore呼び出しの間に割り込まれると\n"
        "    # positionがNoneになりPos/Idがサイレントに欠落する)。versionが前後で不変な\n"
        "    # ことを確認し、割り込みがあれば取り直す。\n"
        "    tl_track = None\n"
        "    position = None\n"
        "    stream_title = None\n"
        "    for _ in range(_TRACKLIST_SNAPSHOT_RETRIES):\n"
        "        tracklist_version = context.core.tracklist.get_version().get()\n"
        "        if version < tracklist_version:\n"
        "            return translator.tracks_to_mpd_format(\n"
        "                context.core.tracklist.get_tl_tracks().get(),\n"
        "                context.session.tagtypes,\n"
        "            )\n"
        "        elif version == tracklist_version:\n"
        "            # A version match could indicate this is just a metadata update, so\n"
        "            # check for a stream ref and let the client know about the change.\n"
        "            stream_title = context.core.playback.get_stream_title().get()\n"
        "            if stream_title is None:\n"
        "                return None\n"
        "\n"
        "            tl_track = context.core.playback.get_current_tl_track().get()\n"
        "            position = context.core.tracklist.index(tl_track).get()\n"
        "            if context.core.tracklist.get_version().get() == tracklist_version:\n"
        "                return translator.track_to_mpd_format(\n"
        "                    tl_track,\n"
        "                    context.session.tagtypes,\n"
        "                    position=position,\n"
        "                    stream_title=stream_title,\n"
        "                )\n"
        "        else:\n"
        "            return\n"
        "    return translator.track_to_mpd_format(\n"
        "        tl_track,\n"
        "        context.session.tagtypes,\n"
        "        position=position,\n"
        "        stream_title=stream_title,\n"
        "    )\n"
    )
    s = s.replace(old_plchanges, new_plchanges, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: playlistid {SONGID}のfilter()+index()間、"
        "plchangesのversion一致分岐のget_current_tl_track()+index()間、それぞれの"
        "TOCTOUレースでPos/Idがサイレントに欠落する不具合を修正 (playlistidは単一"
        "core呼び出しへ一本化、plchangesはtracklist.versionの楽観的排他制御で"
        "bounded retry)"
    )
