# `previous`が`repeat "1"`(かつ`random "0"`)の時、常に現在曲を返すだけで
# 一つ前の曲へ戻らない不具合(`consume`単体でも同様に誤って現在曲を返す)。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェント
# への調査委任を経て)新規発見。
#
# mopidy_mpd自身のdocstring(playback.pyの`previous()`に埋め込まれた実MPD
# 0.15.4での実測テーブル)が既に「repeat=T かつ random=. の全行(single/
# consume問わず)はc=1,2,3→3,1,2(前の曲へ、先頭なら末尾へラップ)」「repeat=.
# かつ random=. の全行(single/consume問わず)はc=1,2,3→1,1,2(前の曲へ、
# 先頭なら現在曲を再スタート)」と明記しているにも関わらず、実装
# (`mopidy/core/tracklist.py`の`previous_track()`)は
#   if self.get_repeat() or self.get_consume() or self.get_random():
#       return tl_track
# と、repeat/consume/randomのいずれか一つでもTrueなら無条件で現在曲を
# 返してしまう。実MPD本体(gh rawでsrc/queue/PlaylistControl.cxx
# playlist::PlayPrevious()を確認)は
#   if (current > 0) order = current - 1;
#   else if (queue.repeat) order = queue.GetLength() - 1;
#   else order = current;
# であり、single/consumeは一切参照せず、randomはこの関数自体には現れない
# (シャッフル順序は別途queueのorder配列側で吸収される)。
#
# 修正範囲: `random`が無効な場合のみ、上記の実MPDのアルゴリズムをplayback.py
# 側で直接計算し`context.core.playback.play(tl_track)`で反映する
# (mpdplayneg-patch.pyで既に確立済みの、tracklistから曲を取得してplay()へ
# 渡すパターンを踏襲)。`random`有効時は複雑なシャッフル順序状態への依存が
# 必要になり単発修正のリスクが高いため、既存の(repeat=T,random=T,consume=T
# ではdocstring自身も"Rand?"と実測結果が曖昧であることを認めている)
# 現在曲を返す挙動のまま変更しない。oneshot(single/consume)のrevert機構
# (mpdoneshotmanualskip-patch.py)が使う`mark_pending_manual_track_change`は
# 分岐前と同じタイミングで呼び続ける。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    "    current_tl_track = context.core.playback.get_current_tl_track().get()\n"
    "    if current_tl_track is not None:\n"
    '        translator.mark_pending_manual_track_change("previous")\n'
    "    if current_tl_track is not None and not context.core.tracklist.get_random().get():\n"
    "        tl_tracks = context.core.tracklist.get_tl_tracks().get()\n"
    "        position = context.core.tracklist.index(current_tl_track).get()\n"
    "        if position is not None and tl_tracks:\n"
    "            if position > 0:\n"
    "                new_position = position - 1\n"
    "            elif context.core.tracklist.get_repeat().get():\n"
    "                new_position = len(tl_tracks) - 1\n"
    "            else:\n"
    "                new_position = position\n"
    "            return context.core.playback.play(tl_tracks[new_position]).get()\n"
    "    return context.core.playback.previous().get()\n"
)

if NEW in s:
    print("previous() repeat/consume fix already patched, skip")
else:
    OLD = (
        "    if context.core.playback.get_current_tl_track().get() is not None:\n"
        '        translator.mark_pending_manual_track_change("previous")\n'
        "    return context.core.playback.previous().get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: previous()がrepeat/consume有効時(random無効)"
        "常に現在曲を返してしまい前の曲へ戻らない不具合を修正"
    )
