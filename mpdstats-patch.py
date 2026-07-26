# `stats` (mopidy_mpd/protocol/status.py) は musicpd.org protocol 標準の統計コマンドだが、
# mopidy-mpd 3.3.0 では artists/albums/songs/uptime/db_playtime/db_update/playtime の
# 全フィールドが常に固定値 0 (`# TODO`) のまま返る。TODO 全項目消化済みのため自走エージェントが
# 残存する `# TODO` を洗い出して発見した項目。rmpc 本体 (mierak/rmpc, 既存の
# /private/tmp/rmpc-check clone を再利用) の rmpc-mpd/src/mpd_client.rs 全 `send_*` を
# 洗い出したが `stats` を送信する経路は皆無 (rmpc はこの機能を使わない) と判明したため、
# clearerror/replay_gain/mixrampdb/decoders と同種の「rmpc固有ではなく標準 MPD プロトコル
# 準拠の不備」に該当すると判断: mpc/ncmpcpp 等の汎用 MPD クライアントが標準的に使う基本
# コマンドが常時ゼロ固定を返す現状はプロトコル層として不正確なギャップと判断した上で着手。
#
# 実装方針: uptime/db_update/playtime は実 MPD 同様プロセス揮発性の値として安全に実装できる
# (crossfade/mixrampdb と同じ流儀)。artists/albums は `list`/`count group` が既に安全に
# 使っている `context.core.library.get_distinct()` (mopidy-ytmusic backend でもライブラリ
# 由来の値のみを返す軽量な呼び出しと実績済み) を再利用して実値を返す。
# 一方 songs (DB内曲数)/db_playtime (DB内全曲の合計長) は「ライブラリ全体を走査して曲単位で
# 集計する」ことが必要で、これは configs/media/mopidy/BACKLOG.md の `listall` blocked 項目
# (mopidy-ytmusic backend の browse() がHome/Explore等の非有界カタログを含むため深さ優先の
# 再帰が事実上非有界になり、mopidy core actor を専有して他クライアントの status 応答すら
# 10秒以上ブロックするデッドロック同然の実害を実機で確認済み) と全く同じ危険を抱えるため、
# 安全策として未実装のまま 0 を返す (実装しない、決め打ちで誤魔化さない)。
#
# playtime は実 MPD (MusicPlayerDaemon/MPD src/command/StatsCommands.cxx handle_stats,
# src/Instance.cxx/src/PlayerControl.cxx 相当) もデコーダの再生位置進行を基準に積算する値で、
# 本実装では mopidy core の `track_playback_ended` イベント (mpdoneshot-patch.py が既に
# actor.py の MpdFrontend.on_event で購読済み) が渡す `time_position` (ms、曲の再生が
# 終了/切り替わった時点までの到達位置、mopidy/core/playback.py
# `_trigger_track_playback_ended` を実際にソース確認済み) を積算する近似値として実装する
# (シークで位置を巻き戻した場合は壁時計時間より少なく積算されうるが、実 MPD 自体も
# デコーダの再生位置進行を基準にしているため方向性は一致する、mixrampdb/decoders と同種の
# 割り切り)。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER = "get_uptime"
if MARKER in s:
    print("status.py already patched, skip")
else:
    old_stats = '''    return {
        "artists": 0,  # TODO
        "albums": 0,  # TODO
        "songs": 0,  # TODO
        "uptime": 0,  # TODO
        "db_playtime": 0,  # TODO
        "db_update": 0,  # TODO
        "playtime": 0,  # TODO
    }
'''
    assert s.count(old_stats) == 1, f"old_stats count={s.count(old_stats)}"
    new_stats = '''    artists = context.core.library.get_distinct("artist").get() or set()
    albums = context.core.library.get_distinct("album").get() or set()
    return {
        "artists": len([v for v in artists if v]),
        "albums": len([v for v in albums if v]),
        # songs/db_playtime はライブラリ全体の走査 (実質的に listall 相当) が必要で、
        # mopidy-ytmusic のような非有界カタログ backend では listall と同じく mopidy core
        # actor を専有し他クライアントを巻き込むおそれがあるため未実装のまま 0 を返す
        # (BACKLOG.md の `listall` blocked 項目と同種の安全策)。
        "songs": 0,  # TODO
        "uptime": translator.get_uptime(),
        "db_playtime": 0,  # TODO
        "db_update": translator.get_db_update_time(),
        "playtime": translator.get_playtime(),
    }
'''
    assert new_stats != old_stats
    s = s.replace(old_stats, new_stats, 1)
    open(sp, "w").write(s)
    print("patched status.py: stats の artists/albums/uptime/db_update/playtime を実装")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_db_update_time"
