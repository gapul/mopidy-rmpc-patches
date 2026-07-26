# mopidy-mpd 3.3.0 の `listneighbors` (mopidy_mpd/protocol/mount.py) は
# `raise MpdNotImplemented` のスタブで常に ACK エラーになる。TODO 全項目消化済みのため
# 自走エージェントが mopidy_mpd 残りの MpdNotImplemented スタブ (listfiles/rangeid/
# addtagid/cleartagid/clearerror/listneighbors, mpdclearerror-patch.py のコメントで
# 洗い出し済み) から、次に着手可能な1件として選定。rmpc 本体 (mierak/rmpc) を実際に
# clone して grep したが `listneighbors` を送信する箇所は皆無 (idle "neighbor" イベントも
# event_loop.rs で `log::warn!("Received unhandled event")` するだけで listneighbors を
# 送り返す導線は無い) と判明。clearerror/mixrampdb/decoders/replay_gain と同種の
# 「rmpc固有ではなく標準 MPD プロトコル準拠の不備」に該当すると判断し、実 MPD
# (MusicPlayerDaemon/MPD src/command/NeighborCommands.cxx handle_listneighbors) を
# 実際にソース確認した上で着手。
#
# 実 MPD の仕様: `client.GetInstance().neighbors` (NeighborGlue、smb/upnp 等の neighbor
# プラグインが1つ以上有効な場合のみ生成される) が null なら
# `r.Error(ACK_ERROR_UNKNOWN, "No neighbor plugin configured")` を返す。プラグインは
# あるが0件発見の場合のみ OK + 空リストになる (この2ケースは明確に区別される)。
# mopidy_mpd/mopidy core には neighbor プラグインの仕組み自体が一切存在しない
# (グローバル検索で neighbor 関連の実装コードは皆無) ため、常に前者
# (プラグイン自体が無い) のケースに一致する。よって「無条件 OK」の clearerror とは
# 逆に、実 MPD 仕様に合わせて ACK_ERROR_UNKNOWN(5) "No neighbor plugin configured"
# を返すのが正しい実装であり、既存の `MpdNotImplemented` (error_code=0 "Not
# implemented") は ACK エラーになる点は結果的に同じでもエラーコード/メッセージが
# 実 MPD と異なる (mpc/ncmpcpp 等の汎用 MPD クライアントがコード5を見て
# "プラグイン未設定" と正しく判別できない) というギャップだった。

pp = "mopidy_mpd/protocol/mount.py"
s = open(pp).read()

MARKER = "No neighbor plugin configured"
if MARKER in s:
    print("mount.py already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("listneighbors")\n'
        "def listneighbors(context):\n"
        '    """\n'
        "    *musicpd.org, mounts and neighbors section:*\n"
        "\n"
        "        ``listneighbors``\n"
        "\n"
        '        Queries a list of "neighbors" (e.g. accessible file servers on the\n'
        "        local net). Items on that list may be used with the mount command.\n"
        "        Example::\n"
        "\n"
        "            listneighbors\n"
        "            neighbor: smb://FOO\n"
        "            name: FOO (Samba 4.1.11-Debian)\n"
        "            OK\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("listneighbors")\n'
        "def listneighbors(context):\n"
        '    """\n'
        "    *musicpd.org, mounts and neighbors section:*\n"
        "\n"
        "        ``listneighbors``\n"
        "\n"
        '        Queries a list of "neighbors" (e.g. accessible file servers on the\n'
        "        local net). Items on that list may be used with the mount command.\n"
        "        Example::\n"
        "\n"
        "            listneighbors\n"
        "            neighbor: smb://FOO\n"
        "            name: FOO (Samba 4.1.11-Debian)\n"
        "            OK\n"
        "\n"
        "    .. versionadded:: 0.19\n"
        "        New in MPD protocol version 0.19\n"
        '    """\n'
        "    # mopidy core/mopidy_mpd には neighbor 探索プラグイン (smb/upnp等) の仕組み\n"
        "    # 自体が無く、実MPDの「neighborsプラグインが1つも無い」ケース\n"
        "    # (NeighborCommands.cxx: instance.neighbors == nullptr) と常に一致するため、\n"
        '    # 実MPD仕様通り ACK_ERROR_UNKNOWN(5) で "No neighbor plugin configured" を返す。\n'
        '    raise exceptions.MpdUnknownError("No neighbor plugin configured")\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched mount.py: listneighbors を実MPD仕様のACKエラー(5, No neighbor plugin configured)に統一")
