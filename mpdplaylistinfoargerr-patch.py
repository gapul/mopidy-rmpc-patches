# `playlistinfo [SONGPOS | START:END]` に不正な引数 (非数値 `playlistinfo "abc"`、
# `-1` 以外の負数、`START >= END` の逆順レンジ `playlistinfo "5:2"`、開始のみ空の
# `playlistinfo ":5"` 等) を渡すと `mopidy_mpd/protocol/current_playlist.py` の
# `playlistinfo()` 内で手動パースしている `protocol.RANGE(parameter)` が素の
# `ValueError` を送出し、捕捉されずに MPD セッションが切断されてしまう不具合
# (サーバ本体は生存、当該コネクションのみ切断)。
#
# mpdseekcurargerr-patch.py (`seekcur`) と全く同じパターン: `delete`/`move`/
# `shuffle`/`listplaylist`/`listplaylistinfo`/`load`/`playlistdelete`/
# `playlistmove` は `songrange=protocol.RANGE` のようにデコレータの引数バリデータ
# として宣言しているため `Commands.add.<locals>.validate()` の
# `except ValueError: raise exceptions.MpdArgError(...)` に保護されるが、
# `playlistinfo` は `parameter` が省略可能 (`None`/`"-1"` で全件表示) なため
# デコレータの型宣言だけでは表現できず、関数本体で手動パースしており保護を
# 受けられない。同じファイル内の `prio()` は同型の手動パース箇所を
# try/except で既に保護済みであり、`playlistinfo()` だけがこの保護漏れ。
#
# 修正: `protocol.RANGE(parameter)` の呼び出しを `prio()` と同じ流儀で
# try/except し、`ValueError` を `exceptions.MpdArgError("incorrect
# arguments")` に変換する。

p = "mopidy_mpd/protocol/current_playlist.py"
s = open(p).read()

NEW = (
    '    if parameter is None or parameter == "-1":\n'
    "        start, end = 0, None\n"
    "    else:\n"
    "        try:\n"
    "            tracklist_slice = protocol.RANGE(parameter)\n"
    "        except ValueError:\n"
    '            raise exceptions.MpdArgError("incorrect arguments")\n'
    "        start, end = tracklist_slice.start, tracklist_slice.stop\n"
)

if NEW in s:
    print("playlistinfo() arg-error guard already patched, skip")
else:
    OLD = (
        '    if parameter is None or parameter == "-1":\n'
        "        start, end = 0, None\n"
        "    else:\n"
        "        tracklist_slice = protocol.RANGE(parameter)\n"
        "        start, end = tracklist_slice.start, tracklist_slice.stop\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched current_playlist.py: playlistinfoの不正な引数(非数値/逆順"
        "レンジ等)が素のValueErrorでMPDセッションを切断してしまう不具合を"
        "修正 (ACK incorrect argumentsへ)"
    )
