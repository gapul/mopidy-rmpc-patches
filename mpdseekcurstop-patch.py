# mopidy_mpd/protocol/playback.py の `seekcur {TIME}` が、再生中でない (停止中)
# 状態でも無条件で `context.core.playback.seek()` を呼んでしまい、
# `mopidy/core/playback.py` の `seek()` 内部の「`PlaybackState.STOPPED` なら
# 暗黙に `self.play()` する」実装 (429-448行付近) を誘発してしまう不具合。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが mopidy_mpd の
# コード品質を再調査して発見した項目。
#
# 実 MPD (MusicPlayerDaemon/MPD `src/queue/PlaylistControl.cxx`
# `playlist::SeekCurrent`) は
#   if (!playing) throw PlaylistError::NotPlaying();
# を最初に無条件で行い、`playing` (PLAY/PAUSE状態) でなければ (=STOPPEDなら)
# `seekcur` を常に拒否する
# (`PlaylistResult::NOT_PLAYING` は `src/command/CommandError.cxx` の `ToAck()`
# で `ACK_ERROR_PLAYER_SYNC` (ヘッダ定義 55) に写像され、メッセージは
# "Not playing" 固定)。一方 `seek {SONGPOS} {TIME}` / `seekid {SONGID} {TIME}`
# は明示的な SONGPOS/ID を指定するため、対象が現在曲と異なれば内部で
# `play(context, songpos)` を呼んで曲を切り替えてから seek する仕様上の相違が
# あり (これは意図通りで問題ない)、`seekcur` だけが「現在曲基準」という性質上、
# 再生中でないと成立しない操作になっている。
#
# 判定条件は `get_current_tl_track() is None` ではなく `get_state() ==
# PlaybackState.STOPPED` にする必要がある: `mopidy/core/playback.py` の
# `stop()` は `_current_tl_track` を一切クリアしないため、一度でも再生してから
# `stop` した後は `get_current_tl_track()` が非 None のまま残り続ける
# (=前者の判定では停止中でも素通ししてしまう)。一方 `state` は `stop()` で
# 確実に `PlaybackState.STOPPED` になるため、実MPDの `playing` 真偽値
# (PLAY/PAUSE状態かどうか) を過不足なく再現できる。
#
# 実害: rmpc-mpd (`rmpc-mpd/src/mpd_client.rs` `send_seek_current`) はシークバー
# 操作等で実際に `seekcur` を送信する。停止中 (起動直後で一度も再生していない、
# または明示的な `stop` の後) にシーク操作をすると、実 MPD なら
# `ACK [55@0] {seekcur} Not playing` になるところ、mopidy-mpd は `OK` を返した
# 上でサイレントに再生が開始してしまう (現在曲が一度も無い状態ではキュー先頭/
# シャッフル次曲という無関係な曲、既に現在曲がある状態では直前の現在曲が
# 再生されるが、いずれもクライアントが意図しない停止中→再生中への遷移が
# サイレントに起きる点で実害がある)。
#
# 修正: 既存の `current_playlist.py`/`music_db.py`/`stored_playlists.py` が
# 「現在曲が必要な操作」で確立済みの `_MpdPlayerSyncError`
# (`error_code = ACK_ERROR_PLAYER_SYNC`) と同じパターンを playback.py にも
# 導入し、`seekcur` の先頭で `get_state() == PlaybackState.STOPPED` なら core
# への `seek()` 呼び出しに到達させず即座に `ACK Not playing` を返す。
# `seek`/`seekid` の既存動作 (SONGPOS/ID指定で曲切り替えを伴うseek) は変更しない。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    'class _MpdSeekCurPlayerSyncError(exceptions.MpdAckError):\n'
    "    error_code = exceptions.MpdAckError.ACK_ERROR_PLAYER_SYNC\n"
    "\n"
    "\n"
    '@protocol.commands.add("seekcur")\n'
    "def seekcur(context, time):\n"
    '    """\n'
    "    *musicpd.org, playback section:*\n"
    "\n"
    "        ``seekcur {TIME}``\n"
    "\n"
    "        Seeks to the position ``TIME`` within the current song. If prefixed by\n"
    "        '+' or '-', then the time is relative to the current playing position.\n"
    '    """\n'
    "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
    '        # 実MPDのSeekCurrentは`!playing`(PLAY/PAUSE状態でない)を無条件で\n'
    "        # NotPlaying扱いする。ここで弾かないとcore.playback.seek()が\n"
    "        # STOPPED時の暗黙play()を誘発し、クライアントが意図しない\n"
    "        # 停止中->再生中への遷移がサイレントに起きてしまう。\n"
    '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
    "    if time.startswith((\"+\", \"-\")):\n"
    "        position = context.core.playback.get_time_position().get()\n"
    "        position += int(protocol.FLOAT(time) * 1000)\n"
    "        context.core.playback.seek(position).get()\n"
    "    else:\n"
    "        position = int(protocol.UFLOAT(time) * 1000)\n"
    "        context.core.playback.seek(position).get()\n"
)

if NEW in s:
    print("seekcur() not-playing guard already patched, skip")
else:
    OLD = (
        '@protocol.commands.add("seekcur")\n'
        "def seekcur(context, time):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``seekcur {TIME}``\n"
        "\n"
        "        Seeks to the position ``TIME`` within the current song. If prefixed by\n"
        "        '+' or '-', then the time is relative to the current playing position.\n"
        '    """\n'
        "    if time.startswith((\"+\", \"-\")):\n"
        "        position = context.core.playback.get_time_position().get()\n"
        "        position += int(protocol.FLOAT(time) * 1000)\n"
        "        context.core.playback.seek(position).get()\n"
        "    else:\n"
        "        position = int(protocol.UFLOAT(time) * 1000)\n"
        "        context.core.playback.seek(position).get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: seekcurが停止中(state==STOPPED)でも"
        "core.playback.seek()の暗黙play()を誘発しサイレントに"
        "停止中->再生中へ遷移してしまう不具合を修正 (ACK Not playingへ)"
    )
