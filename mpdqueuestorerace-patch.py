# translator.py の4つの揮発性ストア _queue_priorities (prio/prioid,
# mpdprio-patch.py/mpdprioleak-patch.py)・_queue_added (Added,
# mpdadded-patch.py)・_queue_extra_tags (addtagid/cleartagid,
# mpdaddtagid-patch.py)・_queue_ranges (rangeid, mpdrangeid-patch.py) が、
# mpdurimaprace-patch.py/mpdchannelrace-patch.py/mpdpartitionrace-patch.py が
# 修正した uri_mapper.py/channels.py/partition.py の揮発性ストアと全く同種の
# 不備を抱えたまま残っていた: 全クライアント接続 (各々別スレッドの
# MpdSession アクター) が prio/addtagid/rangeid/add 等のコマンド経由で直接
# 読み書きする一方、actor.py の MpdFrontend (Core本体とは別アクター、
# 別スレッド) が core の tracklist_changed イベント (add/delete/move/clear
# 等キュー変更全般で発火) を受けるたびに `sync_priorities`/`sync_added`/
# `sync_extra_tags`/`sync_ranges` を呼び、
#     for tlid in [t for t in _queue_XXX if t not in current]:
#         del _queue_XXX[tlid]
# という「dict をその場で走査するリスト内包表記」でstale tlidを掃除する。
# ロックが一切無いため、あるスレッドがこの走査を実行中に別スレッドが
# `set_priority`/`stamp_added`/`add_song_tag`/`set_range` で同じ dict へ
# 挿入すると `RuntimeError: dictionary changed size during iteration` が
# 飛ぶ。`RuntimeError` は `exceptions.MpdAckError` のサブクラスではないため
# `dispatcher.py` の `_catch_mpd_ack_errors_filter` に捕捉されず、
# `session.py` にも保護が無いため pykka アクターの外まで伝播し
# `network.LineProtocol.on_failure` に到達、その接続の TCP セッションが
# 問答無用で切断される。トリガ条件は「2本以上の MPD 接続が同時に張られて
# いる」だけで良く (rmpc複数台、あるいはキュー変更を伴う操作
# (add/delete/move/clear等) と prio/addtagid/rangeid の同時実行)、ごく
# ありふれた並行操作で発現する。
#
# 加えて、`get_song_tags(tlid)` は `_queue_extra_tags` の内部dictをコピー
# せずそのまま返しており、呼び出し元の `track_to_mpd_format()`
# (`for extra_tag_type, extra_values in get_song_tags(tlid).items():`、
# playlistinfo/playlistid/find/search/count/currentsong等ほぼ全コマンドが
# 経由する共有関数) がロック解放後にこの生の dict を `.items()` で走査する
# ため、その走査中に別スレッドが同じ tlid へ `addtagid` すると同様に
# `RuntimeError: dictionary changed size during iteration` で切断されうる。
# TODO 全項目消化済みのため自走エージェントが既存の揮発性ストア群
# (translator.py) を横断調査して発見・追加した項目。
#
# 修正: mpdurimaprace-patch.py/mpdchannelrace-patch.py/
# mpdpartitionrace-patch.py と同じ流儀で `threading.RLock()` を1個
# (`_queue_lock`、4ストア共通) 導入し、4ストアの読み書き関数全てを
# `with _queue_lock:` で直列化する。`sync_added()` が同じロック保持中に
# `stamp_added()` を呼ぶため RLock (再入可能) を使う。`get_song_tags()` は
# 追加で `{k: list(v) for k, v in ...}` の浅いコピーを返すよう変更し、
# ロック解放後に呼び出し元がロック外で安全に走査できるようにする。

p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "_queue_lock = threading.RLock()"
if MARKER in s:
    print("mpdqueuestorerace already applied to translator.py, skip")
