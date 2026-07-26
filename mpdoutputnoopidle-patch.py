# enableoutput/disableoutput (mopidy_mpd/protocol/audio_output.py) が、要求された
# 有効/無効状態が現在の状態と既に同じ (no-op) の場合でも常に
# context.core.mixer.set_mute() を無条件に呼んでしまう不具合。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、raw curlでソース直接確認:
# src/output/OutputCommand.cxx) は:
#   void audio_output_enable_index(Partition &partition, unsigned idx) {
#       auto &ao = CheckPartitionOutput(partition, idx);
#       if (!ao.LockSetEnabled(true))
#           return;                       // 既に有効なら早期return、EmitIdle無し
#       partition.EmitIdle(IDLE_OUTPUT);
#       ...
#   }
# と、audio_output_disable_index() も同様に LockSetEnabled(false) が false
# (状態不変) を返した場合は即座にreturnしIDLE_OUTPUTを発火しない。
# (兄弟コマンド audio_output_toggle_index() は LockToggleEnabled() が常に状態を
# 反転させるため、no-opという概念自体が無く常にEmitIdleする非対称も確認済み —
# toggleoutput側は対象外)
#
# 一方 mopidy_mpd の disableoutput()/enableoutput() は現在のmute状態と一切比較せず
# 常に context.core.mixer.set_mute(False/True) を呼ぶ。この dev 環境が使う
# mopidy/audio/actor.py の SoftwareMixer.set_mute() は
# self._mixer.trigger_mute_changed(self.get_mute()) を値が変わったかどうかに
# 関係なく無条件に呼ぶため、mute_changed core イベント経由で
# changed: output の idle 通知が値が全く変化していないのに発火してしまう。
# 全く同じ根本原因 (SoftwareMixerの無条件trigger_*_changed) を volume (相対指定)
# については既に mpdvolumenoopidle-patch.py が修正済みだが、兄弟コマンドの
# enableoutput/disableoutput (mute方向) には未対応のまま残っていた。
# BACKLOG.md全体を "enableoutput"/"disableoutput"/"LockSetEnabled"/"no-op" で
# 検索したが、既存項目 (mpdoutputtogglerace/mpdoutputpartition/
# mpdidlemixerpartition) はレース・パーティション所有・パーティション越しidle漏れ
# のみを扱っており、本件 (同一パーティション内でのno-op時のidle抑制) は未対応と
# 確認した。
#
# 修正: mpdoutputtogglerace-patch.pyが既に追加した_output_mixer_lockスコープ内で、
# set_mute()呼び出し前に現在のmute状態を確認し、既に要求状態と一致するならno-opと
# してsuccess=Trueとする(実MPDのLockSetEnabled()と同じ「実際に変化した場合のみ」
# ガード)。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

MARKER = "既にmute状態が一致するならno-op"
if MARKER in s:
    print("mpdoutputnoopidle already applied to audio_output.py, skip")
else:
    old_disable = (
        "        with _output_mixer_lock:\n"
        "            success = context.core.mixer.set_mute(False).get()\n"
    )
    assert s.count(old_disable) == 1, f"old_disable count={s.count(old_disable)}"
    new_disable = (
        "        with _output_mixer_lock:\n"
        "            # mpdoutputnoopidle-patch.py: 実MPD(LockSetEnabled(false)が"
        "状態不変時に早期returnする挙動)と同じく、\n"
        "            # 既にmute状態が一致するならno-opとしてmixer書き込み/idle"
        "発火を抑制\n"
        "            if not context.core.mixer.get_mute().get():\n"
        "                success = True\n"
        "            else:\n"
        "                success = context.core.mixer.set_mute(False).get()\n"
    )
    s = s.replace(old_disable, new_disable, 1)

    old_enable = (
        "        with _output_mixer_lock:\n"
        "            success = context.core.mixer.set_mute(True).get()\n"
    )
    assert s.count(old_enable) == 1, f"old_enable count={s.count(old_enable)}"
    new_enable = (
        "        with _output_mixer_lock:\n"
        "            # mpdoutputnoopidle-patch.py: 実MPD(LockSetEnabled(true)が"
        "状態不変時に早期returnする挙動)と同じく、\n"
        "            # 既にmute状態が一致するならno-opとしてmixer書き込み/idle"
        "発火を抑制\n"
        "            if context.core.mixer.get_mute().get():\n"
        "                success = True\n"
        "            else:\n"
        "                success = context.core.mixer.set_mute(True).get()\n"
    )
    s = s.replace(old_enable, new_enable, 1)

    open(p, "w").write(s)
    print(
        "patched audio_output.py: disableoutput/enableoutputが要求状態と現在の"
        "mute状態が既に一致するno-opの場合でも常にset_mute()を呼びmute_changed経由の"
        "idle output通知を誤発火させていた不具合を修正 (実MPDのLockSetEnabled()の"
        "状態不変ガードに追随)"
    )
