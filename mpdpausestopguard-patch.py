# mopidy_mpd/protocol/playback.py の `pause {PAUSE}` (明示引数版) が、
# 現在の再生状態を一切確認せず停止中(STOP)でも強制的に一時停止状態へ
# 遷移させてしまう不具合。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体 (gh rawで src/command/PlayerCommands.cxx handle_pause() と
# src/player/Control.cxx PlayerControl::LockSetPause() を確認) は
#   switch (state) {
#   case PlayerState::STOP:   break;                       // 常に無視
#   case PlayerState::PLAY:   if (pause_flag) Pause();      break;
#   case PlayerState::PAUSE:  if (!pause_flag) Pause();     break;
#   }
# という3状態switchで、STOP中は `pause 0`/`pause 1` どちらを送っても
# 現在状態が一切変化しない (無条件の一時停止コマンドではなく、現在の
# 再生状態と整合する遷移のときだけ作用する)。
#
# mopidy_mpd の pause() は引数無し(トグル)分岐 (`state is None`) では
# `get_state()` を見てPLAYING/PAUSEDの時だけ動く既存の正しいガードが
# あるのに、明示引数分岐 (`elif state:`/`else:`) だけは現在状態を
# 一切見ず `context.core.playback.pause()`/`resume()` を無条件に呼ぶ
# (同一関数内の非対称)。さらにmopidy core本体
# (`mopidy/core/playback.py`のpause())もbackend呼び出しが成功する限り
# 現在状態を見ずに`set_state(PAUSED)`するため、二重に歯止めが無い。
#
# 実機確認(TCP 6601, mopidy-ytmusic実アカウント): `stop`後の`status`で
# `state: stop`を確認した直後に`pause "1"`を送ると`state: pause`へ
# 遷移してしまう(本来は`state: stop`のまま不変であるべき)ことを確認。
#
# 修正: 引数無し分岐と同じ`get_state()`判定を明示引数分岐にも適用し、
# `pause "1"`はPLAYING中のみ、`pause "0"`はPAUSED中のみ実際にcoreを
# 呼ぶよう統一する(STOP中はどちらも何もしない、実MPDのswitchと同じ
# 3状態の遷移条件を再現)。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    "    if state is None:\n"
    "        # Deprecated: Calling `pause` without any arguments\n"
    "        playback_state = context.core.playback.get_state().get()\n"
    "        if playback_state == PlaybackState.PLAYING:\n"
    "            context.core.playback.pause().get()\n"
    "        elif playback_state == PlaybackState.PAUSED:\n"
    "            context.core.playback.resume().get()\n"
    "    elif state:\n"
    "        # 実MPDのLockSetPause()同様、STOP中は明示引数でも無視する\n"
    "        if context.core.playback.get_state().get() == PlaybackState.PLAYING:\n"
    "            context.core.playback.pause().get()\n"
    "    else:\n"
    "        if context.core.playback.get_state().get() == PlaybackState.PAUSED:\n"
    "            context.core.playback.resume().get()\n"
)

if NEW in s:
    print("pause() stop-guard already patched, skip")
else:
    OLD = (
        "    if state is None:\n"
        "        # Deprecated: Calling `pause` without any arguments\n"
        "        playback_state = context.core.playback.get_state().get()\n"
        "        if playback_state == PlaybackState.PLAYING:\n"
        "            context.core.playback.pause().get()\n"
        "        elif playback_state == PlaybackState.PAUSED:\n"
        "            context.core.playback.resume().get()\n"
        "    elif state:\n"
        "        context.core.playback.pause().get()\n"
        "    else:\n"
        "        context.core.playback.resume().get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: pause()の明示引数分岐がSTOP中でも無条件に"
        "PAUSEDへ遷移させてしまう不具合を修正 (get_state()判定を追加)"
    )
