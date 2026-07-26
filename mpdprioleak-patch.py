# `prio`/`prioid` (mpdprio-patch.py) が tlid -> priority を保存する揮発性ストア
# `_queue_priorities` (translator.py) だけ、キューから曲が消えても掃除されず
# 永久に肥大化するメモリリークが残っていた。TODO 全項目消化済みのため自走
# エージェントが既存の揮発性ストア群 (translator.py/actor.py) を横断調査して
# 発見・追加した項目。
#
# 同じ「tlid をキーにしたキュー内限定の揮発性ストア」である `_queue_added`
# (mpdadded-patch.py)・`_queue_extra_tags`/`_queue_ranges`
# (mpdaddtagid-patch.py/mpdrangeid-patch.py) は、actor.py の
# `MpdFrontend.on_event()` が `tracklist_changed` イベント (delete/deleteid/
# clear/move 等キュー変更全般で発火) を受けるたびに `sync_added()`/
# `sync_extra_tags()`/`sync_ranges()` を呼び、その時点でキューに現存しない
# tlid を破棄している。`_queue_priorities` だけこの sync 相当が存在せず、
# `set_priority()` は明示的に priority=0 (`prioid ID 0` 等でのリセット) で
# 呼ばれたときしかエントリを pop しない。
#
# 再現: `prio 50 "0:N"` で複数曲に優先度を設定 → その曲を `delete`/`clear`/
# `deleteid` でキューから除去 (0リセットせずに除去) → `_queue_priorities` には
# 除去済みの tlid がエントリとして居座り続ける。mopidy core の tlid はプロセス
# 内で単調増加し再利用されないため、誤った優先度表示のような実害はないが
# (再利用されたtlidへ古いPrioが化けて出る心配はない)、prio+delete/clear を
# 繰り返すたびに `_queue_priorities` が無限に肥大化する「純粋なメモリリーク」
# であり、長時間稼働するプロセスでは看過できない不備と判断した。
#
# 修正: `_queue_added`/`_queue_extra_tags`/`_queue_ranges` と対称に、
# translator.py に `sync_priorities(current_tlids)` を追加し、actor.py の
# `_sync_added_timestamps`/`_sync_extra_tags`/`_sync_ranges` と並べて
# `_sync_priorities()` を新設、`on_event` の `tracklist_changed` 分岐に追加する。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "def sync_priorities"
if MARKER_T in t:
    print("translator.py already patched for priority leak, skip")
else:
    anchor = "def get_priority(tlid):\n    return _queue_priorities.get(tlid, 0)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    new_block = anchor + (
        "\n"
        "\n"
        "def sync_priorities(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_priorities if t not in current]:\n"
        "        del _queue_priorities[tlid]\n"
    )
    t = t.replace(anchor, new_block, 1)
    open(tp, "w").write(t)
    print("patched translator.py: sync_priorities を追加")

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER_A = "_sync_priorities"
if MARKER_A in a:
    print("actor.py already patched for priority leak, skip")
else:
    old_event = (
        '        if event == "tracklist_changed":\n'
        "            self._sync_added_timestamps()\n"
        "            self._sync_extra_tags()\n"
        "            self._sync_ranges()\n"
    )
    assert a.count(old_event) == 1, f"old_event count={a.count(old_event)}"
    new_event = old_event.replace(
        "            self._sync_ranges()\n",
        "            self._sync_ranges()\n            self._sync_priorities()\n",
    )
    assert new_event != old_event
    a = a.replace(old_event, new_event, 1)

    anchor_method = (
        "    def _sync_ranges(self):\n"
        "        # rangeid 用のtlid->レンジストアからキューに存在しなくなった\n"
        "        # tlidを掃除する (実MPD同様、曲がキューから消えたら部分再生の\n"
        "        # 指定も消える揮発性のため)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_ranges([tlid for tlid, _track in tl_tracks])\n"
    )
    assert a.count(anchor_method) == 1, f"anchor_method count={a.count(anchor_method)}"
    new_method = anchor_method + (
        "\n"
        "    def _sync_priorities(self):\n"
        "        # prio/prioid 用のtlid->優先度ストアからキューに存在しなく\n"
        "        # なったtlidを掃除する (delete/clear等で除去された曲のPrioが\n"
        "        # 無期限に居座りメモリリークするのを防ぐ)。\n"
        "        tl_tracks = self.core.tracklist.get_tl_tracks().get()\n"
        "        translator.sync_priorities([tlid for tlid, _track in tl_tracks])\n"
    )
    a = a.replace(anchor_method, new_method, 1)
    open(ap, "w").write(a)
    print("patched actor.py: tracklist_changed で消えたtlidのPrioを掃除")
