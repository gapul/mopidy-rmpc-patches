# `prio`/`prioid`(mpdprio-patch.py)、`rangeid`(mpdrangeid-patch.py)、
# `addtagid`/`cleartagid`(mpdaddtagid-patch.py)が、成功時に idle "playlist" イベントを
# 一切発火しない不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# mpdcrossfadeidle-patch.py(crossfade/mixrampdb/mixrampdelayのidle options未発火)・
# mpdstickeridle-patch.py(sticker set/deleteのidle sticker未発火)と同種のギャップとして
# current_playlist.py を再調査し新規発見・追加した項目。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/QueueCommands.cxx handle_prio/handle_prioid/
# handle_rangeid、src/command/TagCommands.cxx handle_addtagid/handle_cleartagid) を実際に
# clone してソース確認したところ、いずれも成功パスの末尾で queue の version を上げる
# (playlist::SetPriority/SetPriorityRange/SetSongRangeSong/AddSongIdTag/ClearSongIdTag
# が内部で queue.ModifyAtOrder / IncrementVersion 相当を呼ぶ) ため、MPD の idle 通知は
# version 変更を検知して IDLE_PLAYLIST を発火する。
# ところが mopidy_mpd 3.3.0 (+ 上記4パッチ) の実装は `context.core.tracklist` を
# 一切経由せず、translator.py のモジュールレベル揮発性ストア (優先度/range/タグ) を
# 直接書き換えるだけなので、actor.py の `MpdFrontend.on_event` が拾う mopidy core 由来の
# `tracklist_changed` イベントには一切乗らず、`idle playlist` で待機中の他クライアントは
# 起こされない。
#
# 実害: rmpc は `playlistinfo`/`plchangesposid` で Prio/Range/(タグ) を表示する導線を
# 持つが、別クライアント(または同一クライアントの別接続)が prio/prioid/rangeid/
# addtagid/cleartagid を実行しても、`idle playlist` 待機中の rmpc は起こされず、次に
# 別の理由 (add/delete/move等) で playlist イベントが発火するまで表示が古いまま
# 固定される、というサイレントな不整合が生じる。クラッシュやセッション切断は起きないが
# 実MPD仕様違反かつUI表示に実害がある。
#
# 実装: mpdcrossfadeidle-patch.py の `_mpdcrossfadeidle_notify()`・
# mpdstickeridle-patch.py の `_mpdsticker_notify()` と全く同じ機構
# (`mopidy.listener.send(session.MpdSession, "playlist")`、pykka の `.tell()` 経由で
# スレッドセーフに全セッションへブロードキャスト) を current_playlist.py 専用の
# `_mpdqueueidle_notify()` として新設し、5コマンドそれぞれの成功パス末尾で呼び出す。
# `playlist` は status.py の SUBSYSTEMS に既に登録済み (bare `idle` でも従来から拾う
# 対象) のため、status.py 側の変更は不要。

p = "mopidy_mpd/protocol/current_playlist.py"
s = open(p).read()

MARKER = "_mpdqueueidle_notify"
if MARKER in s:
    print("current_playlist.py already patched, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = old_import + (
        "\n"
        "def _mpdqueueidle_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdcrossfadeidle-patch.py の _mpdcrossfadeidle_notify と全く同じ理由・機構)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "playlist")\n'
    )
    s = s.replace(old_import, new_import, 1)

    old_prio_tail = (
        "        tlids.update(tlid for tlid, _track in tl_tracks)\n"
        "    for tlid in tlids:\n"
        "        translator.set_priority(tlid, priority)\n"
    )
    assert s.count(old_prio_tail) == 1, f"old_prio_tail count={s.count(old_prio_tail)}"
    new_prio_tail = old_prio_tail + "    _mpdqueueidle_notify()\n"
    s = s.replace(old_prio_tail, new_prio_tail, 1)

    old_prioid_tail = (
        '            raise exceptions.MpdNoExistError("No such song")\n'
        "    for tlid in tlids:\n"
        "        translator.set_priority(tlid, priority)\n"
    )
    assert (
        s.count(old_prioid_tail) == 1
    ), f"old_prioid_tail count={s.count(old_prioid_tail)}"
    new_prioid_tail = old_prioid_tail + "    _mpdqueueidle_notify()\n"
    s = s.replace(old_prioid_tail, new_prioid_tail, 1)

    old_rangeid_tail = "    translator.set_range(tlid, start_ms, end_ms)\n"
    assert (
        s.count(old_rangeid_tail) == 1
    ), f"old_rangeid_tail count={s.count(old_rangeid_tail)}"
    new_rangeid_tail = old_rangeid_tail + "    _mpdqueueidle_notify()\n"
    s = s.replace(old_rangeid_tail, new_rangeid_tail, 1)

    old_addtagid_tail = "    translator.add_song_tag(tlid, tag_type, value)\n"
    assert (
        s.count(old_addtagid_tail) == 1
    ), f"old_addtagid_tail count={s.count(old_addtagid_tail)}"
    new_addtagid_tail = old_addtagid_tail + "    _mpdqueueidle_notify()\n"
    s = s.replace(old_addtagid_tail, new_addtagid_tail, 1)

    old_cleartagid_tail = "    translator.clear_song_tag(tlid, tag_type)\n"
    assert (
        s.count(old_cleartagid_tail) == 1
    ), f"old_cleartagid_tail count={s.count(old_cleartagid_tail)}"
    new_cleartagid_tail = old_cleartagid_tail + "    _mpdqueueidle_notify()\n"
    s = s.replace(old_cleartagid_tail, new_cleartagid_tail, 1)

    open(p, "w").write(s)
    print(
        "patched current_playlist.py: prio/prioid/rangeid/addtagid/cleartagid で"
        " idle 'playlist' 通知を発火"
    )
