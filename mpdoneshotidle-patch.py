# `single {STATE}` / `consume {STATE}` (mpdoneshot-patch.py で oneshot 対応済み) は
# 表示用の3値状態を `state != "0"` で真偽値に潰してから mopidy core
# (`context.core.tracklist.set_single`/`set_consume`) へ渡している。mopidy core の
# `set_single`/`set_consume` (mopidy/core/tracklist.py) は真偽値が実際に反転した
# ときだけ `_trigger_options_changed()` (→ `options_changed` イベント→ actor.py の
# `MpdFrontend.on_event` 経由で idle "options" 通知) を呼ぶため、`"1"` と
# `"oneshot"` は同じ `True` に潰れてしまい、両者間の遷移
# (`single "1"` → `single "oneshot"`、またはその逆) では真偽値が変化せず
# `options_changed` が一切発火しない。TODO 全項目消化済みのため自走エージェントが
# ソース精読調査で発見した。
#
# 実 MPD (MusicPlayerDaemon/MPD, WebFetch で src/queue/Playlist.cxx を直接確認) の
# `single`/`consume` は `SingleMode`/`ConsumeMode` という3値 enum そのものであり、
# `playlist::SetSingle`/`SetConsume` は `if (status == queue.single) return;` と
# enum 値そのものを比較するため、`ON → ONESHOT`(またはその逆) も値の変化として
# 正しく検出され `listener.OnQueueOptionsChanged()` (→ `EmitIdle(IDLE_OPTIONS)`) が
# 呼ばれる。mopidy_mpd 側は真偽値への圧縮が enum の意味の一部 (on/oneshotの区別) を
# 握り潰しており、実 MPD 仕様に反する。
#
# 実害: rmpc (rmpc-mpd/src/commands/status.rs `OnOffOneshot::cycle()` は
# `Off → Oneshot → On → Off` の順で3値を送信する通常のキーバインド操作) がまさに
# この `Oneshot → On` 遷移を経由するため、`idle options` で待機している別クライアント
# (または同一クライアントの別接続) は single/consume のステータス表示が
# 古いまま更新されない、というサイレントな不整合が生じる。
#
# 実装: crossfade/mixrampdb/mixrampdelay (mpdcrossfadeidle-patch.py) と同じ流儀で、
# 本パッチ専用の `_mpdoneshotidle_notify()` を playback.py に追加し、
# `single()`/`consume()` の末尾で常に呼ぶ (mopidy core 側で既に options_changed が
# 発火する 0⇔1 / 0⇔oneshot 遷移では二重通知になるが、idle のイベント集合は
# 同じサブシステムの再追加が単なる no-op であるため実害はない。真偽値が変化した
# ケースだけ通知を省く分岐は複雑さの割に得るものがなく、常時通知の方が
# crossfadeidle と同じ単純さを保てる)。他パッチ実装済みの notify 関数へ相乗りせず
# 自パッチ内で完結させ、適用順序への依存を避ける (mpdcrossfadeidle-patch.py 冒頭
# コメントと同じ理由)。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "_mpdoneshotidle_notify"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_consume = (
        '@protocol.commands.add("consume", state=protocol.ONOFFONESHOT)\n'
        "def consume(context, state):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``consume {STATE}``\n"
        "\n"
        "        Sets consume state to ``STATE``, ``STATE`` should be 0, 1 or\n"
        "        ``oneshot``. When consume is activated, each song played is\n"
        "        removed from playlist. In ``oneshot`` mode only the next song\n"
        "        played is removed, then consume automatically reverts to off.\n"
        '    """\n'
        '    context.core.tracklist.set_consume(state != "0").get()\n'
        "    translator.set_consume_state(state)\n"
    )
    assert s.count(old_consume) == 1, f"old_consume count={s.count(old_consume)}"
    new_consume = (
        "def _mpdoneshotidle_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "options")\n'
        "\n"
        "\n"
        '@protocol.commands.add("consume", state=protocol.ONOFFONESHOT)\n'
        "def consume(context, state):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``consume {STATE}``\n"
        "\n"
        "        Sets consume state to ``STATE``, ``STATE`` should be 0, 1 or\n"
        "        ``oneshot``. When consume is activated, each song played is\n"
        "        removed from playlist. In ``oneshot`` mode only the next song\n"
        "        played is removed, then consume automatically reverts to off.\n"
        '    """\n'
        '    context.core.tracklist.set_consume(state != "0").get()\n'
        "    translator.set_consume_state(state)\n"
        "    _mpdoneshotidle_notify()\n"
    )
    s = s.replace(old_consume, new_consume, 1)

    old_single = (
        '@protocol.commands.add("single", state=protocol.ONOFFONESHOT)\n'
        "def single(context, state):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``single {STATE}``\n"
        "\n"
        "        Sets single state to ``STATE``, ``STATE`` should be 0, 1 or\n"
        "        ``oneshot``. When single is activated, playback is stopped\n"
        "        after current song, or song is repeated if the ``repeat``\n"
        "        mode is enabled. In ``oneshot`` mode this applies only to the\n"
        "        next song, then single automatically reverts to off.\n"
        '    """\n'
        '    context.core.tracklist.set_single(state != "0").get()\n'
        "    translator.set_single_state(state)\n"
    )
    assert s.count(old_single) == 1, f"old_single count={s.count(old_single)}"
    new_single = old_single + "    _mpdoneshotidle_notify()\n"
    s = s.replace(old_single, new_single, 1)

    open(pp, "w").write(s)
    print(
        "patched playback.py: single/consume の oneshot⇔on 遷移でも idle options"
        "通知を発火するよう修正"
    )
