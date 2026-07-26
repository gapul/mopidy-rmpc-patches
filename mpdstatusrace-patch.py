# mopidy_mpd/protocol/status.py の `status` コマンド本体 (currentsong とは別関数) に
# 残っていた、mpdcurrentsongrace-patch.py が currentsong/playlistid/plchanges に対して
# 修正したのと全く同型の TOCTOU レース。自走エージェントが TODO/既知の残課題を全項目
# 消化済みのため mopidy_mpd のコード品質を再調査して発見した項目。
#
# `status()` は以下の2組で、それぞれ「曲/tlidを取得する core 呼び出し」と「その位置を
# 求める tracklist.index() の core 呼び出し」が別々の pykka actor 往復に分かれている:
#   - `tl_track = core.playback.get_current_tl_track()` → `tracklist.index(tl_track.get())`
#   - `next_tlid = core.tracklist.get_next_tlid()` → `tracklist.index(tlid=next_tlid.get())`
# `mopidy/core/tracklist.py` の `index()` は対象の tl_track/tlid がもはやキューに
# 存在しなければ `ValueError` を握り潰して `None` を返す実装 (currentsong 修正時に
# 確認済みの実装と同一)。呼び出し1と呼び出し2の間隙で別クライアントが `delete`/`clear`
# 等により対象曲をキューから外すと `position`/`next_index` が `None` になる。
#
# `currentsong` 等と違い `status()` の `song`/`nextsong` は `translator.track_to_mpd_format()`
# の `position is not None` ガードを経由せず、`_status_songpos()`/`_status_nextsongpos()` が
# `futures["tracklist.index"].get()`/`futures["tracklist.next_index"].get()` を無条件に
# そのまま返し、`dispatcher.py` の `_format_lines()` が `f"{key}: {value}"` で無検証に
# 文字列化するため、ACK もクラッシュも無く `song: None`/`nextsong: None` という
# musicpd.org 仕様 (both are integers) に反する応答がそのまま返る実害がある
# (`songid`/`nextsongid` は `current_tl_track.tlid`/`next_tlid` から直接得るためこのレースの
# 影響を受けない)。rmpc (mierak/rmpc) は player idle wakeup のたびに `status`+`currentsong`
# を command_list で送るため、この応答不正がクライアント側のパース/曲同定ロジックへ
# 伝播しうる。
#
# 修正方針: mpdcurrentsongrace-patch.py が確立した「呼び出し前後で tracklist.version が
# 不変なことを確認し、割り込みがあれば取り直す (bounded retry)」を転用。status() は
# 元々 futures 辞書 + pykka.get_all() で多数の core 呼び出しをまとめて解決する構造のため、
# tl_track/position/next_tlid/next_index の4値だけ先にレース対策込みで解決し、
# pykka.ThreadingFuture().set() で「既に解決済みの future」として同じ futures 辞書の
# 枠組みに乗せる (既存の _status_songpos() 等の呼び出し側を変更せずに済む)。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER = "_resolved_future"
if MARKER in s:
    print("status race already patched, skip")