else:
    old_block = (
        "# prio/prioid (current_playlist.py) 用の揮発性ストア。プロセス再起動で\n"
        "# 消えるのは実 MPD の優先度も同じなので妥当。\n"
        "_queue_priorities = {}\n"
        "\n"
        "\n"
        "def set_priority(tlid, priority):\n"
        "    if priority:\n"
        "        _queue_priorities[tlid] = priority\n"
        "    else:\n"
        "        _queue_priorities.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_priority(tlid):\n"
        "    return _queue_priorities.get(tlid, 0)\n"
        "\n"
        "\n"
        "def sync_priorities(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_priorities if t not in current]:\n"
        "        del _queue_priorities[tlid]\n"
        "\n"
        "\n"
        "# Added (queue内の各曲がキューへ追加された時刻、MPD 0.24+) 用の揮発性\n"
        "# ストア。tlid -> ISO8601文字列。add/addid/findadd/searchadd/load が\n"
        "# その場でstamp_addedを呼び即座に記録し、actor.py の tracklist_changed\n"
        "# イベントハンドラがsync_addedで消えたtlidを破棄する (プロセス再起動で\n"
        "# 消えるのは実 MPD のキュー状態も同じなので妥当)。\n"
        "_queue_added = {}\n"
        "\n"
        "\n"
        "def stamp_added(new_tlids):\n"
        "    if not new_tlids:\n"
        "        return\n"
        "    now = datetime.datetime.now(datetime.timezone.utc).strftime(\n"
        '        "%Y-%m-%dT%H:%M:%SZ"\n'
        "    )\n"
        "    for tlid in new_tlids:\n"
        "        _queue_added.setdefault(tlid, now)\n"
        "\n"
        "\n"
        "def sync_added(current_tlids):\n"
        "    stamp_added(current_tlids)\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_added if t not in current]:\n"
        "        del _queue_added[tlid]\n"
        "\n"
        "\n"
        "def get_added(tlid):\n"
        "    return _queue_added.get(tlid)\n"
        "\n"
        "\n"
        "# addtagid/cleartagid (current_playlist.py) 用の揮発性ストア。\n"
        "# tlid -> {tag_type: [value, ...]}。実MPD同様、曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_extra_tags = {}\n"
        "\n"
        "\n"
        "def add_song_tag(tlid, tag_type, value):\n"
        "    _queue_extra_tags.setdefault(tlid, {}).setdefault(tag_type, []).append(\n"
        "        value\n"
        "    )\n"
        "\n"
        "\n"
        "def clear_song_tag(tlid, tag_type=None):\n"
        "    if tag_type is None:\n"
        "        _queue_extra_tags.pop(tlid, None)\n"
        "        return\n"
        "    tags = _queue_extra_tags.get(tlid)\n"
        "    if not tags:\n"
        "        return\n"
        "    tags.pop(tag_type, None)\n"
        "    if not tags:\n"
        "        _queue_extra_tags.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_song_tags(tlid):\n"
        "    return _queue_extra_tags.get(tlid, {})\n"
        "\n"
        "\n"
        "def sync_extra_tags(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_extra_tags if t not in current]:\n"
        "        del _queue_extra_tags[tlid]\n"
        "\n"
        "\n"
        "# rangeid (current_playlist.py) 用の揮発性ストア。tlid -> (start_ms, end_ms)。\n"
        "# end_ms==0 は「開始のみ指定・無制限」、実MPD同様曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_ranges = {}\n"
        "\n"
        "\n"
        "def set_range(tlid, start_ms, end_ms):\n"
        "    if start_ms or end_ms:\n"
        "        _queue_ranges[tlid] = (start_ms, end_ms)\n"
        "    else:\n"
        "        _queue_ranges.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_range(tlid):\n"
        "    return _queue_ranges.get(tlid)\n"
        "\n"
        "\n"
        "def sync_ranges(current_tlids):\n"
        "    current = set(current_tlids)\n"
        "    for tlid in [t for t in _queue_ranges if t not in current]:\n"
        "        del _queue_ranges[tlid]\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "# prio/prioid・Added・addtagid/cleartagid・rangeid 用の4つの揮発性ストア\n"
        "# (tlidをキーにしたキュー内限定のメタデータ)。全クライアント接続\n"
        "# (各々別スレッドのMpdSessionアクター) が直接読み書きする一方、\n"
        "# actor.py の MpdFrontend (別アクター・別スレッド) も\n"
        "# tracklist_changed イベントでsync_*を呼びstale tlidを走査・削除する\n"
        "# ため、読み書きはRLockで直列化する\n"
        "# (mpdurimaprace-patch.py/mpdchannelrace-patch.py/\n"
        "# mpdpartitionrace-patch.pyと同種の不備、mpdqueuestorerace-patch.py)。\n"
        "_queue_lock = threading.RLock()\n"
        "\n"
        "# prio/prioid (current_playlist.py) 用の揮発性ストア。プロセス再起動で\n"
        "# 消えるのは実 MPD の優先度も同じなので妥当。\n"
        "_queue_priorities = {}\n"
        "\n"
        "\n"
        "def set_priority(tlid, priority):\n"
        "    with _queue_lock:\n"
        "        if priority:\n"
        "            _queue_priorities[tlid] = priority\n"
        "        else:\n"
        "            _queue_priorities.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_priority(tlid):\n"
        "    with _queue_lock:\n"
        "        return _queue_priorities.get(tlid, 0)\n"
        "\n"
        "\n"
        "def sync_priorities(current_tlids):\n"
        "    with _queue_lock:\n"
        "        current = set(current_tlids)\n"
        "        for tlid in [t for t in _queue_priorities if t not in current]:\n"
        "            del _queue_priorities[tlid]\n"
        "\n"
        "\n"
        "# Added (queue内の各曲がキューへ追加された時刻、MPD 0.24+) 用の揮発性\n"
        "# ストア。tlid -> ISO8601文字列。add/addid/findadd/searchadd/load が\n"
        "# その場でstamp_addedを呼び即座に記録し、actor.py の tracklist_changed\n"
        "# イベントハンドラがsync_addedで消えたtlidを破棄する (プロセス再起動で\n"
        "# 消えるのは実 MPD のキュー状態も同じなので妥当)。\n"
        "_queue_added = {}\n"
        "\n"
        "\n"
        "def stamp_added(new_tlids):\n"
        "    if not new_tlids:\n"
        "        return\n"
        "    now = datetime.datetime.now(datetime.timezone.utc).strftime(\n"
        '        "%Y-%m-%dT%H:%M:%SZ"\n'
        "    )\n"
        "    with _queue_lock:\n"
        "        for tlid in new_tlids:\n"
        "            _queue_added.setdefault(tlid, now)\n"
        "\n"
        "\n"
        "def sync_added(current_tlids):\n"
        "    stamp_added(current_tlids)\n"
        "    with _queue_lock:\n"
        "        current = set(current_tlids)\n"
        "        for tlid in [t for t in _queue_added if t not in current]:\n"
        "            del _queue_added[tlid]\n"
        "\n"
        "\n"
        "def get_added(tlid):\n"
        "    with _queue_lock:\n"
        "        return _queue_added.get(tlid)\n"
        "\n"
        "\n"
        "# addtagid/cleartagid (current_playlist.py) 用の揮発性ストア。\n"
        "# tlid -> {tag_type: [value, ...]}。実MPD同様、曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_extra_tags = {}\n"
        "\n"
        "\n"
        "def add_song_tag(tlid, tag_type, value):\n"
        "    with _queue_lock:\n"
        "        _queue_extra_tags.setdefault(tlid, {}).setdefault(\n"
        "            tag_type, []\n"
        "        ).append(value)\n"
        "\n"
        "\n"
        "def clear_song_tag(tlid, tag_type=None):\n"
        "    with _queue_lock:\n"
        "        if tag_type is None:\n"
        "            _queue_extra_tags.pop(tlid, None)\n"
        "            return\n"
        "        tags = _queue_extra_tags.get(tlid)\n"
        "        if not tags:\n"
        "            return\n"
        "        tags.pop(tag_type, None)\n"
        "        if not tags:\n"
        "            _queue_extra_tags.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_song_tags(tlid):\n"
        "    # 呼び出し元 (track_to_mpd_format) がロック解放後にこの戻り値を\n"
        "    # .items() で走査するため、生の内部dict/listを返さずコピーする\n"
        "    # (返さないと走査中の別スレッドのaddtagidでRuntimeErrorになりうる)。\n"
        "    with _queue_lock:\n"
        "        return {\n"
        "            tag_type: list(values)\n"
        "            for tag_type, values in _queue_extra_tags.get(tlid, {}).items()\n"
        "        }\n"
        "\n"
        "\n"
        "def sync_extra_tags(current_tlids):\n"
        "    with _queue_lock:\n"
        "        current = set(current_tlids)\n"
        "        for tlid in [t for t in _queue_extra_tags if t not in current]:\n"
        "            del _queue_extra_tags[tlid]\n"
        "\n"
        "\n"
        "# rangeid (current_playlist.py) 用の揮発性ストア。tlid -> (start_ms, end_ms)。\n"
        "# end_ms==0 は「開始のみ指定・無制限」、実MPD同様曲がキューから消えると\n"
        "# 失われる (volatile、actor.py の tracklist_changed ハンドラが掃除)。\n"
        "_queue_ranges = {}\n"
        "\n"
        "\n"
        "def set_range(tlid, start_ms, end_ms):\n"
        "    with _queue_lock:\n"
        "        if start_ms or end_ms:\n"
        "            _queue_ranges[tlid] = (start_ms, end_ms)\n"
        "        else:\n"
        "            _queue_ranges.pop(tlid, None)\n"
        "\n"
        "\n"
        "def get_range(tlid):\n"
        "    with _queue_lock:\n"
        "        return _queue_ranges.get(tlid)\n"
        "\n"
        "\n"
        "def sync_ranges(current_tlids):\n"
        "    with _queue_lock:\n"
        "        current = set(current_tlids)\n"
        "        for tlid in [t for t in _queue_ranges if t not in current]:\n"
        "            del _queue_ranges[tlid]\n"
    )

    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched translator.py: prio/Added/addtagid/rangeid 用の4揮発性ストアが"
        "全クライアント接続間でロック無しに共有され、他スレッドのtracklist_changed"
        "同期走査中の変更でRuntimeErrorによりセッション切断されてしまう不具合を修正"
        " (threading.RLockで直列化。get_song_tagsは戻り値もコピー化)"
    )
