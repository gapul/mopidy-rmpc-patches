# MPD 0.24+ の queue "Added" (各曲がキューへ追加された時刻、ISO 8601) が
# mopidy-mpd 3.3.0 では一切出力されない件。TODO 全項目消化済みのため自走
# エージェントが調査して新規発見・追加した項目。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc-mpd/src/commands/current_song.rs の `Song` 構造体が "added" キーを
# 専用フィールド `added: Option<DateTime<Utc>>` として解釈しており (コメントに
# "Option because it is present from mpd 0.24 onwards" と明記)、CHANGELOG.md
# v0.11.0 の "Added `Added()` ... song properties" で `SongProperty::Added()`
# として rmpc/src/ui/song_ext.rs (song_table_format のカラム表示) /
# rmpc/src/ui/dir_or_song.rs (キューの `Sort`/`SortByColumn` キーバインドでの
# ソート) に実際に使われていることを確認した。musicpd.org protocol の
# "Other Metadata" 節も ISO 8601 形式で明記している (WebFetch で確認)。
# 未対応のままだと、rmpc でキューを "Added" 列で表示・ソートしても常に空欄の
# ままになる実害あるギャップ。
#
# mopidy core の Track モデル自体は「キューに追加された時刻」という概念を
# 持たない (last_modified はファイルの更新時刻でありキュー追加時刻とは無関係)
# ため、prio/crossfade/lastloadedplaylist と同じ揮発性ストア方式で
# translator.py に tlid -> ISO8601文字列 を保持する。
#
# 実装は2段構え:
# (1) キューへ実際に曲を追加する各コマンド (add/addid/findadd/searchadd/
#     stored_playlists.load) で、`context.core.tracklist.add(...)` が同期的に
#     返す新規 TlTrack のtlidを使ってその場で即座にタイムスタンプを記録する
#     (`translator.stamp_added`)。これにより `addid` の直後に同じ接続で
#     `playlistinfo` を送っても確実に反映される (CoreListenerのイベント配送は
#     別アクター経由の非同期メッセージのため、直後の応答には間に合わない
#     レースがあることを実機検証で確認済み)。
# (2) mopidy core が発火する CoreListener の `tracklist_changed` イベント
#     (delete/deleteid/clear/move等キュー変更全般で発火) を actor.py の
#     MpdFrontend.on_event で拾い、その時点の実際のtlid集合
#     (`core.tracklist.get_tl_tracks()`) と揮発性ストアを突き合わせて、
#     キューから消えたtlidを破棄する (非同期でも実害なし、単なるメモリ掃除)。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_queue_added"
if MARKER_T in t:
    print("translator.py already patched for Added, skip")
else:
    anchor = "def get_priority(tlid):\n    return _queue_priorities.get(tlid, 0)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "\n"
        "# Added (queue内の各曲がキューへ追加された時刻、MPD 0.24+) 用の揮発性\n"
        "# ストア。tlid -> ISO8601文字列。add/addid/findadd/searchadd/load が\n"
        "# その場でstamp_addedを呼び即座に記録し、actor.py の tracklist_changed\n"
        "# イベントハンドラがsync_addedで消えたtlidを破棄する (プロセス再起動で\n"
        "# 消えるのは実 MPD のキュー状態も同じなので妥当)。\n"
        "_queue_added = {}\n"
        "\n"
        "\n"
        "def stamp_added(new_tlids):\n"
        "    if not new_tlids:\n"
        "        return\n"
        "    now = datetime.datetime.now(datetime.timezone.utc).strftime(\n"
        '        "%Y-%m-%dT%H:%M:%SZ"\n'
        "    )\n"
        "    for tlid in new_tlids:\n"
        "        _queue_added.setdefault(tlid, now)\n"
        "\n"
        "\n"
        "def sync_added(current_tlids):\n"
        "    stamp_added(current_tlids)\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_added if t not in current]:\n"
        "        del _queue_added[tlid]\n"
        "\n"
        "\n"
        "def get_added(tlid):\n"
        "    return _queue_added.get(tlid)\n"
    )
    t = t.replace(anchor, anchor + store, 1)

    prio_anchor = (
        "        priority = get_priority(tlid)\n"
        "        if priority:\n"
        '            result.append(("Prio", priority))\n'
    )
    assert t.count(prio_anchor) == 1, f"prio_anchor count={t.count(prio_anchor)}"
    prio_new = prio_anchor + (
        "        added = get_added(tlid)\n"
        "        if added:\n"
        '            result.append(("Added", added))\n'
    )
    t = t.replace(prio_anchor, prio_new, 1)
    open(tp, "w").write(t)
    print("patched translator.py: Added の揮発性ストア + track_to_mpd_format反映を追加")

# --- actor.py: tracklist_changed で消えたtlidの掃除 (非同期・掃除のみ) ---

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER_A = "_sync_added_timestamps"
if MARKER_A in a:
    print("actor.py already patched for Added, skip")
