# mpdfindaddpos-patch.py の findadd/searchadd POSITION 実装に、mpdaddloadrace-patch.py が
# add/load で修正したのと同種の TOCTOU レースが残っている。加えて add/load の旧実装より
# 悪い点として、tracklist.move() の戻り値 (pykka Future) に一度も .get() を呼んでいない
# ため、mpdmoveswaprace-patch.py が move/shuffle/swap で修正したのと同じ「AssertionError が
# _catch_mpd_ack_errors_filter にも引っかからず握り潰される」不具合が、範囲外 position 指定
# だけでなく通常のレース条件でも発生しうる。
#
# rmpc 本体 (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc/src/shared/mpd_client_ext.rs の enqueue_multiple が
# Position::AfterCurrentSong/BeforeCurrentSong から QueuePosition::RelativeAdd(0)/
# RelativeSub(0) を生成し、検索結果ペインでの「現在の曲の次/前に追加」操作 (日常的に使う
# 操作) で send_find_add 経由 findadd "(FILTER)" position "+0" を実際に送信する
# (mpdfindaddpos-patch.py 自身のコメントで既に確認済みの到達経路と同一)。
#
# addid (mpdaddid-patch.py) や、修正後の add/load (mpdaddloadrace-patch.py) は
# 解決済みの position を tracklist.add(uris=..., at_position=position) として1回の
# atomic core 呼び出しに渡すだけでこの問題を回避している。findadd/searchadd も同じ
# 流儀に統一する。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "at_position=position"
if MARKER in s:
    print("findadd/searchadd race already patched, skip")
else:
    old_block = (
        "    old_size = context.core.tracklist.get_length().get()\n"
        "    position = None\n"
        "    if _position is not None:\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks]\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
        "\n"
        "    if tracks and position is not None and position < old_size:\n"
        "        new_size = context.core.tracklist.get_length().get()\n"
        "        context.core.tracklist.move(old_size, new_size, position)\n"
    )
    assert s.count(old_block) == 2, f"old_block count={s.count(old_block)}"

    new_block = (
        "    position = None\n"
        "    if _position is not None:\n"
        "        old_size = context.core.tracklist.get_length().get()\n"
        "        position = _mpd_resolve_addpos_position(context, _position, old_size)\n"
        "\n"
        "    new_tl_tracks = context.core.tracklist.add(\n"
        "        uris=[track.uri for track in tracks], at_position=position\n"
        "    ).get()\n"
        "    translator.stamp_added([tl_track.tlid for tl_track in new_tl_tracks])\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block)
    assert s.count(new_block) == 2, f"new_block count={s.count(new_block)}"

    open(p, "w").write(s)
    print(
        "patched music_db.py: findadd/searchadd の POSITION 解決を at_position "
        "直接指定に変更 (末尾追加+moveのTOCTOUレース + move().get()未呼び出しを解消)"
    )