else:
    old_helper_anchor = (
        "_TRACKLIST_SNAPSHOT_RETRIES = 5\n"
        "\n"
        "#: Subsystems that can be registered with idle command.\n"
    )
    assert s.count(old_helper_anchor) == 1, (
        f"old_helper_anchor count={s.count(old_helper_anchor)} "
        "(mpdcurrentsongrace-patch.py が先に status.py へ適用されている前提)"
    )
    new_helper_anchor = (
        "_TRACKLIST_SNAPSHOT_RETRIES = 5\n"
        "\n"
        "\n"
        "def _resolved_future(value):\n"
        "    # status() が get_current_tl_track()/get_next_tlid() と対応する\n"
        "    # tracklist.index() の間のTOCTOUレース対策で先に解決してしまった値を、\n"
        "    # 既存の futures 辞書 + pykka.get_all() の枠組みにそのまま乗せるための\n"
        "    # 軽量ラッパー (pykka.Future と同じ .get() インタフェースを持つ)。\n"
        "    future = pykka.ThreadingFuture()\n"
        "    future.set(value)\n"
        "    return future\n"
        "\n"
        "\n"
        "#: Subsystems that can be registered with idle command.\n"
    )
    s = s.replace(old_helper_anchor, new_helper_anchor, 1)

    old_status_body = (
        "    tl_track = context.core.playback.get_current_tl_track()\n"
        "    next_tlid = context.core.tracklist.get_next_tlid()\n"
        "\n"
        "    futures = {\n"
        "        \"tracklist.length\": context.core.tracklist.get_length(),\n"
        "        \"tracklist.version\": context.core.tracklist.get_version(),\n"
        "        \"mixer.volume\": context.core.mixer.get_volume(),\n"
        "        \"tracklist.consume\": context.core.tracklist.get_consume(),\n"
        "        \"tracklist.random\": context.core.tracklist.get_random(),\n"
        "        \"tracklist.repeat\": context.core.tracklist.get_repeat(),\n"
        "        \"tracklist.single\": context.core.tracklist.get_single(),\n"
        "        \"playback.state\": context.core.playback.get_state(),\n"
        "        \"playback.current_tl_track\": tl_track,\n"
        "        \"tracklist.index\": context.core.tracklist.index(tl_track.get()),\n"
        "        \"tracklist.next_tlid\": next_tlid,\n"
        "        \"tracklist.next_index\": context.core.tracklist.index(\n"
        "            tlid=next_tlid.get()\n"
        "        ),\n"
        "        \"playback.time_position\": context.core.playback.get_time_position(),\n"
        "    }\n"
        "    pykka.get_all(futures.values())\n"
    )
    assert s.count(old_status_body) == 1, f"old_status_body count={s.count(old_status_body)}"
    new_status_body = (
        "    # get_current_tl_track()/get_next_tlid() と、対応する tracklist.index() は\n"
        "    # 別々のcore呼び出しで、間に他クライアントのdelete/clear等が割り込むと\n"
        "    # index()がValueErrorを握り潰しNoneを返し、仕様上整数のはずのsong/nextsongが\n"
        "    # サイレントに`None`のまま応答されてしまう(currentsong/playlistid/plchanges\n"
        "    # と同根のTOCTOU、mpdcurrentsongrace-patch.py参照)。versionが前後で不変な\n"
        "    # ことを確認し、割り込みがあれば取り直す。\n"
        "    tl_track = None\n"
        "    position = None\n"
        "    next_tlid = None\n"
        "    next_index = None\n"
        "    for _ in range(_TRACKLIST_SNAPSHOT_RETRIES):\n"
        "        version = context.core.tracklist.get_version().get()\n"
        "        tl_track = context.core.playback.get_current_tl_track().get()\n"
        "        next_tlid = context.core.tracklist.get_next_tlid().get()\n"
        "        position = (\n"
        "            context.core.tracklist.index(tl_track).get()\n"
        "            if tl_track is not None\n"
        "            else None\n"
        "        )\n"
        "        next_index = (\n"
        "            context.core.tracklist.index(tlid=next_tlid).get()\n"
        "            if next_tlid is not None\n"
        "            else None\n"
        "        )\n"
        "        if context.core.tracklist.get_version().get() == version:\n"
        "            break\n"
        "\n"
        "    futures = {\n"
        "        \"tracklist.length\": context.core.tracklist.get_length(),\n"
        "        \"tracklist.version\": context.core.tracklist.get_version(),\n"
        "        \"mixer.volume\": context.core.mixer.get_volume(),\n"
        "        \"tracklist.consume\": context.core.tracklist.get_consume(),\n"
        "        \"tracklist.random\": context.core.tracklist.get_random(),\n"
        "        \"tracklist.repeat\": context.core.tracklist.get_repeat(),\n"
        "        \"tracklist.single\": context.core.tracklist.get_single(),\n"
        "        \"playback.state\": context.core.playback.get_state(),\n"
        "        \"playback.current_tl_track\": _resolved_future(tl_track),\n"
        "        \"tracklist.index\": _resolved_future(position),\n"
        "        \"tracklist.next_tlid\": _resolved_future(next_tlid),\n"
        "        \"tracklist.next_index\": _resolved_future(next_index),\n"
        "        \"playback.time_position\": context.core.playback.get_time_position(),\n"
        "    }\n"
        "    pykka.get_all(futures.values())\n"
    )
    s = s.replace(old_status_body, new_status_body, 1)

    open(sp, "w").write(s)
    print(
        "patched status.py: statusのget_current_tl_track()/get_next_tlid()と対応する"
        "tracklist.index()間のTOCTOUレースでsong/nextsongがサイレントにNoneのまま"
        "応答されてしまう不具合を修正 (tracklist.versionの楽観的排他制御でbounded retry)"
    )
