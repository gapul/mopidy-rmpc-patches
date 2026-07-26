# mpdaddloadrace-patch.py は add()/load() の POSITION 実装を「末尾追加+move」の
# 2段階非同期呼び出しから `tracklist.add(at_position=position)` の単発呼び出しへ統一し、
# get_length()→add()→get_length()→move() という4回に分解されていた古典的な TOCTOU
# レースを解消した。しかし add() には別のレースが1つ残っている。
#
# add() は POSITION (`+N`/`-N` 相対指定込み) を、URI が browse 経由(ディレクトリ/
# mopidy-ytmusicのプレイリスト等、スキーム無しURI)かどうかを判定する**前**、
# つまり `context.browse(uri, lookup=False)` を呼ぶ**前**に解決してしまっている。
# `_mpd_resolve_add_position()` は絶対位置だけでなく `context.core.tracklist.index()`
# (現在再生中の曲のtracklist上の位置)にも依存するが、mopidy-ytmusicの`browse()`は
# YouTube Music APIへの同期的なネットワーク呼び出しを伴い数百ms〜数秒かかりうる。
# その間に別クライアント(または同一クライアントの別接続、rmpcのような単一アプリでも
# 複数コネクションを張りうる)が`next`/`previous`/`seek`等でカレント曲を進めると、
# add()が実際に`tracklist.add(at_position=position)`を呼ぶ時点では、positionは
# もはや「ブラウズ開始前のカレント曲」基準のまま古くなっており、ユーザーが
# 「今流れている曲の次に追加」のつもりで送った`add URI "+0"`が、ブラウズ完了時点の
# 実際のカレント曲とは無関係な位置(典型的には、ブラウズ中に進んだ新カレント曲の
# **直前**、大量に追加された曲の山の反対側)に静かに挿入されてしまう。
#
# 兄弟コマンドである findadd/searchadd (mpdfindaddrace-patch.py) や load
# (mpdaddloadrace-patch.py) は、いずれも「時間のかかるデータ取得(検索/プレイリスト
# lookup)を先に終わらせてから、position解決とtracklist.add()呼び出しを直前で
# まとめて行う」という順序になっており、レース窓が最小化されている。add()の
# browse分岐だけがこの順序から外れていた。
#
# 実機のdev mopidy(6601, ytmusic実アカウント)で実際に再現確認: 4曲(pos0-3)の
# キューでpos1を再生中に`add "(未ブラウズの91曲のYTMusicプレイリスト)" "+0"`を
# 送り、応答を待たずに別接続から即座に`next`(pos1→pos2へ移動)を送ったところ、
# `next`はcore actorのメールボックスでbrowse中のadd()の後ろに並び2秒超かかった上で
# 完了したにもかかわらず、追加された91曲は「ブラウズ開始前のカレント曲(pos1)の
# 直後」であるpos2に挿入され、`next`によって新カレント曲になっていたはずの曲
# (元pos2)がpos93まで押し出された(狙った「新カレント曲の直後」ではなく
# 「新カレント曲の直前」に91曲が挿入される形でキュー順序が破損)。
#
# 修正方針: position解決を、scheme付き分岐・browse分岐それぞれの
# `tracklist.add()`呼び出しの直前(=そのブランチで行う時間のかかる処理が
# 全て完了した後)に移動する。addid (元からこの種のレースが無い) と同じく
# 「position解決の直後に即tracklist.addへ渡す」という形に揃え、レース窓を
# 各分岐の最終呼び出し直前まで縮小する。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

old_block = (
    "    position = None\n"
    "    if songpos is not None:\n"
    "        old_size = context.core.tracklist.get_length().get()\n"
    "        position = _mpd_resolve_add_position(context, songpos, old_size)\n"
    "\n"
    "    # If we have an URI just try and add it directly without bothering with\n"
    "    # jumping through browse...\n"
    "    added = False\n"
    "    new_tl_tracks = []\n"
    '    if urllib.parse.urlparse(uri).scheme != "":\n'
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
    "        new_tl_tracks = context.core.tracklist.add(\n"
    "            uris=uris, at_position=position\n"
    "        ).get()\n"
    "\n"
    "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
)

new_block = (
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

if old_block not in s:
    assert new_block in s, "neither old_block nor new_block found in current_playlist.py: add() may have changed unexpectedly"
    print("add() browse race already patched, skip")
else:
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: add() の POSITION 解決を各分岐の"
        "tracklist.add()呼び出し直前まで遅延させ、browse()中のカレント曲変更に"
        "よるTOCTOUレース窓を縮小"
    )
