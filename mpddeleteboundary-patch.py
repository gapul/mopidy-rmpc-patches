# mopidy_mpd/protocol/current_playlist.py の `delete [{POS}|{START:END}]` が、
# 実 MPD なら「範囲が空だが不正ではない」境界ケース (`start == キュー長`) でも
# 一律 `ACK Bad song index` を返してしまう不具合。
#
# 実 MPD (MusicPlayerDaemon/MPD src/queue/PlaylistEdit.cxx DeleteRange +
# src/protocol/RangeArg.hxx CheckClip) をgh api経由で実際に確認したところ、
# `CheckClip(count)` は `start > count` の場合のみ false (ACK BadRange) を返し、
# `start == count` は `end` を `count` へクリップした上で true を返す。続く
# `range.IsEmpty()` (`start >= end`) が真なら例外を投げず単に `return` する
# (=OKのみで実際には何もしない、実害の無い黙示no-op)。
#
# 対してこのコードの `delete()` は `context.core.tracklist.slice(start, end)`
# (Pythonのリストスライス、`mopidy/core/tracklist.py` の `slice()`) の結果が
# 空リストになるケースを「`start > count` (真に範囲外)」「`start == count`
# (境界上の空範囲)」の区別なく一律 `ACK Bad song index` にしてしまっている。
# 例えば3曲キュー(有効位置0-2)に対し `delete "3"` や `delete "3:"` を送ると、
# 実MPDは`OK`(無変更)を返すのにこの実装は`ACK Bad song index`を返す。
# rmpcはキュー末尾のちょうど1つ先を指すdeleteを日常的には送らないが、
# 2クライアントが同じ末尾領域を同時に削除しようとする競合(片方が先に削除して
# キューが縮み、もう片方の`delete "N:"`のNがちょうど新しい長さと一致する)で
# 実際に起こりうる、実MPDとの可観測なプロトコル差異。
#
# 修正: `tl_tracks` が空だった場合、`start > 実際の長さ` のときのみ
# `ACK Bad song index` を投げ、`start == 長さ` (境界上の空範囲) は無変更で
# 正常終了させる (実MPDの CheckClip/IsEmpty と同じ判定に合わせる)。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

NEW = (
    "    tl_tracks = context.core.tracklist.slice(start, end).get()\n"
    "    if not tl_tracks:\n"
    "        if start > context.core.tracklist.get_length().get():\n"
    '            raise exceptions.MpdArgError("Bad song index", command="delete")\n'
    "        return\n"
    "    for (tlid, _) in tl_tracks:\n"
    '        context.core.tracklist.remove({"tlid": [tlid]}).get()\n'
)

if NEW in s:
    print("delete() boundary already patched, skip")
else:
    OLD = (
        "    tl_tracks = context.core.tracklist.slice(start, end).get()\n"
        '    if not tl_tracks:\n'
        '        raise exceptions.MpdArgError("Bad song index", command="delete")\n'
        "    for (tlid, _) in tl_tracks:\n"
        '        context.core.tracklist.remove({"tlid": [tlid]}).get()\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: delete()がstart==キュー長の境界上の"
        "空範囲でも一律ACK Bad song indexを返す不具合を修正 "
        "(start>長さの場合のみエラー、それ以外は無変更でOKへ)"
    )
