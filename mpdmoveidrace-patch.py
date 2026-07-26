# mopidy_mpd/protocol/current_playlist.py の `moveid`/`swapid` (tlid経由の
# 系統) に残っていたTOCTOUレース。mpdmoveswaprace-patch.py は raw position/range
# 系統 (move/shuffle/swap) の「範囲外指定がサイレントにOKを返す」不具合を修正した
# 際、その docstring コメントで「moveid/swapidはtlid経由で常に実在する位置しか
# 渡らないため元々無害」と結論していたが、これは同時実行下では誤りだった。
#
# 原因: moveid/swapid は tlid→position の解決を
#   tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()  # 呼び出し1
#   position  = context.core.tracklist.index(tl_tracks[0]).get()       # 呼び出し2
# という2段階の別々の core 呼び出しで行っている (prio/add/load/findadd で既に
# 修正済みの「別呼び出し間に他クライアントが操作するとスナップショットが古くなる」
# のと同じ形)。mopidy/core/tracklist.py の `index(tl_track)` は、渡された
# TlTrack が現在のtracklistに存在しなければ ValueError を握り潰して `None` を
# 返す実装 (`_tl_tracks.index(tl_track)` の except ValueError: pass の後 `return
# None`)。つまり呼び出し1と呼び出し2の間に別クライアントが `deleteid`/`delete`/
# `clear` 等で当該 tlid をキューから除去すると、`position` が `None` になる。
# moveid はその直後 `position + 1` を計算し、swapid は `swap(context, position1,
# position2)` (内部で `songpos1 >= length` を評価) するため、いずれも
# `TypeError: unsupported operand type(s)` が発生する。この例外は
# `exceptions.MpdAckError` ではないため `dispatcher._catch_mpd_ack_errors_filter`
# に捕捉されず、`mopidy_mpd/session.py` の `on_line_received` (pykka アクターの
# メッセージ処理内) まで伝播して MPD セッションが切断される (prio の
# `IndexError`・findadd/searchadd や add/load の位置解決レースと同種の実害)。
# rmpc (mierak/rmpc) は prio/prioid を一切送信しない一方 moveid/swapid は実際に
# 送信する (mpdprio-patch.py のコメントで既に確認済み)。
#
# 修正: `filter()`→`index(tl_track)` の2段階を、mopidy core が用意する
# `tracklist.index(tlid=...)` (tlid直接指定、1回のcore呼び出しで完結しfilter不要)
# へ置き換え、`None` を明示チェックして `ACK No such song` へ変換する
# (delete()/prio() 等と同じ「範囲外はACKで返す」流儀)。1回の core 呼び出しに
# 集約するため、呼び出し1-2間の TOCTOU ウィンドウ自体が消滅する。move()/swap()
# 本体の呼び出しとの間のレース (position解決後にさらに他クライアントが操作する
# ケース) は mpdmoveswaprace-patch.py が既に AssertionError→ACK Bad song index で
# 吸収済みのため、本パッチのスコープ外 (既存の許容レベルのまま)。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "context.core.tracklist.index(tlid=tlid).get()"
if MARKER in s:
    print("moveid/swapid race already patched, skip")
else:
    # moveid
    old_moveid = (
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    try:\n"
        "        context.core.tracklist.move(position, position + 1, to_position).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(old_moveid) == 1, f"old_moveid count={s.count(old_moveid)}"
    new_moveid = (
        "    position = context.core.tracklist.index(tlid=tlid).get()\n"
        "    if position is None:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    try:\n"
        "        context.core.tracklist.move(position, position + 1, to_position).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_moveid, new_moveid, 1)

    # swapid
    old_swapid = (
        '    tl_tracks1 = context.core.tracklist.filter({"tlid": [tlid1]}).get()\n'
        '    tl_tracks2 = context.core.tracklist.filter({"tlid": [tlid2]}).get()\n'
        "    if not tl_tracks1 or not tl_tracks2:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position1 = context.core.tracklist.index(tl_tracks1[0]).get()\n"
        "    position2 = context.core.tracklist.index(tl_tracks2[0]).get()\n"
        "    swap(context, position1, position2)\n"
    )
    assert s.count(old_swapid) == 1, f"old_swapid count={s.count(old_swapid)}"
    new_swapid = (
        "    position1 = context.core.tracklist.index(tlid=tlid1).get()\n"
        "    position2 = context.core.tracklist.index(tlid=tlid2).get()\n"
        "    if position1 is None or position2 is None:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    swap(context, position1, position2)\n"
    )
    s = s.replace(old_swapid, new_swapid, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: moveid/swapidのtlid->position解決に残っていた"
        "TOCTOUレース(削除競合でposition=NoneとなりTypeErrorでセッション切断)を修正"
    )
