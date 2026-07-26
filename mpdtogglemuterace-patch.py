# mopidy_mpd/protocol/audio_output.py の `toggleoutput` が
# `context.core.mixer.set_mute(not mute_status)` の戻り値 (pykka の Future) を
# 一度も `.get()` せず、そのまま `success` として `if not success:` の真偽判定に
# 使っている不具合。TODO 全項目消化済みのため自走エージェントが mopidy-mpd 3.3.0
# (アップストリーム由来、mpdoutputpartition-patch.py が周辺の分岐条件を書き換えた
# だけで、この行自体には一度も手を入れていない) のソースを実際に読んで新規発見・
# 追加した項目。
#
# 同じファイル内の `enableoutput`/`disableoutput` はどちらも
# `context.core.mixer.set_mute(True/False).get()` と正しく `.get()` しているのに、
# `toggleoutput` だけ非対称に `.get()` が抜けている。Future オブジェクトは常に
# truthy なため `if not success:` は実際の mute 操作の成否に関わらず絶対に真に
# ならず (`MpdSystemError` が発火しない、という副作用もあるがSoftwareMixerは
# 実質常に成功するため目立たない)、より実害があるのは同期の欠如そのもの:
# mopidy_mpd はハンドラが返った時点でクライアントへ `OK` を返すため、core actor
# 側で実際に mute 状態が反映されるより前に `OK` が届きうる (delete()/prio()/
# move()/swap() 等で既に修正した「.get() 未呼び出しによるOK応答と実状態反映の
# 非同期」と同じバグクラス)。rmpc の Outputs モーダル (`GlobalAction::
# ShowOutputs`) は toggle 直後に `outputs` を再取得して表示を更新するため、
# タイミング次第で古い mute 状態を表示しうる。
#
# 修正: `.get()` を追加して同期化する (mopidy.core.mixer.set_mute() は
# 例外を投げる実装ではないため、追加の例外処理は不要)。
# mpdoutputpartition-patch.py 未適用状態は想定しない (mopidy-env.nix で
# 常に先に適用され、toggleoutput 周辺の分岐条件を書き換えるため)。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

NEW = "        success = context.core.mixer.set_mute(not mute_status).get()\n"

if NEW in s:
    print("toggleoutput() race already patched, skip")
else:
    OLD = "        success = context.core.mixer.set_mute(not mute_status)\n"
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched audio_output.py: toggleoutput()内のset_mute()に"
        ".get()を追加しOK応答前にmute状態反映を同期化 (enableoutput/disableoutputと対称に修正)"
    )
