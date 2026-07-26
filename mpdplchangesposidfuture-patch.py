# mopidy_mpd/protocol/current_playlist.py の `plchangesposid {VERSION}` が、渡された
# VERSION が現在の tracklist version より「大きい」(=クライアントが認識しているより
# 未来の、まだ実際には割り振られていないバージョン) 場合にも「キュー全曲が変更された」
# として全件返してしまう不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# mopidy_mpd 本体を再調査して新規発見した項目。
#
# 兄弟コマンド `plchanges {VERSION}` (同ファイル、こちらは mpdcurrentsongrace-patch.py で
# TOCTOUレース修正済みだが分岐構造自体は元のまま) は明確に3分岐している:
#     if version < tracklist_version:      # 過去のバージョン → 全曲を「変更」として返す
#     elif version == tracklist_version:    # 現在のバージョン → メタデータ更新のみチェック
#     else:                                 # 未来のバージョン → 何も返さない (変更なし)
# 一方 `plchangesposid` は元々 `if int(version) != context.core.tracklist.get_version().get():`
# という `!=` 一発の判定しか無く、"未来のバージョン" (version > tracklist_version) も
# この条件を満たしてしまうため、`plchanges` なら空応答になるのと全く同じ入力に対して
# `plchangesposid` はキュー全曲の cpos/Id を返す。同じ「XXX Naive implementation」を
# 名乗る兄弟コマンド同士で応答が矛盾しているだけでなく、実 MPD 本体 (GitHub
# MusicPlayerDaemon/MPD の queue/Print.cxx 等、曲ごとの実更新バージョンとの比較で
# 未来バージョン入力に対しては常に「変更なし」を返す実装) の挙動とも異なる。
#
# rmpc 等のクライアントが `plchangesposid` に自身が最後に見た version を渡す運用では
# 通常発生しないが、MPD 仕様上 VERSION に任意の値を渡すこと自体は許容されており
# (musicpd.org protocol、型は unsigned なので decorator の protocol.INT で ACK
# incorrect arguments になるのは非数値のみ)、再接続直後にキャッシュした古いversionを
# 使い回すクライアントや、サーバ再起動でversionがリセットされた後に大きい値を送る
# クライアント等では現実に未来のバージョンが送られうる。
#
# 修正方針: plchanges と同じ「version < tracklist_version のときのみ全曲を返す」判定に
# 揃える (plchangesposid には plchanges のメタデータ更新分岐に相当する概念が無いため、
# version == / > tracklist_version はどちらも「変更なし」で統一)。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "# XXX Naive implementation that returns all changed song ids"
if MARKER in s:
    print("plchangesposid future-version already patched, skip")
else:
    old_plchangesposid = (
        "    # XXX Naive implementation that returns all tracks as changed\n"
        "    if int(version) != context.core.tracklist.get_version().get():\n"
        "        result = []\n"
        "        for (position, (tlid, _)) in enumerate(\n"
        "            context.core.tracklist.get_tl_tracks().get()\n"
        "        ):\n"
        "            result.append((\"cpos\", position))\n"
        "            result.append((\"Id\", tlid))\n"
        "        return result\n"
    )
    assert s.count(old_plchangesposid) == 1, (
        f"old_plchangesposid count={s.count(old_plchangesposid)}"
    )
    new_plchangesposid = (
        "    # XXX Naive implementation that returns all changed song ids\n"
        "    # version > tracklist_version (未来のバージョン) は「変更なし」を意味すべき\n"
        "    # ところ、元実装は `!=` 判定のため全曲を「変更」として返してしまっていた\n"
        "    # (兄弟コマンドplchangesのversion<tracklist_version分岐とだけ揃える)。\n"
        "    if int(version) < context.core.tracklist.get_version().get():\n"
        "        result = []\n"
        "        for (position, (tlid, _)) in enumerate(\n"
        "            context.core.tracklist.get_tl_tracks().get()\n"
        "        ):\n"
        "            result.append((\"cpos\", position))\n"
        "            result.append((\"Id\", tlid))\n"
        "        return result\n"
    )
    s = s.replace(old_plchangesposid, new_plchangesposid, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: plchangesposidが未来のVERSION(現在のtracklist "
        "versionより大きい値)を渡された場合にも全曲を「変更」として返してしまう不具合を "
        "修正 (plchangesと同じversion<tracklist_versionの判定に統一)"
    )
