# `getvol`/`setvol`/相対 `volume {CHANGE}` (mopidy_mpd/protocol/playback.py) が、
# mpdpartition-patch.py の追加したパーティション機構 (`newpartition`/`partition`/
# `moveoutput`) を一切考慮せず、常に `context.core.mixer` という単一グローバル
# actor へ直接アクセスしてしまう不具合。TODO 全項目消化済みのため自走エージェント
# (general-purposeサブエージェントへの調査委任を経て) が新規発見・追加した項目。
#
# 実MPD本体 (MusicPlayerDaemon/MPD, WebFetchではなくraw curlでソース直接確認:
# src/command/OtherCommands.cxx `handle_getvol`/`handle_setvol`/`handle_volume`、
# src/mixer/Memento.cxx `MixerMemento::GetVolume`/`SetVolume`) は、いずれも
# `client.GetPartition()` で得た **そのパーティションが所有する出力集合
# (`partition.outputs`)** に対してのみ動作する:
#   - `handle_getvol`: `GetVolume(partition.outputs)` が負値なら `volume:` 行自体を
#     省略した空応答を返す (所有出力が無ければ常に負値)。
#   - `handle_setvol`: 所有出力0件の集合に対する `SetVolume()` は何も対象が無く
#     暗黙のno-opになるが、コマンド自体は常に `OK` を返す。
#   - `handle_volume` (相対指定): `old_volume < 0` (所有出力0件) なら
#     `r.Error(ACK_ERROR_SYSTEM, "No mixer")` で明示的にACKする。
# mopidy_mpd 本体には core.mixer actor が唯一つしか存在せず「パーティション所有の
# 出力集合」という概念自体が無いため、mpdoutputpartition-patch.py が
# audio_output.py の `outputs`/`enableoutput`/`disableoutput`/`toggleoutput` 向けに
# 導入した「唯一の仮想出力 "Mute" の所属パーティション == 自セッションの所属
# パーティション」という同じ判定 (`translator.output_partition_get("Mute") ==
# translator.partition_get(id(context.session))`) を、この3ハンドラにも同様に
# 適用することで実MPDの「パーティションが出力を所有しているか」判定を代替できる。
# 実害: `newpartition` で別パーティションを作り `moveoutput Mute` で仮想出力を
# そちらへ移した後でも、元のパーティション (Muteをもう所有していない) から
# `getvol`/`setvol`/`volume` を実行すると引き続き実際のグローバル音量を
# 読み書きできてしまう。rmpc (`rmpc-mpd/src/mpd_client.rs` の
# `send_volume`/`send_set_vol`、idle Mixerイベント経由の `getvol`) はこれら3
# コマンドを実際に使うため、到達可能な実害のあるギャップ。
#
# 修正: playback.py に `_mpdvolumepartition_owned(context)` ヘルパを追加
# (audio_output.py の `_mpdoutputpartition_owned` と同一ロジック、
# mpdpartition-patch.py が既に持つ揮発性ストアを参照するのみで新規状態は
# 持たない)。`getvol` は非所有時に空応答、`setvol` は非所有時に暗黙no-opで
# `OK` (成功扱いのため戻り値なし=Noneを返して早期return)、`volume` は非所有時に
# 実MPDの `ACK_ERROR_SYSTEM "No mixer"` と同じ `MpdSystemError("No mixer")` を送出。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

MARKER = "_mpdvolumepartition_owned"
if MARKER in s:
    print("mpdvolumepartition already applied to playback.py, skip")
