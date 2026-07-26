# 非推奨の相対 `volume {CHANGE}` (mopidy_mpd/protocol/playback.py) が、実際には
# 音量が変化しない no-op (`change=0`、あるいは既に 0/100 に張り付いていて
# クランプ後も old_volume と同値になるケース) でも常に
# `context.core.mixer.set_volume(new_volume)` を無条件に呼んでしまう不具合。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、raw curlでソース直接確認:
# src/command/OtherCommands.cxx `handle_volume()`) は:
#   int new_volume = old_volume + relative;
#   if (new_volume < 0) new_volume = 0;
#   else if (new_volume > 100) new_volume = 100;
#   if (new_volume != old_volume) {
#       mixer_memento.SetVolume(outputs, new_volume);
#       partition.EmitIdle(IDLE_MIXER);
#   }
# と、クランプ後の new_volume が old_volume と実際に異なる場合のみミキサー書き込みと
# IDLE_MIXER 発火を行う (兄弟コマンド `handle_setvol()` にはこのガードが無く常に
# 書き込む非対称も同ファイルで確認済み — つまり `volume` (相対指定) 固有の挙動)。
#
# 一方 mopidy_mpd の `volume()` は new_volume と old_volume を一切比較せず常に
# `context.core.mixer.set_volume(new_volume)` を呼ぶ。この dev 環境が使う
# `mopidy/audio/actor.py` の `SoftwareMixer.set_volume()` は
# `self._mixer.trigger_volume_changed(self.get_volume())` を値が変わったかどうかに
# 関係なく無条件に呼ぶため、`volume_changed` core イベント経由で
# `changed: mixer` の idle 通知が値が全く変化していないのに発火してしまう
# (mpdidlemixerpartition-patch.py が対処した「パーティション越しに漏れる」問題とは
# 別軸: 所有パーティション内であっても、変化が無いのに通知が飛ぶこと自体が不具合)。
# BACKLOG.md 全体を "new_volume != old_volume" / "no-op" 関連の volume 記述で検索したが
# 既存のvolume関連項目 (mpdvolumerace/mpdvolumepartition/mpdsetvolrange/mpdgetvol/
# mpdstatusvolumeomit/mpdidlemixerpartition) はいずれもレース・パーティション所有・
# 範囲外バリデーション・空応答条件・パーティション越しidle漏れのみを扱っており、
# 本項目 (同一パーティション内でのno-op時のidle抑制) は未対応と確認した。
#
# 修正: mpdvolumepartition-patch.py が既に書き換えた `volume()` 本体
# (`new_volume = min(max(0, old_volume + change), 100)` の直後) に、
# 実MPDと同じ `new_volume != old_volume` ガードを追加し、no-op時は
# `set_volume()` を呼ばず `success = True` (変化なしも成功扱い) とする。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

MARKER = "no-opならmixer書き込み/idle発火を抑制"
if MARKER in s:
    print("mpdvolumenoopidle already applied to playback.py, skip")
else:
    old_volume = (
        "        new_volume = min(max(0, old_volume + change), 100)\n"
        "        success = context.core.mixer.set_volume(new_volume).get()\n"
    )
    assert s.count(old_volume) == 1, f"old_volume count={s.count(old_volume)}"
    new_volume = (
        "        new_volume = min(max(0, old_volume + change), 100)\n"
        "        # mpdvolumenoopidle-patch.py: 実MPD (handle_volume()) と同じく、"
        "no-opならmixer書き込み/idle発火を抑制\n"
        "        if new_volume == old_volume:\n"
        "            success = True\n"
        "        else:\n"
        "            success = context.core.mixer.set_volume(new_volume).get()\n"
    )
    s = s.replace(old_volume, new_volume, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: 相対volume(CHANGE)がクランプ後も音量に変化が無い"
        "no-opの場合でも常にset_volume()を呼びvolume_changedのidle mixer通知を"
        "誤発火させていた不具合を修正 (実MPDのnew_volume != old_volumeガードに追随)"
    )
