# lsinfo/listall/listallinfo/listfiles がルート以外のディレクトリをブラウズしたとき、
# mopidy_ytmusic backend が `Ref.playlist(...)` として埋め込む「YouTube Music の
# 各ホーム/Auto Playlistsセクション内のプレイリスト項目」(mopidy_ytmusic/library.py
# の "ytmusic:home:%d"/"ytmusic:auto:*" 配下で実際に Ref.playlist(...) を生成している
# 箇所)を、実MPDでは `playlist: NAME` として返すべきところ常に `directory: NAME` と
# して返してしまう不具合。TODO 全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見した項目。
#
# 原因: dispatcher.py の MpdContext.browse() は非TRACKの ref を type
# (DIRECTORY か PLAYLIST か)で区別せず一律 `yield (path, None)` に潰しており、
# music_db.py の listall()/listallinfo()/listfiles()/lsinfo() はこの `None`
# (または lookup=False 時の ref そのもの)だけを見て無条件に "directory" を積む。
#
# rmpc側の根拠 (mierak/rmpc, git clone して確認): rmpc-mpd/src/commands/lsinfo.rs の
# `FromMpd for LsInfo` は `directory:`/`file:`/`playlist:` を別エントリ型として
# 区別してパースし、rmpc/src/ui/dir_or_song.rs の `into_dir_or_song()` は
# `LsInfoEntry::Playlist` をユーザー設定 `ShowPlaylistsMode`(`All`/`None`/`NonRoot`)
# に応じて表示/非表示を切り替え、`DirOrSong::Dir{ playlist: bool, .. }` フラグは
# `group_by_type` ソートでの並び順にも使われる。埋め込みプレイリストが一律
# `directory:` として返ると、ブラウズ中はプレイリストを隠す設定が効かず、
# ソート分類も誤る。
#
# 修正方針: dispatcher.py の browse() で非TRACK refのうち ref.type == ref.PLAYLIST
# の場合だけ、既存の「falsyならディレクトリ」という呼び出し側の判定を壊さない
# falsy な区別可能マーカー(空タプル `()`。bool(()) は False で
# `not lookup_future`/`not track_ref` は従来通り真になりつつ、`== ()` で
# ディレクトリと判別できる。CPython実装詳細に依存する `is` 同一性ではなく `==`
# の値比較のみに頼るため、Ref/future 側で特別な __eq__ が無くても安全)を
# yield するよう変更し、listall()/listallinfo()/listfiles()/lsinfo() 側でこの
# マーカーを見て ("playlist", path) を出すよう分岐を追加する(recursive=True の
# 場合、プレイリストの中身も従来通り library.browse() で再帰的に辿れる
# 既存動作は無変更で維持。mopidy_ytmusic/library.py の "ytmusic:playlist:ID" browse
# は実際に曲一覧を返すため、listall/listallinfo の再帰列挙が壊れないことを確認済み)。

p = "mopidy_mpd/dispatcher.py"
s = open(p).read()

MARKER = "ref.type == ref.PLAYLIST else None"
if MARKER in s:
    print("mpdbrowseplaylist already applied to dispatcher.py, skip")
