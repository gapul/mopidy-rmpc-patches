# mpdoneshotmanualskip-patch.py が導入した「next/previous 由来フラグ」機構の
# 残存エッジケース (該当パッチ自身の申し送り事項として BACKLOG.md に明記済み) を修正。
#
# next_()/previous() (playback.py) は現在再生中トラックの有無を一切確認せず、
# コマンドを受けた時点で無条件に translator.mark_pending_manual_track_change() で
# フラグを立てる。しかし mopidy core (`mopidy/core/playback.py` の `next()`/
# `previous()`) は `current = self._pending_tl_track or self._current_tl_track`
# が None (完全停止中/未再生状態) の場合 while ループが一度も回らず `_change()` が
# 呼ばれない — `_change()` だけが `_on_stream_changed`/`_on_end_of_stream` 経由で
# `track_playback_ended` を発火させるため、この場合 next/previous は実質何もせず
# イベントも発火しない。
#
# 結果、この状態で next/previous を送るとフラグが立ったまま pop されず、次の
# 全く無関係な自然終了時の `_revert_oneshot()` (actor.py) 呼び出しでフラグが誤って
# 消費され、`single "oneshot"` の revert を1回だけ誤って抑制してしまう
# (mpdoneshotmanualskip-patch.py の "previous"/"next" 分岐に誤爆する)。
#
# 修正: next_()/previous() で `context.core.playback.get_current_tl_track().get()`
# (mopidy_mpd の他コマンド (status.py/current_playlist.py) が現在トラック有無の
# 判定に使っているのと同じ既存パターン) が None でない場合のみフラグを立てる。
# mopidy core 側の `current` 判定とほぼ同じ条件になり、`_change()` が呼ばれない
# ケースではそもそもフラグを立てなくなる。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "get_current_tl_track().get() is not None:\n        translator.mark_pending_manual_track_change"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_next = (
        '    """\n'
        '    translator.mark_pending_manual_track_change("next")\n'
        "    return context.core.playback.next().get()\n"
    )
    assert s.count(old_next) == 1, f"old_next count={s.count(old_next)}"
    new_next = (
        '    """\n'
        "    if context.core.playback.get_current_tl_track().get() is not None:\n"
        '        translator.mark_pending_manual_track_change("next")\n'
        "    return context.core.playback.next().get()\n"
    )
    s = s.replace(old_next, new_next, 1)

    old_previous = (
        '    """\n'
        '    translator.mark_pending_manual_track_change("previous")\n'
        "    return context.core.playback.previous().get()\n"
    )
    assert s.count(old_previous) == 1, f"old_previous count={s.count(old_previous)}"
    new_previous = (
        '    """\n'
        "    if context.core.playback.get_current_tl_track().get() is not None:\n"
        '        translator.mark_pending_manual_track_change("previous")\n'
        "    return context.core.playback.previous().get()\n"
    )
    s = s.replace(old_previous, new_previous, 1)

    open(pp, "w").write(s)
    print(
        "patched playback.py: next/previous が現在トラック無しの時はフラグを"
        "立てないよう修正"
    )
