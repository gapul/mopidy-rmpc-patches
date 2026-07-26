# `setvol {VOL}` (mopidy_mpd/protocol/playback.py) が範囲外の VOL (0-100 外、
# 負数含む) をエラーにせず `min(max(0, volume), 100)` で無条件にクランプして
# しまう不具合。実MPD本体 (MusicPlayerDaemon/MPD, WebFetchで直接ソース確認)
# の `src/command/OtherCommands.cxx handle_setvol` は
# `args.ParseUnsigned(0, 100)` を経由し、`src/protocol/ArgParser.cxx
# ParseCommandArgUnsigned(s, max_value)` が `strtoul(s, &endptr, 10)` の後
# `value > max_value` なら `MakeArgError("Number too large")` を投げて
# コマンド自体を拒否する (音量は変更されないまま)。`strtoul` は先頭 `-` を
# 巨大な unsigned 値へラップするため `setvol -5` のような負数も同じ経路で
# 弾かれる。よって `setvol 999`/`setvol -5` は実MPDでは
# `ACK [2@0] {setvol} Number too large` を返し音量は変更前のまま維持される
# のが仕様だが、mopidy_mpd はエラーにならず黙って 100/0 へ丸めてしまう。
#
# 同じファイル内の相対音量変更コマンド `volume {CHANGE}` は既に
# `if change < -100 or change > 100: raise exceptions.MpdArgError(...)` で
# 入力自体を検証してから使っており (クランプするのは "変更後の絶対値" の方)、
# `setvol` だけ入力そのものの範囲チェックを欠いているという非対称性がある。
# `mpdgetvol-patch.py` の検証時点 (BACKLOG.md) では「既存のmopidy-mpd実装
# 通りでエラーにならない」とだけ記録され回帰の有無としてのみ扱われ、実MPD
# 本体のソースとの突き合わせがされていなかったため見落とされていた。
#
# 修正: `MpdArgError("Number too large")` は `mpdaddid-patch.py`/
# `mpdaddpos-patch.py`/`mpdmoveto-patch.py` 等が POSITION の範囲外で既に
# 使っている本リポジトリの既存の流儀に揃える。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

MARKER = "mpdsetvolrange-patch.py: 実MPD"
if MARKER in s:
    print("playback.py setvol already patched (range check), skip")
else:
    old = (
        "    # NOTE: we use INT as clients can pass in +N etc.\n"
        "    value = min(max(0, volume), 100)\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "    # NOTE: we use INT as clients can pass in +N etc.\n"
        "    # mpdsetvolrange-patch.py: 実MPD (ParseCommandArgUnsigned) と同じく\n"
        "    # 範囲外は黙ってクランプせずコマンド自体を拒否する。\n"
        "    if volume < 0 or volume > 100:\n"
        '        raise exceptions.MpdArgError("Number too large")\n'
        "    value = volume\n"
    )
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: setvolが範囲外(0-100外、負数含む)を"
        "黙ってクランプする不具合を修正し実MPD同様ACK Number too largeで拒否するよう変更"
    )
