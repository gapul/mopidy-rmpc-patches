# mopidy_mpd/protocol/current_playlist.py の `move`/`moveid` の TO 相対指定
# (`+N`/`-N`、現在曲基準。mpdmoveto-patch.py が追加) を解決する
# `_mpd_resolve_move_to()` に残っていたTOCTOUレース。TODO/既知の軽微な残課題を
# 全項目消化済みのため自走エージェントがmopidy_mpdのコード品質を再調査して発見した項目。
#
# `_mpd_resolve_move_to()` は `context.core.tracklist.get_length().get()` と
# (相対TOの場合) `context.core.tracklist.index().get()` という2回の別々の
# core呼び出しで「現在曲のposition」を読み取り、そこから絶対 `to_position` を
# 確定する。呼び出し元の `move_range()`/`moveid()` はこの `to_position` を、
# さらに別の core呼び出しである `context.core.tracklist.move(start, end,
# to_position).get()` に渡して実行する。つまり「現在曲位置を読む」→
# 「moveを実行する」の間に、他クライアントの delete/move/swap 等が割り込める
# 窓が存在する。mopidy/core/tracklist.py の move() は start/end/to_position が
# 単なる範囲チェックを通れば無条件に実行され、「動かした曲が本当に意図した曲か」
# 「to_positionが本当に現在曲の直後/直前のままか」は一切検証しない
# (mpdswapstalepos-patch.py が確認済みの性質と同一)。
#
# 実機再現: dev mopidy に10曲(YOASOBI重複findaddで5曲x2)をキューし現在曲を
# position0で再生。別コネクションBに `swap 0 5` (current tlidの位置を0/5間で
# 往復させる、queue長は変えない) を隙間なく連打させながら、コネクションAで
# `move 9 +0` を80回実行したところ、"+0"の意味的な約束
# (=移動後の曲は必ず現在曲の直後、つまりcurrentが0/5のいずれにいてもposition
# 1/6のいずれかに来るはず) が、当初の実装 (resolve直後・move実行前にのみ
# version一致を確認する版) では OK 応答63件中52件 (82%) で破られる
# (現在曲と隣接しないposition、例:0,4,5,7等に着地) ことを実機ストレステストで
# 確認した。これは「resolve〜version確認」の窓は塞げていても、「version確認〜
# move()実際の呼び出し・core actorでの処理」の間に残る別の窓が、Bの隙間ない
# 連打(=core actorが常に混雑) の下ではほぼ確実に踏まれてしまうためと判明した。
#
# mpdmoveto-patch.py (`_mpd_resolve_move_to`の初出) は相対TOのパース・数式
# ロジックのみを追加し、この関数内部の2回の`.get()`と後続の`move()`との間の
# 競合には触れていない。mpdmoveswaprace-patch.py は範囲外POS/START:ENDに対する
# core側AssertionErrorの.get()漏れ(サイレントOK)のみを対象としており、範囲内に
# 留まる(=例外が起きない)本件のケースはそもそも対象外。mpdmoveidrace-patch.py は
# moveidのFROM側 (tlid->position) の2段階解決レースを修正したが、docstring自身が
# 「move()/swap()本体の呼び出しとの間のレースはmpdmoveswaprace-patch.pyの範囲」と
# 明記しており、TOの相対位置解決 (`_mpd_resolve_move_to`) は対象外。
# BACKLOG.md全文検索でも `_mpd_resolve_move_to` は初出の1箇所にしか登場せず、
# 後続のどの是正項目にも再訪されていないことを確認した。
#
# 修正方針: mpdswapstalepos-patch.py と同じ楽観的排他制御パターンを、同じ
# 「操作の前後でversionを比較する」形で適用する (操作前後の一致確認、では
# なく「操作直前」だけの確認だと上記の通り不十分と実機で判明したため)。
# resolve開始前に `version = tracklist.get_version().get()` を記録し、
# `move()` を実行した**後**に version が baseline+1 (=自分のmoveだけが
# 起きた) と一致するか確認する。不一致 (=resolve開始からmove完了までの
# 間のどこかに自分以外の変更が割り込んだ) ならACK Bad song indexへ変換する。
# これは mpdswapstalepos-patch.py の move1/move2それぞれの「実行後」チェックと
# 同型であり、「操作は既に実行された状態でACKを返す」という同パッチが
# 明記した許容パターンと同じ水準。version確認自体とcore actorでの実処理完了の
# 間にも原理上ごく短い窓は残るが、これは同パッチが明記した既知の残存リスクと
# 同じ扱いとして許容する。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "!= version + 1:\n            raise exceptions.MpdArgError(\"Bad song index\")\n    except AssertionError:\n        raise exceptions.MpdArgError(\"Bad song index\")\n\n\n@protocol.commands.add(\"moveid\""
if MARKER in s:
    print("move_range/moveid version-race already patched, skip")
else:
    old_move_range = (
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(old_move_range) == 1, f"old_move_range count={s.count(old_move_range)}"
    new_move_range = (
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    version = context.core.tracklist.get_version().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_move_range, new_move_range, 1)

    old_moveid = (
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
    assert s.count(old_moveid) == 1, f"old_moveid count={s.count(old_moveid)}"
    new_moveid = (
        "    version = context.core.tracklist.get_version().get()\n"
        "    position = context.core.tracklist.index(tlid=tlid).get()\n"
        "    if position is None:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    try:\n"
        "        context.core.tracklist.move(position, position + 1, to_position).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_moveid, new_moveid, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: move/moveidのTO相対指定(+N/-N)解決が"
        "現在曲位置read→move実行の間のTOCTOUレースで無関係な曲を巻き込み"
        "サイレントにキュー順序破損する不具合を修正 (tracklist.versionの"
        "楽観的排他制御で割り込みを検知しACK Bad song indexへ変換)"
    )