if MARKER2 in t:
    print("translator.py (db_update_time) already patched, skip")
else:
    anchor = (
        "_update_job_id = 0\n"
        "\n"
        "\n"
        "def next_update_job_id():\n"
        "    global _update_job_id\n"
        "    _update_job_id += 1\n"
        "    return _update_job_id\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    replacement = (
        "_update_job_id = 0\n"
        "_db_update_time = 0\n"
        "\n"
        "\n"
        "def next_update_job_id():\n"
        "    global _update_job_id, _db_update_time\n"
        "    _update_job_id += 1\n"
        "    _db_update_time = int(time.time())\n"
        "    return _update_job_id\n"
        "\n"
        "\n"
        "def get_db_update_time():\n"
        "    return _db_update_time\n"
    )
    t = t.replace(anchor, replacement, 1)
    open(tp, "w").write(t)
    print("patched translator.py: update/rescan 成功時の db_update 時刻を記録")

t = open(tp).read()
MARKER3 = "_playtime_ms"
if MARKER3 in t:
    print("translator.py (playtime) already patched, skip")
else:
    anchor2 = "# TODO: special handling of local:// uri scheme\n"
    assert t.count(anchor2) == 1, f"anchor2 count={t.count(anchor2)}"
    store = (
        "# stats (status.py) の uptime/playtime 用の揮発性ストア。実 MPD の uptime/playtime も\n"
        "# プロセス再起動でリセットされる値のため妥当。playtime は track_playback_ended\n"
        "# (actor.py MpdFrontend.on_event、mpdoneshot-patch.py が既に購読済み) が渡す\n"
        "# time_position (ms、再生終了/切り替わり時点までの到達位置) の積算値。\n"
        "_start_time = time.time()\n"
        "_playtime_ms = 0\n"
        "\n"
        "\n"
        "def get_uptime():\n"
        "    return int(time.time() - _start_time)\n"
        "\n"
        "\n"
        "def add_playtime(time_position):\n"
        "    global _playtime_ms\n"
        "    if time_position:\n"
        "        _playtime_ms += time_position\n"
        "\n"
        "\n"
        "def get_playtime():\n"
        "    return int(_playtime_ms / 1000)\n"
        "\n"
        "\n"
    )
    t = t.replace(anchor2, store + anchor2, 1)
    open(tp, "w").write(t)
    print("patched translator.py: uptime/playtime の揮発性ストアを追加")

t = open(tp).read()
MARKER4 = "import time\n"
if MARKER4 in t:
    print("translator.py (import time) already patched, skip")
else:
    old_imports = "import datetime\nimport logging\nimport re\n"
    assert t.count(old_imports) == 1, f"old_imports count={t.count(old_imports)}"
    new_imports = "import datetime\nimport logging\nimport re\nimport time\n"
    t = t.replace(old_imports, new_imports, 1)
    open(tp, "w").write(t)
    print("patched translator.py: import time を追加")

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER5 = "translator.add_playtime"
if MARKER5 in a:
    print("actor.py already patched, skip")
else:
    old_on_event = (
        "    def on_event(self, event, **kwargs):\n"
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
    )
    assert a.count(old_on_event) == 1, f"old_on_event count={a.count(old_on_event)}"
    new_on_event = (
        "    def on_event(self, event, **kwargs):\n"
        '        if event == "track_playback_ended":\n'
        "            self._revert_oneshot()\n"
        '            translator.add_playtime(kwargs.get("time_position"))\n'
    )
    a = a.replace(old_on_event, new_on_event, 1)
    open(ap, "w").write(a)
    print("patched actor.py: track_playback_ended で playtime を積算")
