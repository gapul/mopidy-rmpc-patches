# add/addid/findadd/searchadd/load (POSITION の相対指定 `+N`/`-N`、現在曲基準) に
# 共通するTOCTOUレース。TODO/既知の軽微な残課題を全項目消化済みのため自走
# エージェントがmopidy_mpdのコード品質を再調査して発見した項目。
#
# これら5コマンドはいずれも、POSITIONを実際の挿入位置へ解決するために
# `context.core.tracklist.get_length().get()` (キュー長) と (相対指定の場合)
# `context.core.tracklist.index().get()` (現在曲位置) という**別々の**core
# 呼び出しで値を読み取り、その後にさらに別のcore呼び出しである
# `context.core.tracklist.add(uris=..., at_position=解決済み位置).get()` で
# 実際に挿入する。「位置を読む」→「挿入する」の間には他クライアントの
# delete/move/next(自動進行含む)等が割り込める窓が存在するが、
# mopidy/core/tracklist.py の add() は `self._tl_tracks.insert(at_position,
# tl_track)` という素の list.insert() で、範囲外indexを例外無く黙って
# クランプするため、割り込みが起きても一切のエラーが出ず、OK応答のまま
# 無関係な位置へサイレントに挿入されてしまう (mpdmovetorace-patch.py が
# move/moveidのTO解決について確認した性質と同型)。
#
# 実害: 既存パッチ (mpdaddpos-patch.py/mpdfindaddpos-patch.py/
# mpdloadpos-patch.py) がrmpc本体 (mierak/rmpc) のrmpc-mpd/src/mpd_client.rs
# send_add/send_find_add/send_load_playlistを実際にソース確認済みの通り、
# 「現在の曲の次/前に追加」キーバインド (rmpc/src/config/keys/actions.rs
# Position::AfterCurrentSong/BeforeCurrentSong) は日常的に `add URI +0`
# 等のPOSITION付きコマンドを送信する。2台目のrmpc接続や自動再生の曲送りが
# 同時に走ると、「次に追加」したはずの曲が無関係な位置に挿入され、OK応答が
# 返るためrmpc/ユーザーは失敗に気付けずキュー順序がサイレントに破損する。
# findadd/searchaddは特に、POSITION解決の**手前**で
# `context.core.library.search()` というネットワーク呼び出し
# (mopidy_ytmusicなら実際のYouTube Music検索API、数百ms〜数秒)を挟むため
# レース窓が他の2コマンドより広い。
#
# mpdaddloadrace-patch.py は「末尾追加+move の2段階」というTOCTOUを
# at_position直接指定へ変更し解消したが、その際「addidは1回のcore呼び出しで
# 完結するのでレース無し」と結論しており、位置解決自体 (get_length/index)
# と最終add()実行の間に残るこの窓には触れていなかった。
# mpdaddbrowserace-patch.pyはbrowse()呼び出しとposition解決の順序のみを
# 対象とし、この窓とは別種。BACKLOG.md全文検索でも
# `_mpd_resolve_add_position`/`_mpd_resolve_addpos_position`/
# `_mpd_resolve_load_position`は各初出の1箇所にしか登場せず、後続のどの
# 是正項目にも再訪されていないことを確認した。
#
# 修正方針: mpdmovetorace-patch.pyと同じ楽観的排他制御パターンを適用する。
# POSITION解決の開始直前 (相対/絶対どちらの指定でも解決処理そのものより前)
# に `version = context.core.tracklist.get_version().get()` を記録し、
# `tracklist.add()` 実行後、実際に1曲以上追加できていた場合のみ
# (0件追加、つまりversionが元々増えないケースを誤検知しないよう
# `new_tl_tracks`/`tl_tracks`が非空であることをガードに使う) versionが
# baseline+1と一致するか確認、不一致ならACK Bad song indexへ変換する
# (move/moveidと同様「操作は既に実行された状態でACKを返す」既知の許容パターン)。
# POSITION省略時 (絶対追加のみ) は解決処理自体が無く単一core呼び出しで
# 完結するためレースが無く、対象外のまま (version変数はNoneのまま)。
#
# 既知の残存限界: tracklist.version は内容変更でしか増えないため、index() 読み取りと
# add() の間に「再生曲の自動進行 / 他クライアントの next」だけが起きた場合 (内容不変)
# は検知できない。ミリ秒級の窓であり、実 MPD の単一スレッド原子性を mopidy core API
# 上で完全再現する手段が無い (add 後の補正 move も同じ窓を持つ) ため意図的に許容する。

import re

def _install_helper(content, resolve_end_anchor, target_decorator_anchor):
    anchor = resolve_end_anchor + target_decorator_anchor
    assert content.count(anchor) == 1, f"anchor count={content.count(anchor)}"
    helper = (
        resolve_end_anchor
        + "\n"
        + "def _mpd_check_position_race(context, version):\n"
        + "    # POSITION解決(get_length/index)からtracklist.add()実行までの間に\n"
        + "    # 他接続の操作が割り込むと挿入位置が意図とずれるが、\n"
        + "    # tracklist.add()自体はlist.insert()の範囲外indexクランプにより\n"
        + "    # 無条件で成功しエラーが出ない。tracklist.versionの楽観的排他制御で\n"
        + "    # 割り込みを検知する (mpdmovetorace-patch.pyと同じパターン)。\n"
        + "    if context.core.tracklist.get_version().get() != version + 1:\n"
        + '        raise exceptions.MpdArgError("Bad song index")\n'
        + "\n\n"
        + target_decorator_anchor
    )
    return content.replace(anchor, helper, 1)