else:
    old_block = (
        "                if ref.type == ref.TRACK:\n"
        "                    if lookup:\n"
        "                        # TODO: can we lookup all the refs at once now?\n"
        "                        yield (path, self.core.library.lookup(uris=[ref.uri]))\n"
        "                    else:\n"
        "                        yield (path, ref)\n"
        "                else:\n"
        "                    yield (path, None)\n"
        "                    if recursive:\n"
        "                        path_and_futures.append(\n"
        "                            (path, self.core.library.browse(ref.uri))\n"
        "                        )\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "                if ref.type == ref.TRACK:\n"
        "                    if lookup:\n"
        "                        # TODO: can we lookup all the refs at once now?\n"
        "                        yield (path, self.core.library.lookup(uris=[ref.uri]))\n"
        "                    else:\n"
        "                        yield (path, ref)\n"
        "                else:\n"
        "                    # 空タプルは falsy(directoryと同じ既存呼び出し側判定を維持)\n"
        "                    # だが == () で判別可能な「プレイリストref」マーカー\n"
        "                    yield (path, () if ref.type == ref.PLAYLIST else None)\n"
        "                    if recursive:\n"
        "                        path_and_futures.append(\n"
        "                            (path, self.core.library.browse(ref.uri))\n"
        "                        )\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    open(p, "w").write(s)
    print(
        "patched dispatcher.py: browse()がPLAYLIST refを空タプルマーカーで"
        "ディレクトリと区別できるよう修正"
    )

p2 = "mopidy_mpd/protocol/music_db.py"
s2 = open(p2).read()

MARKER2 = 'if track_ref == ():\n            result.append(("playlist"'
if MARKER2 in s2:
    print("mpdbrowseplaylist already applied to music_db.py listall(), skip")
else:
    old_listall = (
        "    result = []\n"
        "    for path, track_ref in context.browse(uri, lookup=False):\n"
        "        if not track_ref:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        '            result.append(("file", track_ref.uri))\n'
        "\n"
        "    if not result:\n"
        '        raise exceptions.MpdNoExistError("Not found")\n'
        "    return result\n"
    )
    assert s2.count(old_listall) == 1, f"old_listall count={s2.count(old_listall)}"

    new_listall = (
        "    result = []\n"
        "    for path, track_ref in context.browse(uri, lookup=False):\n"
        "        if track_ref == ():\n"
        '            result.append(("playlist", path.lstrip("/")))\n'
        "        elif not track_ref:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        '            result.append(("file", track_ref.uri))\n'
        "\n"
        "    if not result:\n"
        '        raise exceptions.MpdNoExistError("Not found")\n'
        "    return result\n"
    )
    assert new_listall != old_listall
    s2 = s2.replace(old_listall, new_listall, 1)
    print("patched music_db.py: listall()にplaylist分岐を追加")

    old_listallinfo = (
        "    result = []\n"
        "    for path, lookup_future in context.browse(uri):\n"
        "        if not lookup_future:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        "            for tracks in lookup_future.get().values():\n"
        "                for track in tracks:\n"
        "                    result.extend(\n"
        "                        translator.track_to_mpd_format(\n"
        "                            track, context.session.tagtypes\n"
        "                        )\n"
        "                    )\n"
        "    return result\n"
    )
    assert (
        s2.count(old_listallinfo) == 1
    ), f"old_listallinfo count={s2.count(old_listallinfo)}"

    new_listallinfo = (
        "    result = []\n"
        "    for path, lookup_future in context.browse(uri):\n"
        "        if lookup_future == ():\n"
        '            result.append(("playlist", path.lstrip("/")))\n'
        "        elif not lookup_future:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        "            for tracks in lookup_future.get().values():\n"
        "                for track in tracks:\n"
        "                    result.extend(\n"
        "                        translator.track_to_mpd_format(\n"
        "                            track, context.session.tagtypes\n"
        "                        )\n"
        "                    )\n"
        "    return result\n"
    )
    assert new_listallinfo != old_listallinfo
    s2 = s2.replace(old_listallinfo, new_listallinfo, 1)
    print("patched music_db.py: listallinfo()にplaylist分岐を追加")

    old_listfiles = (
        "    result = []\n"
        "    for path, ref in context.browse(uri, recursive=False, lookup=False):\n"
        "        if ref is None:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        '            result.append(("file", ref.uri))\n'
        "    return result\n"
    )
    assert s2.count(old_listfiles) == 1, f"old_listfiles count={s2.count(old_listfiles)}"

    new_listfiles = (
        "    result = []\n"
        "    for path, ref in context.browse(uri, recursive=False, lookup=False):\n"
        "        if ref == ():\n"
        '            result.append(("playlist", path.lstrip("/")))\n'
        "        elif ref is None:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        '            result.append(("file", ref.uri))\n'
        "    return result\n"
    )
    assert new_listfiles != old_listfiles
    s2 = s2.replace(old_listfiles, new_listfiles, 1)
    print("patched music_db.py: listfiles()にplaylist分岐を追加")

    old_lsinfo = (
        "    result = []\n"
        "    try:\n"
        "        for path, lookup_future in context.browse(uri, recursive=False):\n"
        "            if not lookup_future:\n"
        '                result.append(("directory", path.lstrip("/")))\n'
        "            else:\n"
        "                for tracks in lookup_future.get().values():\n"
        "                    if tracks:\n"
        "                        result.extend(\n"
        "                            translator.track_to_mpd_format(\n"
        "                                tracks[0], context.session.tagtypes\n"
        "                            )\n"
        "                        )\n"
        "    except exceptions.MpdNoExistError:\n"
    )
    assert s2.count(old_lsinfo) == 1, f"old_lsinfo count={s2.count(old_lsinfo)}"

    new_lsinfo = (
        "    result = []\n"
        "    try:\n"
        "        for path, lookup_future in context.browse(uri, recursive=False):\n"
        "            if lookup_future == ():\n"
        '                result.append(("playlist", path.lstrip("/")))\n'
        "            elif not lookup_future:\n"
        '                result.append(("directory", path.lstrip("/")))\n'
        "            else:\n"
        "                for tracks in lookup_future.get().values():\n"
        "                    if tracks:\n"
        "                        result.extend(\n"
        "                            translator.track_to_mpd_format(\n"
        "                                tracks[0], context.session.tagtypes\n"
        "                            )\n"
        "                        )\n"
        "    except exceptions.MpdNoExistError:\n"
    )
    assert new_lsinfo != old_lsinfo
    s2 = s2.replace(old_lsinfo, new_lsinfo, 1)
    print("patched music_db.py: lsinfo()にplaylist分岐を追加")

    open(p2, "w").write(s2)
