# mopidy_mpd/protocol/current_playlist.py の raw position 版 `swap` (mpdmoveswaprace-patch.py
# が「範囲外指定でサイレントにOKを返す」不具合を修正済みだが、その内部アルゴリズム自体に
# 残っていた別のTOCTOUレース。同時実行下で無関係な曲を巻き込みキュー順序を静かに破損する。
#
# 現在の実装は songpos1 < songpos2 として
#   context.core.tracklist.move(songpos1, songpos1 + 1, songpos2).get()       # move1
#   context.core.tracklist.move(songpos2 - 1, songpos2, songpos1).get()       # move2
# という2回の別々の core 呼び出し (それぞれ pykka Future への .get() で session スレッドが
# ブロックされる) で構成されている。move1 は songpos1 の曲を songpos2 へ移動する副作用として、
# 元々 songpos2 にいた曲を1つ左 (songpos2 - 1) へ押し出す。move2 はその「songpos2 - 1 に
# 今いる曲」を一切確認せず無条件に songpos1 へ戻すことで swap を完成させている——つまり
# move2 は「元々 songpos2 にあった曲」を直接参照しておらず、「move1 の後に songpos2 - 1
# という座標に何があるか」という構造的な副産物にのみ依存している。
#
# mopidy/core/tracklist.py の Tracklist.move() は起点/終点ともに純粋な position 指定で
# 動作し、曲の同一性は一切見ない (gh api repos/mopidy/mopidy で実装を確認済み: self._tl_tracks
# に対する単純な slice 除去+insert)。したがって move1 の .get() が返ってから move2 が実行
# されるまでの間に、別クライアントが delete/move/swap 等で songpos2 - 1 の座標の中身を
# 変えてしまうと、move2 は「元々 songpos2 にあった曲」ではなく「たまたまその時点で
# songpos2 - 1 にいた別の曲」を songpos1 へ動かしてしまう。ACK は一切出ず `OK` が返るため、
# クライアントはキューが破損したことに気づけない (prio の TOCTOU と同じ根本原因だが、
# こちらは接続断すら起きずサイレント破損である分よりたちが悪い)。
#
# rmpc (mierak/rmpc) を実際に gh api で確認したところ、rmpc/src/ui/panes/queue_header.rs の
# `sort_by_column()` (キュー列ヘッダをクリックしてソートする、既定で使える一般的な操作) が
# `calculate_swaps()` で求めた複数の (i, j) ペアを `send_start_cmd_list` → 複数回の
# `send_swap_position` (=生の `swap {i} {j}`, rmpc-mpd/src/mpd_client.rs 569-571行) →
# `send_execute_cmd_list` として一括送信する。`mopidy_mpd/protocol/command_list.py` の
# command_list はこれらを1つずつ順に `dispatcher.handle_request()` へ渡すだけで、各 `swap`
# 自体の2段階 .get() 構造はそのまま (バッチ化されても不可分にはならない)。つまり「キュー
# 列ヘッダをクリックしてソートする」という日常的な rmpc 操作中に、同時に接続した別クライ
# アント (別の rmpc インスタンス/デバイスや他の MPD クライアント) がキューを操作していると、
# このレースを踏んでソート結果が静かに破損しうる。
#
# mpdmoveidrace-patch.py は tlid 経由の moveid/swapid のレースを修正した際、コメントで
# 「move()/swap() 本体の呼び出しとの間のレースは mpdmoveswaprace-patch.py が既に
# AssertionError→ACK Bad song index で吸収済みのためスコープ外」としていたが、これは範囲外に
# 押し出されるケース (AssertionError) にしか当てはまらず、範囲内に留まる (=例外が起きない)
# 上記のサイレント破損ケースを見落としていたと判明した。
#
# 検討過程: 当初は move2 の起点を tlid 経由 (tracklist.index(tlid=...)) で move1 後に
# 都度再解決する案を実装したが、実機の2コネクションによる継続的競合ストレステスト
# (`swap` を連打するコネクションAに対し、A の範囲内側だが A の songpos1/songpos2 自体には
# 触れない `move` を連打するコネクションBを1秒間ぶつける、を15試行) で検証したところ、
# 修正前 15/15 中14/15 で破損、tlid案適用後も15/15中15/15で破損と有意な改善が見られな
# かった。原因を調査した結果、tlid 案は「move2 の対象曲の取り違え」という1つの具体的な
# 症状だけを塞ぐもので、move1 自体の起点 (songpos1、常に生 position 参照のまま) や
# 「resolve呼び出しとmove2呼び出しの間」に残る別の小さな窓は塞げておらず、B のような
# 常時飽和した対向トラフィックの下では結局その残存窓を即座に踏んでしまうことを確認した。
#
# 最終的な修正方針: mopidy/core/tracklist.py の version (`_increase_version()`、状態変化の
# たびに単調増加、巻き戻り無し) を使った楽観的排他制御に切り替えた。この file 自身の
# `plchanges`/`plchangesposid` (620行目/658行目) が既に「baseline version との比較で
# 他クライアントによる変更の有無を判定する」という同じ仕組みをコマンド応答の目的で使って
# おり、本パッチはこれを「swap の2回の move の間に割り込みが無かったことの検証」に転用した
# だけで、この mopidy_mpd 自体の既存の流儀に沿っている。手順: (1) 操作前の version を
# 記録、(2) move1 実行後に version が baseline+1 (=自分の move1 だけが起きた) と一致する
# ことを確認——一致しなければ songpos2 - 1 という前提そのものが崩れているため、破損した
# 状態を move2 でさらに悪化させる前に ACK Bad song index で打ち切る、(3) 一致していれば
# 従来通り move2 を実行し、その後 version が baseline+2 と一致することも確認する。
# version は自分自身の move() 呼び出し以外のどんな他クライアントの操作 (delete/add/move/
# shuffle/swap 等、無関係な位置への操作も含め) でも必ず単調増加するため、tlid 案のように
# 「songpos2 側だけ」を個別に守るのではなく、2回の move の間に自分以外の変更が一切無かった
# ことを直接的かつ網羅的に検証できる。これにより「別の曲を巻き込んでサイレントに OK を
# 返す」という最悪の症状 (実害の分からない破損) は解消され、割り込みを検知した場合は
# (queueの一部は既に move1 分だけ変化した状態のまま) ACK Bad song index を返すに留まる。
# これは mpdmoveswaprace-patch.py が範囲外 move で既に許容している「一部だけ実行された
# 状態で ACK を返す」という既存の許容パターンと同じ水準であり、「黙って嘘の OK を返す」
# よりも常に望ましい。なお move1 実行前 (version 取得と move1 実行の間) や、move2 実行前
# (version確認とmove2実行の間) にも原理上ごく短い残存窓はあり、飽和した敵対的トラフィック
# 下ではそれすら踏まれうる (実機ストレステストで確認済み) が、これは「2回の別々の core
# 呼び出しに分解される」という mopidy-mpd の設計そのものに起因し、mopidy core 自体を
# 変更しない限り完全には閉じられないため、prio/moveid/swapid など既存パッチが同種の
# 残存リスクを許容範囲として明記しているのと同じ扱いとする。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "version + 1"
if MARKER in s:
    print("swap version-race already patched, skip")