# --- current_playlist.py: add / addid ---

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

if "_mpd_check_position_race" in c:
    print("current_playlist.py already patched for add position race, skip")
else:
    resolve_end = (
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n\n"
    )
    add_decorator = '@protocol.commands.add("add", songpos=_mpd_add_position)\n'
    c = _install_helper(c, resolve_end, add_decorator)

    old_add = (
        '@protocol.commands.add("add", songpos=_mpd_add_position)\n'
        "def add(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``add {URI} [POSITION]``\n"
        "\n"
        "        Adds the file ``URI`` to the playlist (directories add recursively).\n"
        "        ``URI`` can also be a single file.\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before). Absent, songs\n"
        "        are appended to the end of the playlist as before.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``add ""`` should add all tracks in the library to the current playlist.\n'
        '    """\n'
        '    if not uri.strip("/"):\n'
        "        return\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        "    new_tl_tracks = []\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        position = None\n"
        "        if songpos is not None:\n"
        "            old_size = context.core.tracklist.get_length().get()\n"
        "            position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=[uri], at_position=position\n"
        "        ).get()\n"
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
        "        position = None\n"
        "        if songpos is not None:\n"
        "            old_size = context.core.tracklist.get_length().get()\n"
        "            position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=uris, at_position=position\n"
        "        ).get()\n"
        "\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert c.count(old_add) == 1, f"old_add count={c.count(old_add)}"
    new_add = (
        '@protocol.commands.add("add", songpos=_mpd_add_position)\n'
        "def add(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``add {URI} [POSITION]``\n"
        "\n"
        "        Adds the file ``URI`` to the playlist (directories add recursively).\n"
        "        ``URI`` can also be a single file.\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before). Absent, songs\n"
        "        are appended to the end of the playlist as before.\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``add ""`` should add all tracks in the library to the current playlist.\n'
        '    """\n'
        '    if not uri.strip("/"):\n'
        "        return\n"
        "\n"
        "    # If we have an URI just try and add it directly without bothering with\n"
        "    # jumping through browse...\n"
        "    added = False\n"
        "    new_tl_tracks = []\n"
        "    version = None\n"
        '    if urllib.parse.urlparse(uri).scheme != "":\n'
        "        position = None\n"
        "        if songpos is not None:\n"
        "            version = context.core.tracklist.get_version().get()\n"
        "            old_size = context.core.tracklist.get_length().get()\n"
        "            position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=[uri], at_position=position\n"
        "        ).get()\n"
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
        "        position = None\n"
        "        version = None\n"
        "        if songpos is not None:\n"
        "            version = context.core.tracklist.get_version().get()\n"
        "            old_size = context.core.tracklist.get_length().get()\n"
        "            position = _mpd_resolve_add_position(context, songpos, old_size)\n"
        "        new_tl_tracks = context.core.tracklist.add(\n"
        "            uris=uris, at_position=position\n"
        "        ).get()\n"
        "\n"
        "    if version is not None and new_tl_tracks:\n"
        "        _mpd_check_position_race(context, version)\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    c = c.replace(old_add, new_add, 1)

    old_addid = (
        '@protocol.commands.add("addid", songpos=_mpd_addid_position)\n'
        "def addid(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addid {URI} [POSITION]``\n"
        "\n"
        "        Adds a song to the playlist (non-recursive) and returns the song id.\n"
        "\n"
        "        ``URI`` is always a single file or URL. For example::\n"
        "\n"
        '            addid "foo.mp3"\n'
        "            Id: 999\n"
        "            OK\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before).\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``addid ""`` should return an error.\n'
        '    """\n'
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "\n"
        "    at_position = None\n"
        "    if songpos is not None:\n"
        "        kind, offset = songpos\n"
        "        length = context.core.tracklist.get_length().get()\n"
        "        if kind is None:\n"
        "            if offset > length:\n"
        '                raise exceptions.MpdArgError("Bad song index")\n'
        "            at_position = offset\n"
        "        else:\n"
        "            current = context.core.tracklist.index().get()\n"
        "            if current is None:\n"
        '                raise _MpdPlayerSyncError("No current song")\n'
        '            if kind == "+":\n'
        "                if offset > length - current - 1:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current + 1 + offset\n"
        "            else:\n"
        "                if offset > current:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current - offset\n"
        "\n"
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    translator.stamp_added([tl_track.tlid for tl_track in tl_tracks])\n"
        '    return ("Id", tl_tracks[0].tlid)\n'
    )
    assert c.count(old_addid) == 1, f"old_addid count={c.count(old_addid)}"
    new_addid = (
        '@protocol.commands.add("addid", songpos=_mpd_addid_position)\n'
        "def addid(context, uri, songpos=None):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``addid {URI} [POSITION]``\n"
        "\n"
        "        Adds a song to the playlist (non-recursive) and returns the song id.\n"
        "\n"
        "        ``URI`` is always a single file or URL. For example::\n"
        "\n"
        '            addid "foo.mp3"\n'
        "            Id: 999\n"
        "            OK\n"
        "\n"
        "        ``POSITION`` may be relative to the current song: ``+N`` inserts\n"
        "        ``N`` songs after the current song (``+0`` = right after), ``-N``\n"
        "        inserts ``N`` songs before it (``-0`` = right before).\n"
        "\n"
        "    *Clarifications:*\n"
        "\n"
        '    - ``addid ""`` should return an error.\n'
        '    """\n'
        "    if not uri:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "\n"
        "    at_position = None\n"
        "    version = None\n"
        "    if songpos is not None:\n"
        "        version = context.core.tracklist.get_version().get()\n"
        "        kind, offset = songpos\n"
        "        length = context.core.tracklist.get_length().get()\n"
        "        if kind is None:\n"
        "            if offset > length:\n"
        '                raise exceptions.MpdArgError("Bad song index")\n'
        "            at_position = offset\n"
        "        else:\n"
        "            current = context.core.tracklist.index().get()\n"
        "            if current is None:\n"
        '                raise _MpdPlayerSyncError("No current song")\n'
        '            if kind == "+":\n'
        "                if offset > length - current - 1:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current + 1 + offset\n"
        "            else:\n"
        "                if offset > current:\n"
        '                    raise exceptions.MpdArgError("Number too large")\n'
        "                at_position = current - offset\n"
        "\n"
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    if version is not None:\n"
        "        _mpd_check_position_race(context, version)\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in tl_tracks])\n"
        '    return ("Id", tl_tracks[0].tlid)\n'
    )
    c = c.replace(old_addid, new_addid, 1)

    open(cp, "w").write(c)
    print("patched current_playlist.py: add/addidのPOSITION解決レースを修正")


# --- music_db.py: findadd / searchadd ---

mp = "mopidy_mpd/protocol/music_db.py"
m = open(mp).read()

if "_mpd_check_position_race" in m:
    print("music_db.py already patched for add position race, skip")
else:
    resolve_end = (
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n\n"
    )
    findadd_decorator = '@protocol.commands.add("findadd")\n'
    m = _install_helper(m, resolve_end, findadd_decorator)

    old_findadd_tail = (
        "    position = None\n"
        "    if _position is not None:\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks], at_position=position\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert m.count(old_findadd_tail) == 2, f"old_findadd_tail count={m.count(old_findadd_tail)}"
    new_addpos_tail = (
        "    position = None\n"
        "    version = None\n"
        "    if _position is not None:\n"
        "        version = context.core.tracklist.get_version().get()\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks], at_position=position\n"
        "    ).get()\n"
        "    if version is not None and new_tl_tracks:\n"
        "        _mpd_check_position_race(context, version)\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    # findadd と searchadd で完全に同一の末尾ブロック (shared helper への委譲の
    # 都合上、query組み立て以外は同型)。2箇所とも同じ置換を適用する。
    m = m.replace(old_findadd_tail, new_addpos_tail, 2)

    open(mp, "w").write(m)
    print("patched music_db.py: findadd/searchaddのPOSITION解決レースを修正")


# --- stored_playlists.py: load ---

sp = "mopidy_mpd/protocol/stored_playlists.py"
sc = open(sp).read()

if "_mpd_check_position_race" in sc:
    print("stored_playlists.py already patched for add position race, skip")
else:
    resolve_end = (
        "    if offset > current:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    return current - offset\n"
        "\n\n"
    )
    load_decorator = (
        "@protocol.commands.add(\n"
        '    "load", playlist_slice=protocol.RANGE, songpos=_mpd_load_position\n'
        ")\n"
    )
    sc = _install_helper(sc, resolve_end, load_decorator)

    old_load_tail = (
        "    playlist = _get_playlist(context, name)\n"
        "    position = None\n"
        "    if songpos is not None:\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_load_position(context, songpos, old_size)\n"
        "\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=track_uris, at_position=position\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    assert sc.count(old_load_tail) == 1, f"old_load_tail count={sc.count(old_load_tail)}"
    new_load_tail = (
        "    playlist = _get_playlist(context, name)\n"
        "    position = None\n"
        "    version = None\n"
        "    if songpos is not None:\n"
        "        version = context.core.tracklist.get_version().get()\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_load_position(context, songpos, old_size)\n"
        "\n"
        "    track_uris = [track.uri for track in playlist.tracks[playlist_slice]]\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=track_uris, at_position=position\n"
        "    ).get()\n"
        "    if version is not None and new_tl_tracks:\n"
        "        _mpd_check_position_race(context, version)\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "    translator.set_last_loaded_playlist(name)\n"
    )
    sc = sc.replace(old_load_tail, new_load_tail, 1)

    open(sp, "w").write(sc)
    print("patched stored_playlists.py: loadのPOSITION解決レースを修正")
