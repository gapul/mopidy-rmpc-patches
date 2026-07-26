# mopidy-mpd 3.3.0 の `update`/`rescan` (mopidy_mpd/protocol/music_db.py) は、
# 実際の処理を一切せず常に固定で `return {"updating_db": 0}  # TODO` を返すだけの
# スタブ。`status` も `updating_db`/idle の `database`/`update` イベントを一切
# 発火しない。TODO 全項目消化済みのため自走エージェントが rmpc 本体 (mierak/rmpc)
# を実際に clone して調査したところ、rmpc/src/ui/mod.rs の `GlobalAction::Update`/
# `GlobalAction::Rescan` (キーバインド可能なグローバルアクション) が実際に
# `client.update(None)`/`client.rescan(None)` を送信し、`rmpc update`/`rmpc rescan`
# CLI サブコマンド (rmpc/src/core/command.rs) も同じコマンドを送ることを確認。
# さらに rmpc-mpd/src/commands/idle.rs の `IdleEvent::Database`/`IdleEvent::Update`
# ハンドラ (rmpc/src/core/event_loop.rs) が、これらの idle イベント受信時に
# `status`/`currentsong` を再取得して `UiEvent::Database` を発火し、
# directories.rs/playlists.rs/tag_browser.rs/queue.rs/search/mod.rs 等の各ペインが
# 表示中データを再クエリすることを確認した。つまり mopidy_mpd 側が idle
# `database`/`update` を一切発火しない現状では、ユーザーが「データベース更新」を
# キー操作しても rmpc の各ペインは一切再描画されない実害あるギャップと判明。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/OtherCommands.cxx handle_update,
# src/db/update/Service.cxx) を実際に clone してソース確認し仕様を確定 —
# `update`/`rescan` はジョブID (1から単調増加、UpdateService::Enqueue) を
# `updating_db: N` として返し、ジョブの開始・終了で idle `update` を発火、
# 実際にデータベース内容が変化した場合のみ idle `database` を発火する
# (src/Partition.cxx EmitIdle(IDLE_DATABASE))。
#
# 実装: mopidy core の `Core.library.refresh(uri)` (mopidy/core/library.py) を
# 実際に呼び出し、対象スキームの各バックエンドの `LibraryProvider.refresh()` を
# 実行 (mopidy_ytmusic は refresh() 未オーバーライドのため base class の no-op だが、
# mopidy core 自体はパッチ対象外のためこれは妥当な範囲)。ジョブIDは
# lastloadedplaylist/crossfade と同じ流儀で translator.py にモジュールレベルの
# 単調増加カウンタを追加。idle 通知は mount.py の `_mpdmount_notify` と全く同じ機構
# (`mopidy.listener.send(session.MpdSession, subsystem)`) を再利用。refresh() は
# 同期的に完了しジョブの開始/終了が実質同時のため、簡略化として毎回 `update` と
# `database` の両方を無条件に発火する (実際に内容が変化したかまでは検出しない —
# mount/crossfade と同種の割り切り。ytmusic はブラウズのたびに API から取得する
# ライブなバックエンドで恒常的なキャッシュ破棄が必要な場面が乏しいため実害は無く、
# むしろユーザーへの「強制再取得」手段として妥当)。
# `uri` に mopidy の URI 形式 (scheme:...) でない値 (実 MPD 流の素のパスなど) が
# 来た場合、`Core.library.refresh()` 内の `validation.check_uri` が
# `mopidy.exceptions.ValidationError` を送出し得るが、これは MPD ACK エラーではなく
# 捕捉されないと接続がクラッシュしてしまうため、無視して何もせず正常応答する
# (実 MPD も存在しないパスの update を ACK エラーにはしないため方向性は一致)。

pp = "mopidy_mpd/protocol/music_db.py"
s = open(pp).read()

MARKER = "_mpdupdate_notify"
if MARKER in s:
    print("music_db.py already patched, skip")
