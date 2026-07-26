# mopidy_mpd/protocol/current_playlist.py の `swapid` (tlid経由のswap) に残っていた
# TOCTOUレース。mpdmoveidrace-patch.py は tlid->position 解決を filter()+index() の2段階
# から index(tlid=...) の単一core呼び出しへ集約し「削除競合でposition=NoneとなりTypeError
# で接続断する」不具合を修正したが、swapid はその解決自体が
#   position1 = context.core.tracklist.index(tlid=tlid1).get()  # 呼び出し1
#   position2 = context.core.tracklist.index(tlid=tlid2).get()  # 呼び出し2
# という2回の別々のcore呼び出しのままだった (moveidは対象が1曲だけなのでこの問題が
# そもそも存在しない)。mpdmoveidrace-patch.py のコメントは「move()/swap()本体の呼び出し
# との間のレースは mpdmoveswaprace-patch.py が既にAssertionError→ACK Bad song indexで
# 吸収済みのためスコープ外」としていたが、これは position1/position2 が範囲外へ
# ずれて例外化するケースにしか当てはまらない。範囲内に留まったまま曲の対応関係だけが
# ずれるケース——呼び出し1と呼び出し2の間に別クライアントが move/swap 等でキューの
# 並びを変えると、position2 (あるいはposition1) がもはや tlid2 (tlid1) を指さない
# まま有効な範囲内indexとして解決されてしまう——は見落とされていた。この後 swapid は
# それらをそのまま `swap(context, position1, position2)` へ渡し、swap() 自身は自分の
# 呼び出し直前に取得したversionを基準に2回のmove間の割り込みしか検知しない
# (mpdswapstalepos-patch.py) ため、position1/position2 の解決自体が既に古い場合は
# 一切検知されず、無関係な曲同士をサイレントに入れ替えてOKを返してしまう
# (prio/move/moveidのTOCTOUレース群と同じ根本原因で、しかも接続断すら起きない分
# クライアントが破損に気付く手がかりが無い)。
#
# 修正: plchanges/plchangesposid (620行目/658行目) や mpdswapstalepos-patch.py/
# mpdmovetorace-patch.py と同じ tracklist.version による楽観的排他制御を、
# 「呼び出し1と呼び出し2の間に割り込みが無かったことの検証」に適用する。手順:
# (1) 呼び出し1の前に version を記録、(2) 呼び出し1・呼び出し2を実行、(3) 直後に
# version が変化していないか確認——変化していれば position1/position2 の対応関係が
# 崩れている可能性があるため、swap() 本体を呼ぶ前に ACK Bad song index で打ち切る、
# (4) 変化が無ければ従来通り swap() へ委譲する (swap()自身の内部レース対策はそのまま
# 活きる)。version は他クライアントのどんな操作 (delete/add/move/shuffle/swap等) でも
# 必ず単調増加するため、両呼び出しの間に何も起きなかったことを直接検証できる。
# なお version確認とswap()呼び出しの間にも原理上ごく短い残存窓はあるが、これは
# mpdswapstalepos-patch.py等が既に明記している「2回の別々のcore呼び出しに分解される」
# という設計自体に起因する許容範囲内の残存リスクであり、本パッチのスコープ外とする。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "if context.core.tracklist.get_version().get() != version:\n        raise exceptions.MpdArgError(\"Bad song index\")\n    swap(context, position1, position2)"
if MARKER in s:
    print("swapid resolve-race already patched, skip")
else:
    old_swapid = (
        "    position1 = context.core.tracklist.index(tlid=tlid1).get()\n"
        "    position2 = context.core.tracklist.index(tlid=tlid2).get()\n"
        "    if position1 is None or position2 is None:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    swap(context, position1, position2)\n"
    )
    assert s.count(old_swapid) == 1, f"old_swapid count={s.count(old_swapid)}"
    new_swapid = (
        "    version = context.core.tracklist.get_version().get()\n"
        "    position1 = context.core.tracklist.index(tlid=tlid1).get()\n"
        "    position2 = context.core.tracklist.index(tlid=tlid2).get()\n"
        "    if position1 is None or position2 is None:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    if context.core.tracklist.get_version().get() != version:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "    swap(context, position1, position2)\n"
    )
    s = s.replace(old_swapid, new_swapid, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: swapidのtlid->position解決が呼び出し1(tlid1)と"
        "呼び出し2(tlid2)の間の他クライアント割り込みを検知できず対応関係のずれた"
        "positionをswap()へ渡しサイレントにキュー順序破損する不具合を修正"
    )
