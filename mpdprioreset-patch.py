# prio/prioid (mpdprio-patch.py) で設定した優先度が、実MPDでは曲の再生が
# 実際に始まった瞬間に0へリセットされる (src/queue/Playlist.cxx
# playlist::SongStarted(): "reset a song's priority when playback starts"、
# queue.SetPriority(pos, 0, -1, false) を呼ぶ。明示 play/playid 経由
# (PlaylistControl.cxx PlayOrder() → SongStarted()) と自然な曲送り経由
# (Playlist.cxx QueuedSongStarted() → SongStarted()) の両方から呼ばれる)
# のに対し、mopidy_mpdはこのリセットを一切行わずPrioが再生後も
# playlistinfo/playlistid に残り続ける不具合を修正。TODO全項目消化済みの
# ため自走エージェントが(general-purposeサブエージェントへの調査委任を
# 経て)新規発見。
#
# mopidy core は明示play/自然送りの両方で一律 "track_playback_started"
# イベントを発火する (mopidy/core/playback.py
# _trigger_track_playback_started()、tl_track=tl_track を伴う) ため、
# actor.py の on_event() に1箇所フックを追加するだけで実MPDの2経路を
# 両方カバーできる。優先度ストアの実体は既存の translator.set_priority()
# (priority=0で呼ぶと _queue_priorities から pop する実装が既にある) を
# そのまま再利用し、新しいロック/ストアは不要。

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER = "Reset priority on playback start"
if MARKER in a:
    print("actor.py already patched for prio reset on playback start, skip")
else:
    old_event = (
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
        "            translator.add_playtime(kwargs.get(\"time_position\"))\n"
    )
    assert a.count(old_event) == 1, f"old_event count={a.count(old_event)}"
    new_event = old_event + (
        '        if event == "track_playback_started":\n'
        "            # Reset priority on playback start (実MPD\n"
        "            # playlist::SongStarted() 相当、明示play/自然送りの\n"
        "            # 両方をこの1イベントでカバーする)。\n"
        '            tl_track = kwargs.get("tl_track")\n'
        "            if tl_track is not None:\n"
        "                translator.set_priority(tl_track.tlid, 0)\n"
    )
    assert new_event != old_event
    a = a.replace(old_event, new_event, 1)
    open(ap, "w").write(a)
    print("patched actor.py: track_playback_started で曲の優先度を0へリセット")
