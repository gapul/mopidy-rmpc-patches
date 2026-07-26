# translator.py の _update_job_id/_db_update_time (update/rescan 用のジョブID採番、
# music_db.py) が、mpdqueuestorerace-patch.py/mpdmountrace-patch.py/
# mpdchannelrace-patch.py/mpdpartitionrace-patch.py が修正した他の揮発性ストアと
# 同じくロック無しで全クライアント接続間 (各々別スレッドのMpdSessionアクター) に
# 共有されたまま残っていた。他の揮発性ストアと違いこちらは dict の走査中変更に
# よる RuntimeError ではなく、`next_update_job_id()` の
#     _update_job_id += 1
# が「読み出し・加算・書き戻し」の複合操作 (単一のアトミックなbytecodeではない)
# であるため、2接続以上が同時に `update`/`rescan` を送ると GIL のスレッド切替が
# 読み出しと書き戻しの間に割り込み、加算が失われるロストアップデートが起きる
# (例: 2接続が同時に呼ぶと本来 N, N+1 になるはずが両方 N を受け取り、かつ
# カウンタ自体も本来より少なく進む)。クラッシュはしないが、`update`/`rescan` の
# 応答 `updating_db: JOBID` が実 MPD 仕様が要求する「呼び出しごとに一意で単調増加」
# ではなくなり、ジョブIDで完了を追跡するクライアントを誤らせうる。TODO/既知の
# 軽微な残課題を全項目消化済みのため自走エージェントが、translator.py の他の
# 揮発性ストア群 (mpdqueuestorerace-patch.py等) と同じ観点で横断調査し新規発見・
# 追加した項目。オフラインの合成テストで sys.setswitchinterval を小さくして
# 実際に8スレッド×2000回の並行呼び出しで duplicate job id が発生することを
# 確認済み (詳細は BACKLOG.md)。
#
# 修正: mpdqueuestorerace-patch.py等と同じ流儀で専用の `threading.RLock()`
# (`_update_lock`) を導入し、`next_update_job_id()`/`get_db_update_time()` を
# `with _update_lock:` で直列化する。

p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "_update_lock = threading.RLock()"
if MARKER in s:
    print("mpdupdatejobrace already applied to translator.py, skip")
else:
    old_block = (
        "# update/rescan (music_db.py) 用のジョブID採番。実 MPD の UpdateService::Enqueue\n"
        "# 相当で1から単調増加する (musicpd.org protocol の updating_db)。mopidy core の\n"
        "# library.refresh() は同期的に完了するため非同期ジョブ管理そのものは不要だが、\n"
        "# 応答値としてのジョブIDは実 MPD 同様に提供する。\n"
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
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "# update/rescan (music_db.py) 用のジョブID採番。実 MPD の UpdateService::Enqueue\n"
        "# 相当で1から単調増加する (musicpd.org protocol の updating_db)。mopidy core の\n"
        "# library.refresh() は同期的に完了するため非同期ジョブ管理そのものは不要だが、\n"
        "# 応答値としてのジョブIDは実 MPD 同様に提供する。全クライアント接続間で共有\n"
        "# されるため、複合操作 (_update_job_id += 1) をRLockで直列化する\n"
        "# (mpdqueuestorerace-patch.py等と同種の不備、mpdupdatejobrace-patch.py)。\n"
        "_update_lock = threading.RLock()\n"
        "_update_job_id = 0\n"
        "_db_update_time = 0\n"
        "\n"
        "\n"
        "def next_update_job_id():\n"
        "    global _update_job_id, _db_update_time\n"
        "    with _update_lock:\n"
        "        _update_job_id += 1\n"
        "        _db_update_time = int(time.time())\n"
        "        return _update_job_id\n"
        "\n"
        "\n"
        "def get_db_update_time():\n"
        "    with _update_lock:\n"
        "        return _db_update_time\n"
    )

    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched translator.py: update/rescan用のジョブID採番(_update_job_id/"
        "_db_update_time)が全クライアント接続間でロック無しに共有され、複合操作の"
        "ロストアップデートで同時update/rescanがduplicate job idを受け取ってしまう"
        "不具合を修正 (threading.RLockで直列化)"
    )
