# `listfiles` (musicpd.org protocol, music database section) が
# mopidy-mpd 3.3.0 では `raise MpdNotImplemented` のスタブのまま。TODO/既知の軽微な
# 残課題を全項目消化済みのため自走エージェントが mopidy_mpd 残りの `MpdNotImplemented`
# スタブを再洗い出しして選定 (mpdrangeid-patch.py/mpdaddtagid-patch.py 等のコメントで
# 名指しされていた listfiles/rangeid のうち rangeid は既に対応済み、listfiles のみ
# 残っていた)。rmpc 本体 (mierak/rmpc) を実際に clone して grep したが `listfiles` を
# 送信する箇所は皆無 (rmpc はこの機能を持たない) と判明。ただし clearerror/decoders/
# stats/listneighbors/rangeid と同種の「rmpc固有ではなく標準 MPD プロトコル準拠の
# 不備」に該当すると判断: mpc・ncmpcpp 等の汎用 MPD クライアントが標準的に使う基本
# コマンド (ディレクトリの生ファイル一覧、MPDが認識しないファイルも含む列挙) が常に
# ACK エラーになる現状はギャップと確認した上で着手。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/OtherCommands.cxx handle_listfiles,
# src/command/FileCommands.cxx handle_listfiles_local, src/command/StorageCommands.cxx
# handle_listfiles_storage, src/command/DatabaseCommands.cxx handle_listfiles_db) を
# 実際に取得してソース確認したところ、実体は3種類 (ローカルファイルシステム/storage
# プラグイン/DBフォールバック) に分岐するが、出力形式はどの経路でも共通:
#   - 通常ファイル: "file: {name}" + "size: {bytes}" (タグ情報は一切含まない、
#     lsinfo が返すような Artist/Album 等のタグは listfiles の仕様外)。
#   - ディレクトリ: "directory: {name}"。
#   - どちらも任意で "Last-Modified" 行が続く (取得できない場合は省略、size/
#     Last-Modified とも "may be followed by" と明記された任意属性)。
#   - ルート (URI省略/""/"/") でもプレイリストは列挙しない (lsinfo 固有の
#     「非推奨だがルートでは listplaylists 相当も返す」挙動とは無関係)。
#
# mopidy の backend は実ファイルのようなサイズ/mtimeを持たない (ストリーミング
# バックエンドの仮想エントリのため、mount/decoders/stats 等と同種に「値が存在
# しない属性は省略」という割り切り) ため、file 行は uri のみ・size や
# Last-Modified は付与しない実装にした。ディレクトリ一覧は lsinfo が既に使っている
# `context.browse(uri, recursive=False, ...)` をそのまま再利用し (不正なURIでの
# `MpdNoExistError` 等、既存の browse() のエラー処理も自然に流用される)、lookup=False
# にしてトラックの曲情報を余分にフルlookupしない (listfiles は元々タグを含まない
# 仕様のため、lsinfo のような library.lookup() 経由のtrack_to_mpd_format展開が不要)。

cp = "mopidy_mpd/protocol/music_db.py"
c = open(cp).read()

if 'result.append(("file", ref.uri))' in c:
    print("music_db.py already patched for listfiles, skip")
else:
    old_block = (
        '@protocol.commands.add("listfiles")\n'
        "def listfiles(context, uri=None):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``listfiles [URI]``\n"
        "\n"
        "        Lists the contents of the directory URI, including files are not\n"
        "        recognized by MPD. URI can be a path relative to the music directory or\n"
        "        an URI understood by one of the storage plugins. The response contains\n"
        '        at least one line for each directory entry with the prefix "file: " or\n'
        '        "directory: ", and may be followed by file attributes such as\n'
        '        "Last-Modified" and "size".\n'
        "\n"
        '        For example, "smb://SERVER" returns a list of all shares on the given\n'
        '        SMB/CIFS server; "nfs://servername/path" obtains a directory listing\n'
        "        from the NFS server.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert c.count(old_block) == 1, f"old_block count={c.count(old_block)}"

    new_block = (
        '@protocol.commands.add("listfiles")\n'
        "def listfiles(context, uri=None):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``listfiles [URI]``\n"
        "\n"
        "        Lists the contents of the directory URI, including files are not\n"
        "        recognized by MPD. URI can be a path relative to the music directory or\n"
        "        an URI understood by one of the storage plugins. The response contains\n"
        '        at least one line for each directory entry with the prefix "file: " or\n'
        '        "directory: ", and may be followed by file attributes such as\n'
        '        "Last-Modified" and "size".\n'
        "\n"
        '        For example, "smb://SERVER" returns a list of all shares on the given\n'
        '        SMB/CIFS server; "nfs://servername/path" obtains a directory listing\n'
        "        from the NFS server.\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    result = []\n"
        "    for path, ref in context.browse(uri, recursive=False, lookup=False):\n"
        "        if ref is None:\n"
        '            result.append(("directory", path.lstrip("/")))\n'
        "        else:\n"
        '            result.append(("file", ref.uri))\n'
        "    return result\n"
    )
    assert new_block != old_block
    c = c.replace(old_block, new_block, 1)
    open(cp, "w").write(c)
    print(
        "patched music_db.py: listfiles を実装 "
        "(file:/directory: を browse() 経由で列挙、size/Last-Modifiedは非対応属性として省略)"
    )
