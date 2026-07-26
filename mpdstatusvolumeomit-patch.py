# status の volume フィールドが、ミキサー無し (mixer.get_volume() が None) の時でも
# 常に `volume: -1` を出力してしまう不具合を修正。
#
# 実MPD本体 (gh rawで src/command/PlayerCommands.cxx handle_status() を確認) は
#   const auto volume = partition.mixer_memento.GetVolume(partition.outputs);
#   if (volume >= 0)
#       r.Fmt("volume: {}\n", volume);
# と、ミキサーが無い/取得できない (volume < 0) 場合は volume 行そのものを省略する。
# 単独問い合わせコマンドの getvol (mpdgetvol-patch.py、同じ handle_getvol も
# `if (volume >= 0)` で空応答) は既にこの仕様通りに実装済みで、mpdgetvol-patch.py
# 自身のコメントも「status コマンドの volume: -1 フォールバックとは異なる仕様」と
# 書いていたが、これは実MPD本体のソースを確認せずstatus側の既存動作をそのまま
# 「別仕様」と誤って追認しただけで、実際には両コマンドとも同じ`volume>=0`条件の
# はずだった。xfade (mpdxfadezero-patch.py) がmixrampdelayと同じ
# `if 値 > 0: result.append(...)` パターンへ揃えたのと同種の「兄弟フィールド/
# 兄弟コマンドとの条件付き出力の不揃い」。
#
# rmpc (rmpc-mpd/src/commands/status.rs) の volume は Option<i8> としてパースされ
# 行が無ければ None 扱いになる設計のため、行を省略してもクライアント側への
# 悪影響はない (getvol側の空応答を既に許容している設計と同じ)。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER = "volume = _status_volume(futures)"
if MARKER in s:
    print("statusvolumeomit already patched, skip")
else:
    old_entry = '        ("volume", _status_volume(futures)),\n'
    assert s.count(old_entry) == 1, f"old_entry count={s.count(old_entry)}"
    s = s.replace(old_entry, "", 1)

    old_anchor = (
        "    xfade = _status_xfade(futures)\n"
        "    if xfade > 0:\n"
        '        result.append(("xfade", xfade))\n'
    )
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"
    new_anchor = (
        "    volume = _status_volume(futures)\n"
        "    if volume >= 0:\n"
        '        result.append(("volume", volume))\n'
    ) + old_anchor
    s = s.replace(old_anchor, new_anchor, 1)

    open(sp, "w").write(s)
    print("patched status.py: volume をミキサー無し(-1)時は行省略に変更")