else:
    old_rescan = '''@protocol.commands.add("rescan")
def rescan(context, uri=None):
    """
    *musicpd.org, music database section:*

        ``rescan [URI]``

        Same as ``update``, but also rescans unmodified files.
    """
    return {"updating_db": 0}  # TODO
'''
    assert s.count(old_rescan) == 1, f"old_rescan count={s.count(old_rescan)}"

    new_rescan = '''def _mpdupdate_notify():
    # session.py への import サイクルを避けるため呼び出し時に遅延import する
    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。
    from mopidy import listener
    from mopidy_mpd import session as mpd_session

    listener.send(mpd_session.MpdSession, "update")
    listener.send(mpd_session.MpdSession, "database")


def _mpdupdate_refresh(context, uri):
    import mopidy.exceptions

    try:
        context.core.library.refresh(uri).get()
    except mopidy.exceptions.ValidationError:
        # uri がスキーム無し (実MPD流の素のパス等) で mopidy の URI 形式として
        # 不正な場合。実 MPD も存在しない/解決不能なパスの update を ACK エラーには
        # しないため、何もせず正常応答する。
        pass


@protocol.commands.add("rescan")
def rescan(context, uri=None):
    """
    *musicpd.org, music database section:*

        ``rescan [URI]``

        Same as ``update``, but also rescans unmodified files.
    """
    _mpdupdate_refresh(context, uri)
    job_id = translator.next_update_job_id()
    _mpdupdate_notify()
    return {"updating_db": job_id}
'''
    assert new_rescan != old_rescan
    s = s.replace(old_rescan, new_rescan, 1)

    old_update = '''@protocol.commands.add("update")
def update(context, uri=None):
    """
    *musicpd.org, music database section:*

        ``update [URI]``

        Updates the music database: find new files, remove deleted files,
        update modified files.

        ``URI`` is a particular directory or song/file to update. If you do
        not specify it, everything is updated.

        Prints ``updating_db: JOBID`` where ``JOBID`` is a positive number
        identifying the update job. You can read the current job id in the
        ``status`` response.
    """
    return {"updating_db": 0}  # TODO
'''
    assert s.count(old_update) == 1, f"old_update count={s.count(old_update)}"

    new_update = '''@protocol.commands.add("update")
def update(context, uri=None):
    """
    *musicpd.org, music database section:*

        ``update [URI]``

        Updates the music database: find new files, remove deleted files,
        update modified files.

        ``URI`` is a particular directory or song/file to update. If you do
        not specify it, everything is updated.

        Prints ``updating_db: JOBID`` where ``JOBID`` is a positive number
        identifying the update job. You can read the current job id in the
        ``status`` response.
    """
    _mpdupdate_refresh(context, uri)
    job_id = translator.next_update_job_id()
    _mpdupdate_notify()
    return {"updating_db": job_id}
'''
    assert new_update != old_update
    s = s.replace(old_update, new_update, 1)

    open(pp, "w").write(s)
    print("patched music_db.py: update/rescan を実装 (library.refresh + idle update/database 通知)")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_update_job_id"
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = "# TODO: special handling of local:// uri scheme\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "# update/rescan (music_db.py) 用のジョブID採番。実 MPD の UpdateService::Enqueue\n"
        "# 相当で1から単調増加する (musicpd.org protocol の updating_db)。mopidy core の\n"
        "# library.refresh() は同期的に完了するため非同期ジョブ管理そのものは不要だが、\n"
        "# 応答値としてのジョブIDは実 MPD 同様に提供する。\n"
        "_update_job_id = 0\n"
        "\n"
        "\n"
        "def next_update_job_id():\n"
        "    global _update_job_id\n"
        "    _update_job_id += 1\n"
        "    return _update_job_id\n"
        "\n"
        "\n"
    )
    t = t.replace(anchor, store + anchor, 1)
    open(tp, "w").write(t)
    print("patched translator.py: update ジョブIDの揮発性カウンタを追加")
