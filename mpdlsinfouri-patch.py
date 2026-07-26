# `lsinfo {URI}` (music_db.py) が、曲そのものの生 URI (例: ytmusic:track:xxx) を渡されると
# 常に `ACK [50@0] {lsinfo} Not found` になる不具合。TODO 全項目消化済みのため自走エージェントが
# rmpc 本体 (mierak/rmpc) を実際に clone して調査し、rmpc/src/ui/panes/search/mod.rs の
# 検索ペイン search() (236-304行目) が、テキストフィルタ無しで Rating/Liked フィルタのみを
# 指定した場合 (mopidy-mpd では既に mpdstickerfind-patch.py 対応済みの
# `sticker find song "" rating ...`/`like ...` 相当) に到達する分岐で、ヒットした各曲の
# `sticker find` 結果の `file` (= rmpc-mpd/src/shared/mpd_client_ext.rs set_sticker_multiple
# の `Enqueue::File{path}` = song.file、バックエンドの生URIそのもの) を使い、
# `send_start_cmd_list()` によるコマンドリスト内で URI 毎に `send_lsinfo(Some(&uri))`
# (299行目) を呼んでタグ情報を再取得していることを確認した上で着手。
#
# 原因: mopidy_mpd/dispatcher.py の `MpdSession.browse()` は URI 引数を「バックエンドの生URI」
# ではなく「表示名で構成された仮想パス文字列」として扱う。`re.findall(r"[^/]+", uri)` で
# パス区切りを解釈し、`_uri_map.uri_from_name()` (過去の lsinfo/browse でディレクトリ走査した
# 際にのみ登録される表示名→URIキャッシュ) で解決を試み、未登録なら `core.library.browse()` の
# 結果を `ref.name == part` の表示名一致で辿る。ytmusic:track:xxx のような生URIは "/" を
# 含まないため1セグメント丸ごとが `part` になり、`_uri_map` にも表示名一覧にも一致せず
# 必ず `for...else` の `raise exceptions.MpdNoExistError("Not found")` に落ちる。
# music_db.py の `lsinfo()` はこれをそのまま伝播するだけなので、生URIを渡す呼び出しは
# バックエンドを問わず常に失敗する。
#
# 実 MPD の仕様: MusicPlayerDaemon/MPD の src/command/DatabaseCommands.cxx
# handle_lsinfo2 は selection の URI を db.Visit() に渡し、VisitSong にマッチすれば
# (src/db/DatabasePrint.cxx) PrintSongFull() でその曲1件のタグ情報を返す
# (WebFetchで実ソース確認済み)。つまり実MPDでは「曲ファイルのURIそのものを渡された
# lsinfo」は Not found ではなくその曲のタグ情報を返すのが正しい仕様であり、
# mopidy_mpd の「表示名パス」前提の browse() 実装がこの等価性を満たしていないのが
# 本質的な原因 (mount/crossfade等の「バックエンドがリモートAPI丸投げのため対応不能」
# という既存の制約とは異なり、mopidy_mpd 自身の設計上の非互換のため修正可能)。
#
# 修正方針: readcomments (mpdreadcomments-patch.py) と同じ流儀で、browse() が
# MpdNoExistError を投げた場合のフォールバックとして `context.core.library.lookup()`
# で生URIとして直接解決を試みる。解決できればその曲のタグ情報を返し、解決できなければ
# 元の Not found をそのまま再送出する (ディレクトリが本当に存在しないケースの
# 回帰を防ぐ)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "except exceptions.MpdNoExistError:\n        if uri is None:\n            raise\n        tracks = context.core.library.lookup(uris=[uri]).get().get(uri) or []"
if MARKER in s:
    print("music_db.py already patched for lsinfo raw-uri fallback, skip")
else:
    old_block = (
        "    result = []\n"
        "    for path, lookup_future in context.browse(uri, recursive=False):\n"
        "        if not lookup_future:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        "            for tracks in lookup_future.get().values():\n"
        "                if tracks:\n"
        "                    result.extend(\n"
        "                        translator.track_to_mpd_format(\n"
        "                            tracks[0], context.session.tagtypes\n"
        "                        )\n"
        "                    )\n"
        "\n"
        '    if uri in (None, "", "/") and (\n'
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
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
        "        if uri is None:\n"
        "            raise\n"
        "        tracks = context.core.library.lookup(uris=[uri]).get().get(uri) or []\n"
        "        if not tracks:\n"
        "            raise\n"
        "        result = list(\n"
        "            translator.track_to_mpd_format(tracks[0], context.session.tagtypes)\n"
        "        )\n"
        "\n"
        '    if uri in (None, "", "/") and (\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: lsinfo に生URI(曲そのもの)フォールバックを追加 "
        "(browse()の仮想パス解決が失敗した場合、library.lookup()で直接解決を試みてから "
        "曲のタグ情報を返す。従来通りのディレクトリNot foundは無変更で維持)"
    )
