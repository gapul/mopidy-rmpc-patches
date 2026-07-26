# mopidy_mpd/protocol/current_playlist.py の `clear` と playback.py の
# `consume`/`random`/`repeat`/`single`/`stop` が、core actor への
# `context.core.*(...)` 呼び出しの戻り値 (pykka の Future) を一度も `.get()`
# せず投げっぱなしのまま関数を抜けている不具合。TODO 全項目消化済みのため
# 自走エージェントが、直近の一連の `.get()` 抜け修正 (delete/toggleoutput/
# moveid/swapid/searchaddpl 等) と同種のパターンが他にも残っていないか
# `context.core.*` の全呼び出しを ast (`ast.walk` で `context.core.*(...)` の
# 裸の Expr 文を抽出) で機械的に洗い出す形で調査し新規発見・追加した項目。
#
# current_playlist.py 内の他の全ての `context.core.tracklist.*` 呼び出し
# (add/remove/move/index/get_length 等、計20箇所以上) はどれも `.get()` して
# いるのに `clear()` だけが唯一投げっぱなし。playback.py も同様に next/pause/
# resume/play/seek/mixer.get_volume/set_volume 等は全て `.get()` しているのに
# `consume`/`random`/`repeat`/`single`/`stop` の5箇所だけが投げっぱなしという
# 非対称な実装だったと判明 (mopidy-mpd 3.3.0 アップストリーム由来、周辺パッチ
# (mpdoneshot-patch.py 等) はこの行自体には手を入れていない)。
#
# 実害: mopidy_mpd はハンドラが返った時点でクライアントへ `OK` を返すため、
# 実際に core actor 側で consume/random/repeat/single/再生停止/キュークリアが
# 反映されるより前に `OK` が届きうる (delete()/toggleoutput() 等で既に修正した
# 「.get() 未呼び出しによるOK応答と実状態反映の非同期」と同じバグクラス)。rmpc
# はこれらのモード切替キー (C/Z/R/S 等既定バインド) やクリア操作の直後に
# `status`/`playlistinfo` を再取得して表示を更新するため、タイミング次第で
# 古い状態を表示しうる。
#
# 修正: いずれも `.get()` を追加して同期化するだけでよい (mopidy core の
# clear()/set_consume()/set_random()/set_repeat()/set_single()/playback.stop()
# は STATE が事前にプロトコル層で BOOL/ONOFFONESHOT として検証済みのため
# validation.check_boolean() が実際に例外を投げることはなく、追加の例外処理は
# 不要)。

CP = "mopidy_mpd/protocol/current_playlist.py"
PB = "mopidy_mpd/protocol/playback.py"

cp_src = open(CP).read()
pb_src = open(PB).read()

CP_NEW = "    context.core.tracklist.clear().get()\n"
CP_OLD = "    context.core.tracklist.clear()\n"

PB_REPLACEMENTS = [
    (
        '    context.core.tracklist.set_consume(state != "0")\n',
        '    context.core.tracklist.set_consume(state != "0").get()\n',
    ),
    (
        "    context.core.tracklist.set_random(state)\n",
        "    context.core.tracklist.set_random(state).get()\n",
    ),
    (
        "    context.core.tracklist.set_repeat(state)\n",
        "    context.core.tracklist.set_repeat(state).get()\n",
    ),
    (
        '    context.core.tracklist.set_single(state != "0")\n',
        '    context.core.tracklist.set_single(state != "0").get()\n',
    ),
    (
        "    context.core.playback.stop()\n",
        "    context.core.playback.stop().get()\n",
    ),
]

already_patched = CP_NEW in cp_src and all(new in pb_src for _, new in PB_REPLACEMENTS)

if already_patched:
    print("state-sync race already patched (clear/consume/random/repeat/single/stop), skip")
else:
    assert cp_src.count(CP_OLD) == 1, f"CP_OLD count={cp_src.count(CP_OLD)}"
    cp_src = cp_src.replace(CP_OLD, CP_NEW, 1)
    open(CP, "w").write(cp_src)

    for old, new in PB_REPLACEMENTS:
        assert pb_src.count(old) == 1, f"PB_OLD count={pb_src.count(old)} for {old!r}"
        pb_src = pb_src.replace(old, new, 1)
    open(PB, "w").write(pb_src)

    print(
        "patched current_playlist.py/playback.py: clear()/consume()/random()/"
        "repeat()/single()/stop()に.get()を追加しOK応答前に状態反映を同期化"
        "(他の対称なコマンドと同様の流儀に統一)"
    )
