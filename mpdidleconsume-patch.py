# mopidy-mpd 3.3.0 の `idle` 実装 (mopidy_mpd/protocol/status.py の `idle()`/`noidle()`、
# mopidy_mpd/dispatcher.py の `MpdDispatcher.handle_idle()`) は、いずれも「今回の idle
# 呼び出しで報告した(購読集合との積集合の)サブシステムだけでなく、蓄積済みの
# `context.events` を丸ごと `set()` で全消去」してしまう不具合がある。
#
# 実 MPD (MusicPlayerDaemon/MPD, WebFetchではなく raw ソースを直接取得して確認) の
# src/client/Idle.cxx `Client::IdleNotify()` は
#     const unsigned flags = idle_flags & idle_subscriptions;
#     idle_flags &= ~idle_subscriptions;
# と、購読中(今回 idle に渡された SUBSYSTEMS)のビットだけを `idle_flags` から
# 消費する。購読していない(=今回報告しなかった)イベントのビットは `idle_flags` に
# 残り続け、次回そのサブシステムを購読する idle 呼び出しがあった時点で報告される。
# つまり `idle_flags` はクライアント接続の生存期間ずっと持続する蓄積ビットマスクで
# あり、一部を報告したからといって全体がクリアされることは無い。
# src/client/Process.cxx の `noidle` 処理 (`idle_waiting = false; WriteOK();`) も
# `idle_flags` には一切触れない — つまり `noidle` で待機を打ち切っても蓄積済み
# イベントは失われない。
#
# rmpc (mierak/rmpc) の rmpc-mpd `send_idle()` は用途に応じて単一サブシステムだけを
# 指定した `idle {subsystem}` (例: DB 更新完了待ちループ中は `idle update` のみ) を
# 送ることがある (rmpc/src/shared/mpd_client_ext.rs 等)。この待機中に mopidy 側で
# `player`/`mixer` 等の別イベントが同時発生すると、mopidy_mpd は `update` だけを
# 報告した上で `player`/`mixer` イベントごと握りつぶしてしまい、rmpc が通常の
# 全サブシステム idle へ戻った後も既に「消費済み」扱いのそのイベントには
# 気付けず、次に何か別の変化が起きるまで再生状態/音量表示が古いまま停滞しうる
# (取りこぼし)。
#
# 修正: 3箇所とも「報告した(= 積集合の)サブシステムだけを `context.events` から
# 差し引く」(`noidle()` は元々 `idle_flags` に触れない実 MPD に合わせ、
# `context.events` のクリア自体をやめる) に変更する。`context.subscriptions` は
# 実 MPD の `idle_subscriptions` 同様、次の idle 呼び出しごとに上書きされる
# 一時的な値であり、丸ごとクリアのままで実害は無いため変更しない。

dp = "mopidy_mpd/dispatcher.py"
s = open(dp).read()

MARKER_D = "# mpdidleconsume: 報告済みイベントのみ差し引く"
if MARKER_D in s:
    print("dispatcher.py already patched, skip")
else:
    old_handle_idle = (
        "        response.append(\"OK\")\n"
        "        self.context.subscriptions = set()\n"
        "        self.context.events = set()\n"
        "        self.context.session.send_lines(response)\n"
    )
    assert s.count(old_handle_idle) == 1, f"old_handle_idle count={s.count(old_handle_idle)}"
    new_handle_idle = (
        "        response.append(\"OK\")\n"
        "        self.context.subscriptions = set()\n"
        "        # mpdidleconsume: 報告済みイベントのみ差し引く (実MPD Idle.cxx\n"
        "        # IdleNotify() の idle_flags &= ~idle_subscriptions と同じく、\n"
        "        # 未購読で報告していないイベントは次回まで持ち越す)\n"
        "        self.context.events -= subsystems\n"
        "        self.context.session.send_lines(response)\n"
    )
    assert new_handle_idle != old_handle_idle
    s = s.replace(old_handle_idle, new_handle_idle, 1)
    open(dp, "w").write(s)
    print("patched dispatcher.py: handle_idle() が未報告イベントまで全消去する不具合を修正")

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER_S = "# mpdidleconsume: 報告済みイベントのみ差し引く"
if MARKER_S in s:
    print("status.py already patched, skip")
else:
    old_idle_tail = (
        "    response = []\n"
        "    context.events = set()\n"
        "    context.subscriptions = set()\n"
        "\n"
        "    for subsystem in active:\n"
        "        response.append(f\"changed: {subsystem}\")\n"
        "    return response\n"
    )
    assert s.count(old_idle_tail) == 1, f"old_idle_tail count={s.count(old_idle_tail)}"
    new_idle_tail = (
        "    response = []\n"
        "    # mpdidleconsume: 報告済みイベントのみ差し引く (実MPD Idle.cxx\n"
        "    # IdleNotify() の idle_flags &= ~idle_subscriptions と同じく、\n"
        "    # 未購読で報告していないイベントは次回まで持ち越す)\n"
        "    context.events -= active\n"
        "    context.subscriptions = set()\n"
        "\n"
        "    for subsystem in active:\n"
        "        response.append(f\"changed: {subsystem}\")\n"
        "    return response\n"
    )
    assert new_idle_tail != old_idle_tail
    s = s.replace(old_idle_tail, new_idle_tail, 1)

    old_noidle = (
        "    if not context.subscriptions:\n"
        "        return\n"
        "    context.subscriptions = set()\n"
        "    context.events = set()\n"
    )
    assert s.count(old_noidle) == 1, f"old_noidle count={s.count(old_noidle)}"
    new_noidle = (
        "    if not context.subscriptions:\n"
        "        return\n"
        "    context.subscriptions = set()\n"
        "    # mpdidleconsume: 実MPD Process.cxx の noidle 処理 (idle_waiting=false\n"
        "    # にするのみ) は idle_flags に一切触れないため、events は消さない\n"
        "    # (蓄積済みイベントは次の idle 呼び出しへ持ち越す)\n"
    )
    assert new_noidle != old_noidle
    s = s.replace(old_noidle, new_noidle, 1)

    open(sp, "w").write(s)
    print(
        "patched status.py: idle()/noidle() が未報告/未キャンセル分のイベントまで "
        "全消去する不具合を修正"
    )
