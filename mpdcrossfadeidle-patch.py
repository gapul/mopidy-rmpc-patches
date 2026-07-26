# `crossfade`/`mixrampdb`/`mixrampdelay` (mpdcrossfade-patch.py/mpdmixramp-patch.py で
# 実装済み) が idle "options" イベントを一切発火しない不具合。TODO 全項目消化済みの
# ため自走エージェントがソース精読調査で発見した。
#
# 実 MPD (src/command/PlayerCommands.cxx handle_crossfade/handle_mixrampdb/
# handle_mixrampdelay) はいずれも成功時に `partition.EmitIdle(IDLE_OPTIONS)` を呼び、
# `status.py` のdocstring自体も `idle` の `options` サブシステムを
# "options like repeat, random, crossfade, replay gain" と明記している。
# ところが `crossfade()`/`mixrampdb()`/`mixrampdelay()` は mopidy core
# (`context.core.tracklist` 等) を一切経由せず `translator.py` のモジュールレベル
# 揮発性ストアを直接書き換えるだけのため (mopidy core 自体は crossfade/mixramp の
# 概念を持たない)、`actor.py` の `MpdFrontend.on_event` が拾う core 由来の
# `options_changed` イベントに乗れず、`idle options` で待機中の他クライアントへは
# 一切通知が届かない。同じ揮発性ストア方式の `replay_gain_mode` (mpdreplaygain-patch.py)
# だけは `_mpdreplaygain_notify()` で明示的に idle 通知するよう既に対応済みで、
# crossfade/mixrampdb/mixrampdelay だけが取り残されていた。
#
# 実害: rmpc (rmpc-mpd/src/mpd_client.rs send_crossfade、rmpc/src/ui/ の
# CrossfadeUp/CrossfadeDown グローバルアクション) はcrossfadeコマンドを実際に送信し
# ステータスバーへ反映する導線を持つ。別クライアント(または同一クライアントの別接続)が
# crossfade/mixrampdb/mixrampdelayを変更しても、`idle options` で待機中のrmpc等は
# 起こされず、次に別の理由(repeat切替等)でoptionsイベントが発火するまで表示が
# 古いまま固定される、というサイレントな不整合が生じる。クラッシュやセッション切断は
# 起きないが実MPD仕様違反かつUI表示に実害がある。
#
# 実装: mount (mpdmount-patch.py の `_mpdmount_notify`)・replay_gain_mode
# (mpdreplaygain-patch.py の `_mpdreplaygain_notify`) と同じ流儀で、本パッチ専用の
# `_mpdcrossfadeidle_notify()` を playback.py に追加し、mpdcrossfade-patch.py/
# mpdmixramp-patch.py が実装済みの3関数の末尾に呼び出しを追加する
# (他パッチ実装済みの notify 関数へ相乗りせず自パッチ内で完結させ、
# 適用順序への依存を避ける)。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "_mpdcrossfadeidle_notify"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_crossfade = (
        '@protocol.commands.add("crossfade", seconds=protocol.UINT)\n'
        "def crossfade(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``crossfade {SECONDS}``\n"
        "\n"
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    translator.set_crossfade(seconds)\n"
    )
    assert s.count(old_crossfade) == 1, f"old_crossfade count={s.count(old_crossfade)}"
    new_crossfade = (
        "def _mpdcrossfadeidle_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "options")\n'
        "\n"
        "\n"
        '@protocol.commands.add("crossfade", seconds=protocol.UINT)\n'
        "def crossfade(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``crossfade {SECONDS}``\n"
        "\n"
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    translator.set_crossfade(seconds)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    s = s.replace(old_crossfade, new_crossfade, 1)

    old_mixrampdb = (
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
    )
    assert s.count(old_mixrampdb) == 1, f"old_mixrampdb count={s.count(old_mixrampdb)}"
    new_mixrampdb = old_mixrampdb + "    _mpdcrossfadeidle_notify()\n"
    s = s.replace(old_mixrampdb, new_mixrampdb, 1)

    old_mixrampdelay = (
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
    assert s.count(old_mixrampdelay) == 1, f"old_mixrampdelay count={s.count(old_mixrampdelay)}"
    new_mixrampdelay = old_mixrampdelay + "    _mpdcrossfadeidle_notify()\n"
    s = s.replace(old_mixrampdelay, new_mixrampdelay, 1)

    open(pp, "w").write(s)
    print(
        "patched playback.py: crossfade/mixrampdb/mixrampdelay が idle options 通知を"
        "発火するよう修正"
    )