else:
    old_event = (
        '    def on_event(self, event, **kwargs):\n'
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
    )
    assert a.count(old_event) == 1, f"old_event count={a.count(old_event)}"
    new_event = (
        '    def on_event(self, event, **kwargs):\n'
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
        '        if event == "tracklist_changed":\n'
        "            self._sync_added_timestamps()\n"
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
    )
    assert new_event != old_event
    a = a.replace(old_event, new_event, 1)

    anchor_method = "    def _revert_oneshot(self):\n"
    assert a.count(anchor_method) == 1, f"anchor_method count={a.count(anchor_method)}"
    end_marker = "\n    def send_idle(self, subsystem):\n"
    assert a.count(end_marker) == 1, f"end_marker count={a.count(end_marker)}"
    insert_at = a.index(end_marker)
    new_method = (
        "\n"
        "    def _sync_added_timestamps(self):\n"
        "        # Added (MPD 0.24+) 用のtlid->時刻ストアからキューに存在しなく\n"
        "        # なったtlidを掃除する (新規追加分は各コマンドが同期的に\n"
        "        # stamp_added済みのため、ここでは削除の反映のみで十分)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_added([tlid for tlid, _track in tl_tracks])\n"
    )
    a = a[:insert_at] + new_method + a[insert_at:]
    open(ap, "w").write(a)
    print("patched actor.py: tracklist_changed で消えたtlidを掃除")

# --- current_playlist.py: add / addid で同期的に stamp_added ---

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

MARKER_C = "translator.stamp_added"
if MARKER_C in c:
    print("current_playlist.py already patched for Added, skip")
else:
    old_add_body = (
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        if context.core.tracklist.add(uris=[uri]).get():\n"
        "            added = True\n"
        "\n"
        "    if not added:\n"
        "        try:\n"
        "            uris = []\n"
        "            for _path, ref in context.browse(uri, lookup=False):\n"
        "                if ref:\n"
        "                    uris.append(ref.uri)\n"
        "        except exceptions.MpdNoExistError as exc:\n"
        "            exc.message = (  # noqa B306: Our own exception\n"
        '                "directory or file not found"\n'
        "            )\n"
        "            raise\n"
        "\n"
        "        if not uris:\n"
        '            raise exceptions.MpdNoExistError("directory or file not found")\n'
        "        context.core.tracklist.add(uris=uris).get()\n"
    )
    assert c.count(old_add_body) == 1, f"old_add_body count={c.count(old_add_body)}"
    new_add_body = (
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        "    new_tl_tracks = []\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        new_tl_tracks = context.core.tracklist.add(uris=[uri]).get()\n"
        "        if new_tl_tracks:\n"
        "            added = True\n"
        "\n"
        "    if not added:\n"
        "        try:\n"
        "            uris = []\n"
        "            for _path, ref in context.browse(uri, lookup=False):\n"
        "                if ref:\n"
        "                    uris.append(ref.uri)\n"
        "        except exceptions.MpdNoExistError as exc:\n"
        "            exc.message = (  # noqa B306: Our own exception\n"
        '                "directory or file not found"\n'
        "            )\n"
        "            raise\n"
        "\n"
        "        if not uris:\n"
        '            raise exceptions.MpdNoExistError("directory or file not found")\n'
        "        new_tl_tracks = context.core.tracklist.add(uris=uris).get()\n"
        "\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert new_add_body != old_add_body
    c = c.replace(old_add_body, new_add_body, 1)

    old_addid_tail = (
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    return (\"Id\", tl_tracks[0].tlid)\n"
    )
    assert c.count(old_addid_tail) == 1, f"old_addid_tail count={c.count(old_addid_tail)}"
    new_addid_tail = (
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    translator.stamp_added([tl_track.tlid for tl_track in tl_tracks])\n"
        "    return (\"Id\", tl_tracks[0].tlid)\n"
    )
    assert new_addid_tail != old_addid_tail
    c = c.replace(old_addid_tail, new_addid_tail, 1)

    open(cp, "w").write(c)
    print("patched current_playlist.py: add/addid で Added を同期stamp")

# --- music_db.py: findadd / searchadd で同期的に stamp_added ---

mp = "mopidy_mpd/protocol/music_db.py"
m = open(mp).read()

MARKER_M = "translator.stamp_added"
if MARKER_M in m:
    print("music_db.py already patched for Added, skip")
else:
    old_findadd_tail = (
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=True\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
    )
    assert m.count(old_findadd_tail) == 1, f"old_findadd_tail count={m.count(old_findadd_tail)}"
    new_findadd_tail = (
        "    results = context.core.library.search(query=query, exact=True).get()\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=True\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert new_findadd_tail != old_findadd_tail
    m = m.replace(old_findadd_tail, new_findadd_tail, 1)

    old_searchadd_tail = (
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=False\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
    )
    assert m.count(old_searchadd_tail) == 1, f"old_searchadd_tail count={m.count(old_searchadd_tail)}"
    new_searchadd_tail = (
        "    results = context.core.library.search(query).get()\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[\n"
        "            track.uri\n"
        "            for track in _mpd_filter_negatives(\n"
        "                _get_tracks(results), _negatives, case_sensitive=False\n"
        "            )\n"
        "        ]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert new_searchadd_tail != old_searchadd_tail
    m = m.replace(old_searchadd_tail, new_searchadd_tail, 1)

    open(mp, "w").write(m)
    print("patched music_db.py: findadd/searchadd で Added を同期stamp")

# --- stored_playlists.py: load で同期的に stamp_added ---

sp = "mopidy_mpd/protocol/stored_playlists.py"
sc = open(sp).read()

MARKER_S = "translator.stamp_added"
if MARKER_S in sc:
    print("stored_playlists.py already patched for Added, skip")
else:
    old_load_tail = (
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert sc.count(old_load_tail) == 1, f"old_load_tail count={sc.count(old_load_tail)}"
    new_load_tail = (
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    new_tl_tracks = context.core.tracklist.add(uris=track_uris).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert new_load_tail != old_load_tail
    sc = sc.replace(old_load_tail, new_load_tail, 1)

    open(sp, "w").write(sc)
    print("patched stored_playlists.py: load で Added を同期stamp")
