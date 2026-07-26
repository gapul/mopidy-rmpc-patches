# `addtagid`/`cleartagid` (musicpd.org protocol, current playlist section) が
# mopidy-mpd 3.3.0 では `raise MpdNotImplemented` のスタブのまま。TODO 全項目
# 消化済みのため自走エージェントが mopidy_mpd 残りの `MpdNotImplemented` スタブ
# (listfiles/rangeid/addtagid/cleartagid、mpdclearerror-patch.py/
# mpdlistneighbors-patch.py のコメントで洗い出し済み) から選定。rmpc 本体
# (mierak/rmpc) を実際に clone して grep したが addtagid/cleartagid を送信する
# 箇所は皆無 (rmpc はこの機能を持たない) と判明。ただし listneighbors
# (mpdlistneighbors-patch.py) と同じく「rmpc固有ではなく標準 MPD プロトコル
# 準拠の不備」に該当すると判断: mpc・ncmpcpp 等の汎用 MPD クライアントが
# 標準的に使うコマンドが常に ACK エラーになる現状はギャップと確認した上で
# 着手 (`cleartagid ID` のように TAG を省略した呼び出しは、現状の固定必須
# 引数シグネチャでは "Not implemented" 以前に "wrong number of arguments" にも
# なりうる二重の不備もあわせて確認)。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/TagCommands.cxx handle_addtagid/
# handle_cleartagid, src/queue/PlaylistTag.cxx AddSongIdTag/ClearSongIdTag) を
# 実際に取得してソース確認し仕様を確定:
#   - TAG は tag_name_parse_i() (大文字小文字不問) で解決、未知の値は
#     ACK_ERROR_ARG "Unknown tag type: {name}" (music_db.py の
#     `count group Bogus` 等が既に使っている文言・エラーコードと同一)。
#   - addtagid: TAG検証 → 曲の存在確認 (無ければ ACK_ERROR_NO_EXIST
#     "No such song") → ローカルファイルでないか確認 (ローカルなら
#     ACK_ERROR_PERMISSION "Cannot edit tags of local file") の順。
#   - cleartagid: TAG省略可 (省略時は全タグ削除)。TAG検証 (指定時のみ) →
#     曲の存在確認 → ローカルファイルでないか確認、の順 (addtagidと同じ
#     チェック順序をソースで確認済み)。
#   - 変更は volatile (musicpd.org docs: "may be overwritten by tags received
#     from the server, and the data is gone when the song gets removed from
#     the queue")。
#
# mopidy のトラックは全て scheme 付き URI (ytmusic:/m3u: 等、このデプロイでは
# file: バックエンドは無効) のため「ローカルファイル」判定に実際に到達する
# 経路は無いが、仕様に忠実に urllib.parse.urlparse(uri).scheme が空 or "file"
# の場合のみ拒否する実装にした (mount/crossfade等と同種の「バックエンドが
# 存在しない事例は割り切ってプロトコル層の応答のみ用意する」パターン)。
#
# mopidy core の Track/Tag モデルは「キュー内の1曲だけに追加のタグ値を足す」
# 概念を持たないため、prio/Added と同じ流儀で translator.py に
# tlid -> {tag_type: [value, ...]} の揮発性ストアを追加し、
# track_to_mpd_format() の出力に追加行として反映する (既存の Artist/Genre 等の
# 実データはそのまま維持し、addtagid分は追加の行として重畳表示する — 実MPDの
# 「タグは複数値を持てる」仕様と同じ形。tagtypes による絞り込みも
# `_has_value()` がタグ種別名で判定するため自動的に効く)。cleartagid は
# このオーバーレイのみを消去し、Track本体の実メタデータ (実MPDなら
# サーバーから受信したタグ) には触れない — 「実際に送信されて来ないローカル
# ファイル経路には触れられない」既知の割り切りと同種の限界として明記する。
# actor.py の tracklist_changed イベント (mpdadded-patch.py が既に購読済みの
# 同じフック) で、キューから消えた tlid のオーバーレイを掃除する。

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

