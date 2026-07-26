# `single {STATE}` / `consume {STATE}` は musicpd.org protocol (single は MPD 0.21+,
# consume は MPD 0.24+) で STATE に `0`/`1` に加えて `oneshot` を許すが、mopidy-mpd 3.3.0
# は両コマンドとも `state=protocol.BOOL` (0/1のみ) で登録されているため `single oneshot` /
# `consume oneshot` を送ると `ACK [2@0] {single} incorrect arguments` になる。
#
# rmpc (rmpc-mpd/src/mpd_client.rs send_single/send_consume, rmpc/src/ui/mod.rs の
# SingleGlobal/SingleOnOff/ConsumeGlobal/ConsumeOnOff アクション) は実際に
# `OnOffOneshot::cycle()` で off→on→oneshot→off と3値を送信し、ステータスバー表示
# (rmpc/src/ui/panes/mod.rs StatusProperty::Consume/Single) は `status` の
# single/consume フィールドを `"0"`/`"1"`/`"oneshot"` としてパースする
# (rmpc-mpd/src/commands/status.rs OnOffOneshot::from_str) ため、未対応のままだと
# oneshot への切り替えが ACK エラーで失敗し、UI操作が機能しない。
#
# 実装:
# 1. protocol/__init__.py に ONOFFONESHOT 変換関数を追加 (BOOL と同じ流儀)。
# 2. playback.py の single/consume を ONOFFONESHOT で受け、実際の on/off は
#    (state != "0") として既存の mopidy core (tracklist.set_single/set_consume、
#    どちらも実在する機能で crossfade/prio と違いスタブではない) にそのまま反映しつつ、
#    表示用の3値 ("0"/"1"/"oneshot") は translator.py の揮発性ストアに保存。
# 3. status.py の single/consume フィールドはそのストアの値を返す。
# 4. 実 MPD の oneshot は対象の1曲の再生が終わったら自動で off に戻る仕様のため、
#    actor.py の MpdFrontend (既存の CoreListener) が受け取る track_playback_ended
#    イベントで oneshot なら off へ戻す (mopidy core 自体はパッチ対象外だが、
#    mopidy_mpd 拡張側からの CoreListener 購読は対象内)。

ip = "mopidy_mpd/protocol/__init__.py"
s0 = open(ip).read()

MARKER0 = "def ONOFFONESHOT"
if MARKER0 in s0:
    print("protocol/__init__.py already patched, skip")
else:
    anchor0 = (
        "def BOOL(value):  # noqa: N802\n"
        '    """Convert the values 0 and 1 into booleans."""\n'
        '    if value in ("1", "0"):\n'
        "        return bool(int(value))\n"
        "    raise ValueError(f\"{value!r} is not 0 or 1\")\n"
    )
    assert s0.count(anchor0) == 1, f"anchor0 count={s0.count(anchor0)}"
    addition0 = (
        "\n\n\n"
        "def ONOFFONESHOT(value):  # noqa: N802\n"
        '    """Convert the values used by ``single``/``consume``: 0, 1 or oneshot."""\n'
        '    if value in ("0", "1", "oneshot"):\n'
        "        return value\n"
        "    raise ValueError(f\"{value!r} is not 0, 1 or oneshot\")"
    )
    s0 = s0.replace(anchor0, anchor0.rstrip("\n") + addition0 + "\n", 1)
    open(ip, "w").write(s0)
    print("patched protocol/__init__.py: ONOFFONESHOT 変換関数を追加")

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "translator.set_single_state"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    bare_import = "from mopidy_mpd import exceptions, protocol\n"
    with_translator_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    if bare_import in s:
        assert s.count(bare_import) == 1, f"bare_import count={s.count(bare_import)}"
        s = s.replace(bare_import, with_translator_import, 1)
    else:
        assert s.count(with_translator_import) == 1, (
            f"with_translator_import count={s.count(with_translator_import)}"
        )

    old_consume = (
        '@protocol.commands.add("consume", state=protocol.BOOL)\n'
        "def consume(context, state):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``consume {STATE}``\n"
        "\n"
        "        Sets consume state to ``STATE``, ``STATE`` should be 0 or\n"
        "        1. When consume is activated, each song played is removed from\n"
        "        playlist.\n"
        '    """\n'
        "    context.core.tracklist.set_consume(state)\n"
    )
    assert s.count(old_consume) == 1, f"old_consume count={s.count(old_consume)}"
    new_consume = (
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
        '    context.core.tracklist.set_consume(state != "0")\n'
        "    translator.set_consume_state(state)\n"
    )
    s = s.replace(old_consume, new_consume, 1)

    old_single = (
        '@protocol.commands.add("single", state=protocol.BOOL)\n'
        "def single(context, state):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``single {STATE}``\n"
        "\n"
        "        Sets single state to ``STATE``, ``STATE`` should be 0 or 1. When\n"
        "        single is activated, playback is stopped after current song, or\n"
        "        song is repeated if the ``repeat`` mode is enabled.\n"
        '    """\n'
        "    context.core.tracklist.set_single(state)\n"
    )
    assert s.count(old_single) == 1, f"old_single count={s.count(old_single)}"
    new_single = (
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
        '    context.core.tracklist.set_single(state != "0")\n'
        "    translator.set_single_state(state)\n"
    )
    s = s.replace(old_single, new_single, 1)
    open(pp, "w").write(s)
    print("patched playback.py: single/consume に oneshot を追加")

