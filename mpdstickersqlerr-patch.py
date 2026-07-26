# mopidy_mpd/protocol/stickers.py の sticker get/set/delete/list/find/inc/dec/
# stickernames/stickernamestypes はいずれもコマンド呼び出しごとに `sqlite3.connect()` で
# 新規接続を開き、共有ファイル `<data_dir>/mpd/sticker.db` へ直接 execute()/commit() する。
# 他の共有可変状態 (volume/output/partition/channel/mount/uri_mapper) はプロセス内 Lock で
# 直列化されているのに対し、sticker.db への書き込みは複数クライアントが独立した sqlite3
# 接続で同時にアクセスするため、SQLite 自身のファイルロック競合が起きうる。この場合
# sqlite3 モジュールは `sqlite3.OperationalError: database is locked` (あるいはディスク
# 満杯等の他の `sqlite3.Error` 系) を素で送出するが、呼び出し元のどこにも
# `sqlite3.Error` を捕捉する箇所が無く (dispatcher.py の `_catch_mpd_ack_errors_filter` は
# `exceptions.MpdAckError` のみ、`_call_handler_filter` は `pykka.ActorDeadError` のみを
# 捕捉)、未捕捉のまま当該クライアントの MPD セッションが無警告で切断されてしまう
# (サーバ本体は生存、当該コネクションのみ切断)。TODO/既知の軽微な残課題を全項目消化済み
# のため自走エージェントが Explore サブエージェントに未パッチ・薄くしか監査されていない
# 領域の横断調査を委任し新規発見した項目 (mpdstickerincoverflow-patch.py の
# OverflowError 修正と同種の「sqlite3 起因の生例外が未捕捉」パターンだが、原因は
# int の桁数ではなく複数クライアント同時書き込みによるファイルロック競合)。
#
# 修正方針: mopidy_mpd/protocol/playback.py や audio_output.py が volume/output操作の
# 失敗を `exceptions.MpdSystemError(...)` に変換している既存の慣行に倣い、DB へアクセスする
# 8つのヘルパー関数 (_mpd_sticker_list/get/set/delete/find_ext/names/namestypes/inc_dec) を
# デコレータ `_mpd_sticker_guard` でラップし、`sqlite3.Error` を
# `exceptions.MpdSystemError("sticker database error: ...")` に変換する
# (ACK_ERROR_SYSTEM=52、実MPDが読み書き失敗時にsystem errorを返す挙動と整合)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpd_sticker_guard"
if MARKER in s:
    print("sticker sqlite3.Error guard already present, skip")
else:
    old_anchor = (
        "def _mpd_sticker_check_type(field):\n"
        "    if field != _MPD_STICKER_TYPE:\n"
        '        raise exceptions.MpdArgError(f"Unknown sticker domain: {field}")\n'
    )
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"

    new_anchor = old_anchor + (
        "\n"
        "\n"
        "def _mpd_sticker_guard(fn):\n"
        "    # sticker.db は複数クライアントが独立したsqlite3接続で同時に書き込みうるため、\n"
        "    # SQLiteのファイルロック競合 (database is locked 等) がいつでも起こりうる。\n"
        "    # 未捕捉の sqlite3.Error はMPDセッションを無警告切断してしまうため、\n"
        "    # playback.py/audio_output.py の慣行に倣いMpdSystemErrorへ変換する。\n"
        "    def _mpd_sticker_guarded(*args, **kwargs):\n"
        "        try:\n"
        "            return fn(*args, **kwargs)\n"
        "        except sqlite3.Error as e:\n"
        '            raise exceptions.MpdSystemError(f"sticker database error: {e}")\n'
        "    return _mpd_sticker_guarded\n"
    )
    s = s.replace(old_anchor, new_anchor, 1)

    for def_line in (
        "def _mpd_sticker_list(context, field, uri):\n",
        "def _mpd_sticker_get(context, field, uri, name):\n",
        "def _mpd_sticker_set(context, field, uri, name, value):\n",
        "def _mpd_sticker_delete(context, field, uri, name):\n",
        "def _mpd_sticker_find_ext(\n",
        "def _mpd_sticker_names(context):\n",
        "def _mpd_sticker_namestypes(context):\n",
        "def _mpd_sticker_inc_dec(context, field, uri, name, value, sign):\n",
    ):
        assert s.count(def_line) == 1, f"def_line count={s.count(def_line)}: {def_line!r}"
        s = s.replace(def_line, "@_mpd_sticker_guard\n" + def_line, 1)

    open(p, "w").write(s)
    print(
        "patched stickers.py: sticker DB操作8関数を _mpd_sticker_guard でラップし "
        "未捕捉の sqlite3.Error による MPD セッション切断を MpdSystemError へ変換"
    )
