# `sticker set`/`sticker delete` (mpdsticker-patch.py) が idle "sticker" イベントを一切
# 発火しない件。実 MPD (MusicPlayerDaemon/MPD src/command/StickerCommands.cxx
# handle_sticker_song / src/protocol/IdleFlags.cxx IDLE_STICKER) を実際に clone して
# ソース確認したところ、実MPDは sticker set/delete 成功時に必ず idle "sticker" を発火する
# 仕様と判明。一方 mopidy_mpd 3.3.0 (+ mpdsticker-patch.py) の実装は書き込み成功時に一切
# 通知を送らず、status.py の SUBSYSTEMS にも "sticker" 自体が登録されていないため、bare
# `idle` は元より明示的な `idle sticker` を送っても以後二度と `changed: sticker` が来ない。
#
# rmpc 本体 (mierak/rmpc) を実際に clone して調査したところ、rmpc-mpd/src/commands/idle.rs
# の IdleEvent に Sticker バリアントが存在し、rmpc/src/core/event_loop.rs の
# handle_idle_event が IdleEvent::Sticker 受信時に ctx.stickers_supported が真なら
# 表示中の全曲の sticker (rating/like 等、rmpc/src/ctx.rs の RATING_STICKER/LIKE_STICKER)
# を GLOBAL_STICKERS_UPDATE として再フェッチし、rmpc/src/ui/mod.rs で UiEvent::Sticker として
# 画面へ反映する実装であることを確認した。また rmpc/src/core/client.rs の主イベントループは
# `client.enter_idle(None)` (bare idle、SUBSYSTEMSの既定集合を購読) を使うため、
# status.py 側に "sticker" が登録されていないとサーバーはそもそも sticker 変更を
# 購読対象に含めない。つまり、あるクライアント(または rmpc 自身の別画面/別接続)が
# rating/like スティッカーを更新しても、他の rmpc 接続の一覧表示は idle 経由では
# 永久に再フェッチされない実害あるギャップ。TODO 全項目消化済みのため自走エージェントが
# 調査して新規発見・追加した項目。
#
# 実装: mpdmount-patch.py/mpdchannels-patch.py と全く同じ機構
# (mopidy.listener.send(session.MpdSession, "sticker")、pykka の .tell() 経由で
# スレッドセーフに全セッションへブロードキャスト) を再利用し、sticker set/delete が
# 実際に成功した (例外を投げなかった) 場合のみ通知する。status.py の SUBSYSTEMS に
# "sticker" を追加して bare `idle` でも拾えるようにする。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpdsticker_notify"
if MARKER in s:
    print("sticker idle notification already present, skip")
else:
    old_import = "from mopidy_mpd import exceptions, protocol\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = old_import + (
        "\n"
        "def _mpdsticker_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と全く同じ理由・機構)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        "    listener.send(mpd_session.MpdSession, \"sticker\")\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_dispatch = (
        '    elif action == "set":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_set(context, field, uri, rest[0], rest[1])\n"
        "        return None\n"
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        return None\n"
    )
    assert s.count(old_dispatch) == 1, f"old_dispatch count={s.count(old_dispatch)}"
    new_dispatch = (
        '    elif action == "set":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_set(context, field, uri, rest[0], rest[1])\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    s = s.replace(old_dispatch, new_dispatch, 1)

    open(p, "w").write(s)
    print("patched stickers.py: sticker set/delete で idle 'sticker' 通知を発火")

stp = "mopidy_mpd/protocol/status.py"
s2 = open(stp).read()

MARKER2 = '"sticker",\n    "stored_playlist"'
if MARKER2 in s2:
    print("status.py already patched, skip")
else:
    old_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "options",\n'
        '    "output",\n'
        '    "partition",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]\n"
    )
    assert s2.count(old_subsystems) == 1, f"old_subsystems count={s2.count(old_subsystems)}"
    new_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "options",\n'
        '    "output",\n'
        '    "partition",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "sticker",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]\n"
    )
    s2 = s2.replace(old_subsystems, new_subsystems, 1)
    open(stp, "w").write(s2)
    print("patched status.py: SUBSYSTEMS に sticker を追加 (bare idle も拾う)")
