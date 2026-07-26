# mopidy-mpd 3.3.0 の `status` は `lastloadedplaylist` (MPD 0.24+, 直近に `load`
# したストアド プレイリスト名) を一切返さない。実 MPD (MusicPlayerDaemon/MPD
# src/command/PlayerCommands.cxx COMMAND_STATUS_LOADED_PLAYLIST、
# src/playlist/PlaylistQueue.cxx playlist_load_into_queue → SetLastLoadedPlaylist、
# src/queue/Queue.cxx Queue::Clear) を実際にcloneしてソース確認したところ、
# `load NAME` 成功後に queue へ名前を記録し、`clear` でのみリセットされ (個々の
# add/delete では消えない)、`status` は毎回 `lastloadedplaylist: <name-or-empty>`
# を無条件に1行返す仕様と判明。
#
# rmpc 本体 (mierak/rmpc) を実際にcloneして調査したところ、rmpc-mpd/src/commands/
# status.rs が `lastloadedplaylist` を実際にパースし (空文字は None 扱い)、
# rmpc/src/core/event_loop.rs の `reflect_changes_to_playlist` 機能 (config で
# 有効化すると、ストアドプレイリストを load した状態でキューを編集した際に自動で
# 同名プレイリストへ save し直す) が `ctx.status.lastloadedplaylist` の前後比較で
# 動作条件を判定しており、未対応のままだとこの機能が一切発火しない実害あるギャップ。
# TODO 全項目消化済みのため自走エージェントが調査して新規発見・追加した項目。
#
# 実装: crossfade/prio (mpdcrossfade-patch.py/mpdprio-patch.py) と同じ流儀で、
# translator.py にモジュールレベルの揮発性ストアを追加。`load` 成功時に設定、
# `clear` でリセット、`status` で無条件に反映する。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_last_loaded_playlist"
if MARKER_T in t:
    print("translator.py already patched, skip")
else:
    anchor = "# TODO: special handling of local:// uri scheme\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "# load (stored_playlists.py) 用の揮発性ストア。実 MPD の Queue::last_loaded_playlist\n"
        "# 相当で、load で設定・clear でリセットする (プロセス再起動で消えるのは実 MPD の\n"
        "# queue 状態も同じなので妥当)。\n"
        '_last_loaded_playlist = ""\n'
        "\n"
        "\n"
        "def set_last_loaded_playlist(name):\n"
        "    global _last_loaded_playlist\n"
        "    _last_loaded_playlist = name\n"
        "\n"
        "\n"
        "def clear_last_loaded_playlist():\n"
        "    global _last_loaded_playlist\n"
        '    _last_loaded_playlist = ""\n'
        "\n"
        "\n"
        "def get_last_loaded_playlist():\n"
        "    return _last_loaded_playlist\n"
        "\n"
        "\n"
    )
    t = t.replace(anchor, store + anchor, 1)
    open(tp, "w").write(t)
    print("patched translator.py: lastloadedplaylist の揮発性ストアを追加")

sp = "mopidy_mpd/protocol/stored_playlists.py"
s = open(sp).read()

MARKER_S = "translator.set_last_loaded_playlist"
if MARKER_S in s:
    print("stored_playlists.py already patched, skip")
else:
    old_block = (
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    context.core.tracklist.add(uris=track_uris).get()\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"
    new_block = (
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(sp, "w").write(s)
    print("patched stored_playlists.py: load 成功時に lastloadedplaylist を記録")

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

MARKER_C = "translator.clear_last_loaded_playlist"
if MARKER_C in c:
    print("current_playlist.py already patched, skip")
else:
    old_clear = (
        "        Clears the current playlist.\n"
        '    """\n'
        "    context.core.tracklist.clear()\n"
    )
    assert c.count(old_clear) == 1, f"old_clear count={c.count(old_clear)}"
    new_clear = (
        "        Clears the current playlist.\n"
        '    """\n'
        "    context.core.tracklist.clear()\n"
        "    translator.clear_last_loaded_playlist()\n"
    )
    assert new_clear != old_clear
    c = c.replace(old_clear, new_clear, 1)
    open(cp, "w").write(c)
    print("patched current_playlist.py: clear で lastloadedplaylist をリセット")

up = "mopidy_mpd/protocol/status.py"
u = open(up).read()

MARKER_U = "translator.get_last_loaded_playlist"
if MARKER_U in u:
    print("status.py already patched, skip")
else:
    old_state = '        ("state", _status_state(futures)),\n'
    assert u.count(old_state) == 1, f"old_state count={u.count(old_state)}"
    new_state = (
        '        ("state", _status_state(futures)),\n'
        '        ("lastloadedplaylist", translator.get_last_loaded_playlist()),\n'
    )
    assert new_state != old_state
    u = u.replace(old_state, new_state, 1)
    open(up, "w").write(u)
    print("patched status.py: lastloadedplaylist フィールドを追加")
