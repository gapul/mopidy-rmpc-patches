# mopidy_mpd/actor.py の `_revert_oneshot` (mpdoneshot-patch.py が追加した、
# single/consume の oneshot モードを対象曲の再生終了後に自動でoffへ戻す処理) が
# `self.core.tracklist.set_single(False)` / `self.core.tracklist.set_consume(False)`
# の戻り値 (pykka の Future) を一度も `.get()` せず投げっぱなしのまま関数を抜けている
# 不具合。TODO 全項目消化済みのため自走エージェントが、既存の `.get()` 抜け修正
# (delete/toggleoutput/moveid/swapid/searchaddpl/clear/consume/random/repeat/single/
# stop 等) と同じ「`context.core.*`/`self.core.*` の裸の Expr 文呼び出し」パターンが
# protocol/*.py 以外にも残っていないか ast (`ast.walk`) で mopidy_mpd/actor.py・
# mopidy_ytmusic/*.py も含めて機械的に再走査し新規発見・追加した項目 (mpdstatesync-
# patch.py 自身のコメントが「周辺パッチ (mpdoneshot-patch.py 等) はこの行自体には
# 手を入れていない」と明記していた通り、actor.py はこれまでの `.get()` 監査の対象外
# だった)。
#
# 同じメソッド内の直前の行 `translator.set_single_state("0")` /
# `translator.set_consume_state("0")` はプロセス内の揮発性ストアへの同期的な代入で
# 即座に反映されるが (status の single/consume フィールドは常にこのストアから
# 返すため `status` 応答自体に見た目の遅れは生じない)、実際に自動再生判断へ使われる
# mopidy core 本体の `Tracklist._single`/`_consume` (get_eot_tlid()/_mark_played() が
# 参照する real boolean) 側は非同期メッセージが core actor のメールボックスで
# 処理されるまで反映されない。他の `context.core.tracklist.set_*()` 呼び出しが
# 全て `.get()` して同期化しているのと非対称であり、理論上はこの反映が完了する前に
# 次の track_playback_ended (連続再生や次曲への遷移) が core actor 側で処理される
# ごく短い時間窓において、oneshot revert がまだ効いていない状態で判定されうる
# (delete()/toggleoutput() 等で既に修正した「`.get()` 未呼び出しによる状態反映の
# 非同期」と同じバグクラス)。
#
# 修正: `.get()` を追加して同期化する (mopidy core の set_single()/set_consume() は
# 事前にプロトコル層で bool 型が保証された `False` 固定値を渡しており
# validation.check_boolean() が実際に例外を投げることはないため、追加の例外処理は
# 不要)。

p = "mopidy_mpd/actor.py"
s = open(p).read()

NEW_SINGLE = "            self.core.tracklist.set_single(False).get()\n"
NEW_CONSUME = "            self.core.tracklist.set_consume(False).get()\n"

if NEW_SINGLE in s and NEW_CONSUME in s:
    print("_revert_oneshot() race already patched, skip")
else:
    OLD_SINGLE = "            self.core.tracklist.set_single(False)\n"
    OLD_CONSUME = "            self.core.tracklist.set_consume(False)\n"
    assert s.count(OLD_SINGLE) == 1, f"OLD_SINGLE count={s.count(OLD_SINGLE)}"
    assert s.count(OLD_CONSUME) == 1, f"OLD_CONSUME count={s.count(OLD_CONSUME)}"
    s = s.replace(OLD_SINGLE, NEW_SINGLE, 1)
    s = s.replace(OLD_CONSUME, NEW_CONSUME, 1)
    open(p, "w").write(s)
    print(
        "patched actor.py: _revert_oneshot()内のset_single(False)/"
        "set_consume(False)に.get()を追加しcore側のsingle/consume反映を同期化 "
        "(他のcontext.core.tracklist.set_*()呼び出しと対称に修正)"
    )
