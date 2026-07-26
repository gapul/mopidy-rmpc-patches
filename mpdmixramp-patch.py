# mopidy-mpd 3.3.0 の `mixrampdb {deciBels}` / `mixrampdelay {SECONDS}` は
# どちらも `raise MpdNotImplemented` のスタブで、標準 MPD クライアントがこれらの
# コマンドを送ると常に ACK エラーになる (実 MPD は両方とも OK を返す)。さらに
# `mixrampdelay` の引数型が `protocol.UINT` になっており、実 MPD が仕様上許可する
# 負値なしの小数秒や無効化用の特殊値 "nan" (MixRamp を無効化しクロスフェードへ
# フォールバックさせる) を渡すと ValueError で弾かれる (UINT は `\d+` の整数のみ)。
# 実 MPD (src/command/PlayerCommands.cxx) の `status` 応答は、crossfade
# (mpdcrossfade-patch.py で対応済み) と同様に `mixrampdb` を常時・`mixrampdelay` を
# 値が 0 より大きい時のみ返す。
#
# rmpc (rmpc-mpd/src/commands/status.rs Status::next_internal) は status 応答の
# mixrampdb/mixrampdelay フィールドを既にパース対象としているが、rmpc 自体は
# mixrampdb/mixrampdelay コマンドを送信する UI 導線を持たないため実害は
# 「標準 MPD クライアント/generic MPD ツールがこれらのコマンドを送ると常に
# ACK エラーになる」というプロトコル準拠上の不備。crossfade/oneshot/decoders と
# 同種の「未実装スタブを実際に動くプロトコル応答に揃える」項目として対応する。
#
# 実装: crossfade (mpdcrossfade-patch.py) と同じ流儀で、translator.py に
# モジュールレベルの揮発性ストアとして値を保持し (プロセス再起動で消えるのは
# 実 MPD の設定も同じなので妥当)、`mixrampdb`/`mixrampdelay` コマンドで更新、
# `status` の mixrampdb (常時)・mixrampdelay (>0 の時のみ) フィールドで反映する。
#
# 既知の制約: mopidy core は GStreamer レベルの MixRamp/クロスフェード機能を
# 持たないため、この値が実際の再生に影響することはない (プロトコル応答・status
# フィールド反映のみ。crossfade と同じ既知の限界)。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "translator.set_mixrampdb"
if MARKER in s:
    print("mixrampdb/mixrampdelay already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("mixrampdb")\n'
        "def mixrampdb(context, decibels):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdb {deciBels}``\n"
        "\n"
        "    Sets the threshold at which songs will be overlapped. Like crossfading but\n"
        "    doesn't fade the track volume, just overlaps. The songs need to have\n"
        "    MixRamp tags added by an external tool. 0dB is the normalized maximum\n"
        "    volume so use negative values, I prefer -17dB. In the absence of mixramp\n"
        "    tags crossfading will be used. See\n"
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
        "\n"
        "\n"
        '@protocol.commands.add("mixrampdelay", seconds=protocol.UINT)\n'
        "def mixrampdelay(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdelay {SECONDS}``\n"
        "\n"
        "        Additional time subtracted from the overlap calculated by mixrampdb. A\n"
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("mixrampdb", decibels=protocol.FLOAT)\n'
        "def mixrampdb(context, decibels):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdb {deciBels}``\n"
        "\n"
        "    Sets the threshold at which songs will be overlapped. Like crossfading but\n"
        "    doesn't fade the track volume, just overlaps. The songs need to have\n"
        "    MixRamp tags added by an external tool. 0dB is the normalized maximum\n"
        "    volume so use negative values, I prefer -17dB. In the absence of mixramp\n"
        "    tags crossfading will be used. See\n"
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    translator.set_mixrampdb(decibels)\n"
        "\n"
        "\n"
        '@protocol.commands.add("mixrampdelay", seconds=protocol.FLOAT)\n'
        "def mixrampdelay(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdelay {SECONDS}``\n"
        "\n"
        "        Additional time subtracted from the overlap calculated by mixrampdb. A\n"
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    translator.set_mixrampdelay(seconds)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched playback.py: mixrampdb/mixrampdelay を実装 (揮発性ストアへ保存)")

sp = "mopidy_mpd/protocol/status.py"
s2 = open(sp).read()

MARKER2 = "translator.get_mixrampdb"
if MARKER2 in s2:
    print("status.py already patched, skip")
else:
    old_xfade_entry = '        ("xfade", _status_xfade(futures)),\n'
    assert s2.count(old_xfade_entry) == 1, f"old_xfade_entry count={s2.count(old_xfade_entry)}"
    new_xfade_entry = (
        '        ("xfade", _status_xfade(futures)),\n'
        '        ("mixrampdb", _status_mixrampdb(futures)),\n'
    )
    s2 = s2.replace(old_xfade_entry, new_xfade_entry, 1)

    old_song_if = '    if futures["playback.current_tl_track"].get() is not None:\n'
    assert s2.count(old_song_if) == 1, f"old_song_if count={s2.count(old_song_if)}"
    new_song_if = (
        "    mixrampdelay = _status_mixrampdelay(futures)\n"
        "    if mixrampdelay > 0:\n"
        '        result.append(("mixrampdelay", mixrampdelay))\n'
        + old_song_if
    )
    s2 = s2.replace(old_song_if, new_song_if, 1)

    old_tail = "def _status_xfade(futures):\n    return translator.get_crossfade()\n"
    assert s2.count(old_tail) == 1, f"old_tail count={s2.count(old_tail)}"
    new_tail = (
        old_tail
        + "\n\n"
        + "def _status_mixrampdb(futures):\n"
        + "    return translator.get_mixrampdb()\n"
        + "\n\n"
        + "def _status_mixrampdelay(futures):\n"
        + "    return translator.get_mixrampdelay()\n"
    )
    s2 = s2.replace(old_tail, new_tail, 1)

    open(sp, "w").write(s2)
    print("patched status.py: mixrampdb(常時)/mixrampdelay(>0のみ) フィールドを反映")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER3 = "_mixrampdb"
if MARKER3 in t:
    print("translator.py already patched, skip")
else:
    anchor = "def get_crossfade():\n    return _crossfade_seconds\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        anchor
        + "\n\n"
        + "# mixrampdb/mixrampdelay (playback.py) 用の揮発性ストア。crossfade と同種の\n"
        + "# 理由でプロセス再起動で消えるのは実MPDの設定も同じなので妥当。mixrampdelay の\n"
        + "# 初期値 nan は実MPDのデフォルト(MixRamp無効・クロスフェードへフォールバック)と揃える。\n"
        + "_mixrampdb = 0.0\n"
        + "_mixrampdelay = float(\"nan\")\n"
        + "\n"
        + "\n"
        + "def set_mixrampdb(decibels):\n"
        + "    global _mixrampdb\n"
        + "    _mixrampdb = decibels\n"
        + "\n"
        + "\n"
        + "def get_mixrampdb():\n"
        + "    return _mixrampdb\n"
        + "\n"
        + "\n"
        + "def set_mixrampdelay(seconds):\n"
        + "    global _mixrampdelay\n"
        + "    _mixrampdelay = seconds\n"
        + "\n"
        + "\n"
        + "def get_mixrampdelay():\n"
        + "    return _mixrampdelay\n"
    )
    t = t.replace(anchor, store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: mixrampdb/mixrampdelay の揮発性ストアを追加")
