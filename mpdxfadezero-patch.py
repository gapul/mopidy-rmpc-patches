# mpdcrossfade-patch.py が実装した `status` の `xfade` フィールドは、値が 0
# (crossfade未設定/リセット後の既定状態) でも常に `xfade: 0` を出力してしまう。
#
# 実MPD本体 (src/command/PlayerCommands.cxx の handle_status()) は、兄弟フィールド
# mixrampdelay (mpdmixramp-patch.py で対応済み、値が0より大きい時のみ出力) と全く
# 同じパターンで、crossfade も
#
#   if (pc.GetCrossFade() > FloatDuration::zero())
#       r.Fmt(COMMAND_STATUS_CROSSFADE ": {}\n", ...);
#
# と、値が0より大きい時だけ `xfade` 行を出力し、既定値0では行そのものを省略する。
# この分岐は少なくとも v0.21.26 から現行masterまで一貫した長期安定仕様。
# mpdmixramp-patch.py 自身のコメントは「crossfadeは対応済み」と述べていたが、
# その「対応済み」の中身(常時出力)自体が実MPD仕様と食い違っており、
# mixrampdelay側だけ条件付き出力に直され、xfade側の対応漏れが残っていた。
#
# rmpc (rmpc-mpd/src/commands/status.rs) の xfade は Option<u32> としてパースされ
# 行が無ければ None 扱いになる設計のため、行を省略してもクライアント側への
# 悪影響はない。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER = "xfade = _status_xfade(futures)"
if MARKER in s:
    print("xfadezero already patched, skip")
else:
    old_entry = '        ("xfade", _status_xfade(futures)),\n'
    assert s.count(old_entry) == 1, f"old_entry count={s.count(old_entry)}"
    s = s.replace(old_entry, "", 1)

    old_anchor = (
        '    mixrampdelay = _status_mixrampdelay(futures)\n'
        "    if mixrampdelay > 0:\n"
        '        result.append(("mixrampdelay", mixrampdelay))\n'
    )
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"
    new_anchor = (
        "    xfade = _status_xfade(futures)\n"
        "    if xfade > 0:\n"
        '        result.append(("xfade", xfade))\n'
    ) + old_anchor
    s = s.replace(old_anchor, new_anchor, 1)

    open(sp, "w").write(s)
    print("patched status.py: xfade を mixrampdelay と同じ >0 の時のみ出力に変更")