sp = "mopidy_mpd/protocol/status.py"
s2 = open(sp).read()

MARKER2 = "translator.get_consume_state"
if MARKER2 in s2:
    print("status.py already patched, skip")
else:
    old_consume_status = (
        "def _status_consume(futures):\n"
        '    if futures["tracklist.consume"].get():\n'
        "        return 1\n"
        "    else:\n"
        "        return 0\n"
    )
    assert s2.count(old_consume_status) == 1, (
        f"old_consume_status count={s2.count(old_consume_status)}"
    )
    new_consume_status = (
        "def _status_consume(futures):\n"
        "    return translator.get_consume_state()\n"
    )
    s2 = s2.replace(old_consume_status, new_consume_status, 1)

    old_single_status = (
        "def _status_single(futures):\n"
        '    return int(futures["tracklist.single"].get())\n'
    )
    assert s2.count(old_single_status) == 1, (
        f"old_single_status count={s2.count(old_single_status)}"
    )
    new_single_status = (
        "def _status_single(futures):\n"
        "    return translator.get_single_state()\n"
    )
    s2 = s2.replace(old_single_status, new_single_status, 1)

    open(sp, "w").write(s2)
    print("patched status.py: single/consume フィールドを揮発性ストアから反映")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER3 = "_single_state"
if MARKER3 in t:
    print("translator.py already patched, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# single/consume (playback.py) の oneshot 表示用の揮発性ストア。実 MPD 同様\n"
        "# oneshot は対象の1曲の再生が終わったら off に自動で戻る (actor.py の\n"
        "# MpdFrontend.on_event が track_playback_ended で担う)。\n"
        '_single_state = "0"\n'
        '_consume_state = "0"\n'
        "\n"
        "\n"
        "def set_single_state(state):\n"
        "    global _single_state\n"
        "    _single_state = state\n"
        "\n"
        "\n"
        "def get_single_state():\n"
        "    return _single_state\n"
        "\n"
        "\n"
        "def set_consume_state(state):\n"
        "    global _consume_state\n"
        "    _consume_state = state\n"
        "\n"
        "\n"
        "def get_consume_state():\n"
        "    return _consume_state\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: single/consume の oneshot 揮発性ストアを追加")

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER4 = "_revert_oneshot"
if MARKER4 in a:
    print("actor.py already patched, skip")
else:
    old_import = "from mopidy_mpd import network, session, uri_mapper\n"
    assert a.count(old_import) == 1, f"old_import count={a.count(old_import)}"
    new_import = "from mopidy_mpd import network, session, translator, uri_mapper\n"
    a = a.replace(old_import, new_import, 1)

    old_init_tail = (
        "        self.uri_map = uri_mapper.MpdUriMapper(core)\n"
        "\n"
        "        self.zeroconf_name = config[\"mpd\"][\"zeroconf\"]\n"
    )
    assert a.count(old_init_tail) == 1, f"old_init_tail count={a.count(old_init_tail)}"
    new_init_tail = (
        "        self.uri_map = uri_mapper.MpdUriMapper(core)\n"
        "        self.core = core\n"
        "\n"
        "        self.zeroconf_name = config[\"mpd\"][\"zeroconf\"]\n"
    )
    a = a.replace(old_init_tail, new_init_tail, 1)

    old_on_event = (
        "    def on_event(self, event, **kwargs):\n"
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
        "            logger.warning(\n"
        '                "Got unexpected event: %s(%s)", event, ", ".join(kwargs)\n'
        "            )\n"
        "        else:\n"
        "            self.send_idle(_CORE_EVENTS_TO_IDLE_SUBSYSTEMS[event])\n"
    )
    assert a.count(old_on_event) == 1, f"old_on_event count={a.count(old_on_event)}"
    new_on_event = (
        "    def on_event(self, event, **kwargs):\n"
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
        "            logger.warning(\n"
        '                "Got unexpected event: %s(%s)", event, ", ".join(kwargs)\n'
        "            )\n"
        "        else:\n"
        "            self.send_idle(_CORE_EVENTS_TO_IDLE_SUBSYSTEMS[event])\n"
        "\n"
        "    def _revert_oneshot(self):\n"
        "        # 実 MPD 同様、single/consume の oneshot は対象の1曲の再生が終わったら\n"
        "        # off に自動で戻る (musicpd.org protocol, single/consume oneshot mode)。\n"
        '        if translator.get_single_state() == "oneshot":\n'
        '            translator.set_single_state("0")\n'
        "            self.core.tracklist.set_single(False)\n"
        '        if translator.get_consume_state() == "oneshot":\n'
        '            translator.set_consume_state("0")\n'
        "            self.core.tracklist.set_consume(False)\n"
    )
    a = a.replace(old_on_event, new_on_event, 1)

    open(ap, "w").write(a)
    print("patched actor.py: track_playback_ended で oneshot を自動 off に戻す")