else:
    # 1) ヘルパ定義を _mixer_volume_lock の直後・getvol定義の直前に挿入
    old_helper = (
        "_mixer_volume_lock = threading.Lock()\n"
        "\n"
        "\n"
        '@protocol.commands.add("getvol")\n'
        "def getvol(context):\n"
    )
    assert s.count(old_helper) == 1, f"old_helper count={s.count(old_helper)}"
    new_helper = (
        "_mixer_volume_lock = threading.Lock()\n"
        "\n"
        "\n"
        "# getvol/setvol/相対volumeの3ハンドラは、実MPDではパーティションが所有する\n"
        "# 出力集合に対してのみ動作する(非所有時: getvolは空応答、setvolは暗黙\n"
        "# no-opでOK、volumeはACK No mixer)。mopidy_mpdにはパーティション毎の\n"
        "# mixerが無く常にグローバルなcontext.core.mixerを指すため、\n"
        "# mpdoutputpartition-patch.pyのaudio_output._mpdoutputpartition_ownedと\n"
        "# 同じ判定(唯一の仮想出力Muteの所属パーティション==自セッションの所属\n"
        "# パーティション)を代わりに使う(mpdvolumepartition-patch.py)。\n"
        "def _mpdvolumepartition_owned(context):\n"
        '    return translator.output_partition_get("Mute") == translator.partition_get(\n'
        "        id(context.session)\n"
        "    )\n"
        "\n"
        "\n"
        '@protocol.commands.add("getvol")\n'
        "def getvol(context):\n"
    )
    s = s.replace(old_helper, new_helper, 1)

    # 2) getvol() 本体: 非所有時は空応答 (実MPD: volume>=0の時のみvolume:行を出力)
    old_getvol = (
        "    volume = context.core.mixer.get_volume().get()\n"
        "    if volume is None:\n"
        "        return []\n"
        '    return [("volume", volume)]\n'
    )
    assert s.count(old_getvol) == 1, f"old_getvol count={s.count(old_getvol)}"
    new_getvol = (
        "    if not _mpdvolumepartition_owned(context):\n"
        "        return []\n"
        "    volume = context.core.mixer.get_volume().get()\n"
        "    if volume is None:\n"
        "        return []\n"
        '    return [("volume", volume)]\n'
    )
    s = s.replace(old_getvol, new_getvol, 1)

    # 3) setvol() 本体: 非所有時は暗黙no-opでOK (実MPD: 所有出力0件へのSetVolume)
    old_setvol = (
        "    if volume < 0 or volume > 100:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    value = volume\n"
        "    with _mixer_volume_lock:\n"
        "        success = context.core.mixer.set_volume(value).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    assert s.count(old_setvol) == 1, f"old_setvol count={s.count(old_setvol)}"
    new_setvol = (
        "    if volume < 0 or volume > 100:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    if not _mpdvolumepartition_owned(context):\n"
        "        return\n"
        "    value = volume\n"
        "    with _mixer_volume_lock:\n"
        "        success = context.core.mixer.set_volume(value).get()\n"
        "    if not success:\n"
        '        raise exceptions.MpdSystemError("problems setting volume")\n'
    )
    s = s.replace(old_setvol, new_setvol, 1)

    # 4) volume() (相対指定) 本体: 非所有時はACK No mixer (実MPD: old_volume<0)
    old_volume = (
        "    if change < -100 or change > 100:\n"
        '        raise exceptions.MpdArgError("Invalid volume value")\n'
        "\n"
        "    with _mixer_volume_lock:\n"
        "        old_volume = context.core.mixer.get_volume().get()\n"
    )
    assert s.count(old_volume) == 1, f"old_volume count={s.count(old_volume)}"
    new_volume = (
        "    if change < -100 or change > 100:\n"
        '        raise exceptions.MpdArgError("Invalid volume value")\n'
        "    if not _mpdvolumepartition_owned(context):\n"
        '        raise exceptions.MpdSystemError("No mixer")\n'
        "\n"
        "    with _mixer_volume_lock:\n"
        "        old_volume = context.core.mixer.get_volume().get()\n"
    )
    s = s.replace(old_volume, new_volume, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: getvol/setvol/volumeがパーティション所有の出力を"
        "考慮せず常にグローバルなcontext.core.mixerへ直接アクセスしていた不具合を修正 "
        "(moveoutputで仮想出力Muteを他パーティションへ移した後、非所有パーティション"
        "からのgetvolは空応答/setvolは暗黙no-op/volumeはACK No mixerへ)"
    )