MARKER_C = "_MpdEditLocalTagsError"
if MARKER_C in c:
    print("current_playlist.py already patched for addtagid/cleartagid, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert c.count(old_import) == 1, f"old_import count={c.count(old_import)}"
    new_import = old_import + "from mopidy_mpd.protocol import tagtype_list\n"
    c = c.replace(old_import, new_import, 1)

    old_block = (
        '@protocol.commands.add("addtagid", tlid=protocol.UINT)\n'
        "def addtagid(context, tlid, tag, value):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addtagid {SONGID} {TAG} {VALUE}``\n"
        "\n"
        "        Adds a tag to the specified song. Editing song tags is only possible\n"
        "        for remote songs. This change is volatile: it may be overwritten by\n"
        "        tags received from the server, and the data is gone when the song gets\n"
        "        removed from the queue.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
        "\n"
        "\n"
        '@protocol.commands.add("cleartagid", tlid=protocol.UINT)\n'
        "def cleartagid(context, tlid, tag):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``cleartagid {SONGID} [TAG]``\n"
        "\n"
        "        Removes tags from the specified song. If TAG is not specified, then all\n"
        "        tag values will be removed. Editing song tags is only possible for\n"
        "        remote songs.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert c.count(old_block) == 1, f"old_block count={c.count(old_block)}"

    new_block = (
        "class _MpdEditLocalTagsError(exceptions.MpdAckError):\n"
        "    error_code = exceptions.MpdAckError.ACK_ERROR_PERMISSION\n"
        "\n"
        "\n"
        "def _mpd_canonical_tag_type(tag):\n"
        "    for known in tagtype_list.TAGTYPE_LIST:\n"
        "        if known.lower() == tag.lower():\n"
        "            return known\n"
        '    raise exceptions.MpdArgError(f"Unknown tag type: {tag}")\n'
        "\n"
        "\n"
        "def _mpd_tl_track_or_no_such_song(context, tlid):\n"
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    return tl_tracks[0]\n"
        "\n"
        "\n"
        "def _mpd_require_remote_track(track):\n"
        "    # 実 MPD 仕様: \"Editing song tags is only possible for remote songs.\"\n"
        "    # (src/queue/PlaylistTag.cxx の song.IsFile() チェック相当)。\n"
        "    scheme = urllib.parse.urlparse(track.uri or \"\").scheme\n"
        '    if scheme in ("", "file"):\n'
        '        raise _MpdEditLocalTagsError("Cannot edit tags of local file")\n'
        "\n"
        "\n"
        '@protocol.commands.add("addtagid", tlid=protocol.UINT)\n'
        "def addtagid(context, tlid, tag, value):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addtagid {SONGID} {TAG} {VALUE}``\n"
        "\n"
        "        Adds a tag to the specified song. Editing song tags is only possible\n"
        "        for remote songs. This change is volatile: it may be overwritten by\n"
        "        tags received from the server, and the data is gone when the song gets\n"
        "        removed from the queue.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    tag_type = _mpd_canonical_tag_type(tag)\n"
        "    _tlid, track = _mpd_tl_track_or_no_such_song(context, tlid)\n"
        "    _mpd_require_remote_track(track)\n"
        "    translator.add_song_tag(tlid, tag_type, value)\n"
        "\n"
        "\n"
        '@protocol.commands.add("cleartagid", tlid=protocol.UINT)\n'
        "def cleartagid(context, tlid, tag=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``cleartagid {SONGID} [TAG]``\n"
        "\n"
        "        Removes tags from the specified song. If TAG is not specified, then all\n"
        "        tag values will be removed. Editing song tags is only possible for\n"
        "        remote songs.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    tag_type = _mpd_canonical_tag_type(tag) if tag is not None else None\n"
        "    _tlid, track = _mpd_tl_track_or_no_such_song(context, tlid)\n"
        "    _mpd_require_remote_track(track)\n"
        "    translator.clear_song_tag(tlid, tag_type)\n"
    )
    assert new_block != old_block
    c = c.replace(old_block, new_block, 1)
    open(cp, "w").write(c)
    print(
        "patched current_playlist.py: addtagid/cleartagid を実装 "
        "(タグ検証・No such song・ローカルファイル拒否・揮発性オーバーレイ反映)"
    )

# --- translator.py: tlid -> {tag_type: [value, ...]} の揮発性ストア ---

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_queue_extra_tags"
if MARKER_T in t:
    print("translator.py already patched for addtagid/cleartagid, skip")
else:
    anchor = "def get_added(tlid):\n    return _queue_added.get(tlid)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "\n"
        "# addtagid/cleartagid (current_playlist.py) 用の揮発性ストア。\n"
        "# tlid -> {tag_type: [value, ...]}。実MPD同様、曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_extra_tags = {}\n"
        "\n"
        "\n"
        "def add_song_tag(tlid, tag_type, value):\n"
        "    _queue_extra_tags.setdefault(tlid, {}).setdefault(tag_type, []).append(\n"
        "        value\n"
        "    )\n"
        "\n"
        "\n"
        "def clear_song_tag(tlid, tag_type=None):\n"
        "    if tag_type is None:\n"
        "        _queue_extra_tags.pop(tlid, None)\n"
        "        return\n"
        "    tags = _queue_extra_tags.get(tlid)\n"
        "    if not tags:\n"
        "        return\n"
        "    tags.pop(tag_type, None)\n"
        "    if not tags:\n"
        "        _queue_extra_tags.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_song_tags(tlid):\n"
        "    return _queue_extra_tags.get(tlid, {})\n"
        "\n"
        "\n"
        "def sync_extra_tags(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_extra_tags if t not in current]:\n"
        "        del _queue_extra_tags[tlid]\n"
    )
    t = t.replace(anchor, anchor + store, 1)

    added_anchor = (
        "        added = get_added(tlid)\n"
        "        if added:\n"
        '            result.append(("Added", added))\n'
    )
    assert t.count(added_anchor) == 1, f"added_anchor count={t.count(added_anchor)}"
    added_new = added_anchor + (
        "        for extra_tag_type, extra_values in get_song_tags(tlid).items():\n"
        "            for extra_value in extra_values:\n"
        "                result.append((extra_tag_type, extra_value))\n"
    )
    t = t.replace(added_anchor, added_new, 1)

    open(tp, "w").write(t)
    print(
        "patched translator.py: addtagid/cleartagid の揮発性ストア + "
        "track_to_mpd_format反映を追加"
    )

# --- actor.py: tracklist_changed で消えたtlidのタグオーバーレイを掃除 ---

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER_A = "_sync_extra_tags"
if MARKER_A in a:
    print("actor.py already patched for addtagid/cleartagid, skip")
else:
    old_event = (
        '        if event == "tracklist_changed":\n'
        "            self._sync_added_timestamps()\n"
    )
    assert a.count(old_event) == 1, f"old_event count={a.count(old_event)}"
    new_event = old_event + "            self._sync_extra_tags()\n"
    a = a.replace(old_event, new_event, 1)

    anchor_method = (
        "    def _sync_added_timestamps(self):\n"
        "        # Added (MPD 0.24+) 用のtlid->時刻ストアからキューに存在しなく\n"
        "        # なったtlidを掃除する (新規追加分は各コマンドが同期的に\n"
        "        # stamp_added済みのため、ここでは削除の反映のみで十分)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_added([tlid for tlid, _track in tl_tracks])\n"
    )
    assert a.count(anchor_method) == 1, f"anchor_method count={a.count(anchor_method)}"
    new_method = (
        "\n"
        "    def _sync_extra_tags(self):\n"
        "        # addtagid/cleartagid 用のtlid->タグストアからキューに存在しなく\n"
        "        # なったtlidを掃除する (実MPD同様、曲がキューから消えたら\n"
        "        # addtagidで足したタグも消える揮発性のため)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_extra_tags([tlid for tlid, _track in tl_tracks])\n"
    )
    a = a.replace(anchor_method, anchor_method + new_method, 1)

    open(ap, "w").write(a)
    print("patched actor.py: tracklist_changed で消えたtlidのタグオーバーレイを掃除")
