# mopidy-mpd 3.3.0 の `crossfade {SECONDS}` は `raise MpdNotImplemented` のスタブで、
# `status` の `xfade` フィールドも常に固定値 0 を返すだけ (_status_xfade)。
# rmpc (rmpc/src/ui/mod.rs の CrossfadeUp/CrossfadeDown グローバルアクション、
# rmpc-mpd/src/mpd_client.rs send_crossfade) は実際にこのコマンドを送信し、
# ステータスバーの Crossfade 表示 (rmpc/src/ui/panes/mod.rs StatusProperty::Crossfade)
# は `status` の xfade を読むため、未実装のままだと ACK エラーになり、値も常に 0 表示のまま
# 変化しない。
#
# 実装: prio/prioid (mpdprio-patch.py) と同じ流儀で、crossfade 秒数を
# translator.py にモジュールレベルの揮発性ストアとして保持し (プロセス再起動で
# 消えるのは実 MPD の crossfade 設定も同じなので妥当)、`crossfade` コマンドで更新、
# `status` の xfade フィールドで反映する。
#
# 既知の制約: mopidy core (mopidy/core/playback.py) 自体は GStreamer レベルの
# クロスフェード機能を持たず、この値が実際の再生に影響することはない
# (プロトコル応答・status の xfade フィールド反映のみ)。mopidy core 自体は
# パッチ対象外 (nix/lib/mopidy-env.nix が patch するのは mopidy-mpd/ytmusic/
# listenbrainz の拡張のみ) のため妥当な範囲。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "translator.set_crossfade"
if MARKER in s:
    print("crossfade already patched, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    s = s.replace(old_import, new_import, 1)

    old_block = (
        '@protocol.commands.add("crossfade", seconds=protocol.UINT)\n'
        "def crossfade(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``crossfade {SECONDS}``\n"
        "\n"
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
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
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched playback.py: crossfade を実装 (揮発性ストアへ保存)")

sp = "mopidy_mpd/protocol/status.py"
s2 = open(sp).read()

MARKER2 = "translator.get_crossfade"
if MARKER2 in s2:
    print("status.py already patched, skip")
else:
    old_xfade = "def _status_xfade(futures):\n    return 0  # Not supported\n"
    assert s2.count(old_xfade) == 1, f"old_xfade count={s2.count(old_xfade)}"
    new_xfade = "def _status_xfade(futures):\n    return translator.get_crossfade()\n"
    s2 = s2.replace(old_xfade, new_xfade, 1)
    open(sp, "w").write(s2)
    print("patched status.py: xfade フィールドを揮発性ストアから反映")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER3 = "_crossfade_seconds"
if MARKER3 in t:
    print("translator.py already patched, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# crossfade (playback.py) 用の揮発性ストア。プロセス再起動で消えるのは\n"
        "# 実 MPD の crossfade 設定も同じなので妥当。\n"
        "_crossfade_seconds = 0\n"
        "\n"
        "\n"
        "def set_crossfade(seconds):\n"
        "    global _crossfade_seconds\n"
        "    _crossfade_seconds = seconds\n"
        "\n"
        "\n"
        "def get_crossfade():\n"
        "    return _crossfade_seconds\n"
        "\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: crossfade 秒数の揮発性ストアを追加")