else:
    old_swap = (
        "    length = context.core.tracklist.get_length().get()\n"
        "    if songpos1 >= length or songpos2 >= length:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "    if songpos1 == songpos2:\n"
        "        return\n"
        "    if songpos2 < songpos1:\n"
        "        songpos1, songpos2 = songpos2, songpos1\n"
        "    try:\n"
        "        context.core.tracklist.move(songpos1, songpos1 + 1, songpos2).get()\n"
        "        context.core.tracklist.move(songpos2 - 1, songpos2, songpos1).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(old_swap) == 1, f"old_swap count={s.count(old_swap)}"
    new_swap = (
        "    length = context.core.tracklist.get_length().get()\n"
        "    if songpos1 >= length or songpos2 >= length:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "    if songpos1 == songpos2:\n"
        "        return\n"
        "    if songpos2 < songpos1:\n"
        "        songpos1, songpos2 = songpos2, songpos1\n"
        "    version = context.core.tracklist.get_version().get()\n"
        "    try:\n"
        "        context.core.tracklist.move(songpos1, songpos1 + 1, songpos2).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        context.core.tracklist.move(songpos2 - 1, songpos2, songpos1).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 2:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_swap, new_swap, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: swap()の2回のmove間に他クライアントの操作が"
        "割り込んでも検知されずsongpos2-1という座標を無条件参照し無関係な曲を巻き込んで"
        "サイレントにキュー順序破損する不具合を修正 (tracklist.version の楽観的排他制御で"
        "割り込みを検知しACK Bad song indexへ変換)"
    )
