# mopidy_mpd/protocol/current_playlist.py の `prio {PRIORITY} {START:END...}` が、
# 実 MPD なら「範囲が空だが不正ではない」境界ケース (`start == キュー長`) でも
# 一律 `ACK Bad song index` を返してしまう不具合。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/QueueCommands.cxx handle_prio →
# src/queue/PlaylistEdit.cxx playlist::SetPriorityRange) をgh api経由で実際に
# 確認したところ、`range.CheckClip(GetLength())` は `start > count` の場合のみ
# false (ACK BadRange) を投げ、`start == count` は `end` を `count` へクリップ
# した上で true を返す。続く `range.IsEmpty()` (`start >= end`) が真なら
# 例外を投げず単に `return` する (=OKのみで実際には何もしない黙示no-op)。
# 兄弟コマンドの `delete [{POS}|{START:END}]` は既にこの区別を実装済み
# (mpddeleteboundary-patch.py) なのに、`prio` にはこの区別が無いまま残っていた
# (発見経緯: mpddeleteboundary-patch.py 適用後の見直しで自走エージェントが
# 兄弟コマンドとの非対称性に新規発見)。
#
# このコードの `prio()` は `context.core.tracklist.slice(start, end)`
# (Pythonのリストスライス) の結果が空リストになるケースを「`start > count`
# (真に範囲外)」「`start == count` (境界上の空範囲)」の区別なく一律
# `ACK Bad song index` にしてしまっている。例えば3曲キュー(有効位置0-2)に
# 対し `prio 50 "3"` や `prio 50 "3:"` を送ると、実MPDは`OK`(無変更)を
# 返すのにこの実装は`ACK Bad song index`を返す。`prio` は複数の
# START:END トークンを列挙できるため、`delete`(単一レンジで即 return)と
# 違い境界上の空レンジは「そのトークンだけ無視して次のトークンへ進む」
# (continue) が正しい対応になる。
#
# 修正: `tl_tracks` が空だった場合、`start > 実際の長さ` のときのみ
# `ACK Bad song index` を投げ、`start == 長さ` (境界上の空範囲) はそのトークンを
# 無視して次のトークンの処理を継続する (実MPDの CheckClip/IsEmpty と同じ判定)。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

NEW = (
    "        tl_tracks = context.core.tracklist.slice(start, end).get()\n"
    "        if not tl_tracks:\n"
    "            if start > context.core.tracklist.get_length().get():\n"
    '                raise exceptions.MpdArgError("Bad song index")\n'
    "            continue\n"
    "        tlids.update(tlid for tlid, _track in tl_tracks)\n"
)

if NEW in s:
    print("prio() boundary already patched, skip")
else:
    OLD = (
        "        tl_tracks = context.core.tracklist.slice(start, end).get()\n"
        "        if not tl_tracks:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "        tlids.update(tlid for tlid, _track in tl_tracks)\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: prio()がstart==キュー長の境界上の"
        "空範囲トークンでも一律ACK Bad song indexを返す不具合を修正 "
        "(start>長さの場合のみエラー、それ以外はそのトークンを無視して継続)"
    )
