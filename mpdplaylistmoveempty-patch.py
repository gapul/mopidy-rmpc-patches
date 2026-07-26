# mopidy_mpd/protocol/stored_playlists.py の `playlistmove {NAME} {FROM} {TO}`
# が、FROM が well-formed な空範囲 (`START:END` で `START == END`) のとき、
# 実MPDなら常に無条件で `OK` (no-op) を返すはずが、TO が範囲外だと
# `ACK Bad song index` を誤って返してしまう不具合。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントが(general-purposeサブエージェントへの調査
# 委任を経て)新規発見した項目。
#
# 実MPD本体 (`src/command/PlaylistCommands.cxx` の `handle_playlistmove`) は
#   if (from.IsEmpty() || from.start == to)
#       return CommandResult::OK;
# であり、`IsEmpty()` (`start == end`、well-formedな空範囲) は
# `start == to` と全く対等なOR条件として即座に無条件 OK を返す
# (プレイリストの存在確認・TOの範囲チェックにすら進まない)。
#
# 対して本実装は `start == to_pos` の早期returnしか実装しておらず、
# `start == end` (空範囲) かつ `start != to_pos` のケースではそのまま
# ロック取得・`_get_playlist()`・境界チェック
# `end > len(tracks) or to_pos > len(tracks) - count` (count=0) へ進んでしまう。
# `to_pos > len(tracks)` (TOがプレイリスト長を超える) だと実MPDなら
# `IsEmpty()` により無条件OKのところ、本実装は `ACK Bad song index` を
# 誤って返す。
#
# 同ファイルの兄弟コマンド `move_range()` (current_playlist.py、current
# playlist版move) には既に `if start == end: return` のガードが
# mpdrangeempty-patch.py で追加済みで、同パッチのコメントは「playlistmoveは
# 素のスライス/既存チェックだけでstart==endを正しくno-op扱いできる」と
# 述べていたが、これは誤りだった。`playlistmove()` は素のスライスではなく
# `count = end - start` を使った独自の境界チェックのため、`count == 0` でも
# `to_pos` が範囲外なら誤ってエラーになる、典型的な「兄弟コードパスの
# 取りこぼし」。
#
# 実機再現 (dev mopidy 6601、ストアドプレイリスト "testpl" に3曲):
# `playlistmove "testpl" "0:0" 999` → 本実装は
# `ACK [2@0] {playlistmove} Bad song index`、実MPDなら `IsEmpty()` により
# 無条件で `OK` (無変更)。
#
# 修正方針: `start == to_pos` の早期returnの直後に `start == end` の
# 早期returnを追加し、実MPDの `from.IsEmpty() || from.start == to` と
# 同じOR条件にする (move_range()と同じ流儀)。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

NEW = (
    "    start = from_range.start\n"
    "    end = from_range.stop\n"
    "    if start == to_pos:\n"
    "        # Real MPD skips even the playlist-existence check here.\n"
    "        return\n"
    "    if end is None:\n"
    '        raise exceptions.MpdArgError("Open-ended range not supported")\n'
    "    if start == end:\n"
    "        # Real MPD's from.IsEmpty() also skips the existence/bounds "
    "checks.\n"
    "        return\n"
)

if NEW in s:
    print("playlistmove() start==end no-op guard already patched, skip")
else:
    OLD = (
        "    start = from_range.start\n"
        "    end = from_range.stop\n"
        "    if start == to_pos:\n"
        "        # Real MPD skips even the playlist-existence check here.\n"
        "        return\n"
        "    if end is None:\n"
        '        raise exceptions.MpdArgError("Open-ended range not supported")\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: playlistmove()がFROMがwell-formedな"
        "空範囲(start==end)のときTOが範囲外だと誤ってACK Bad song indexを"
        "返す不具合を修正 (move_range()と同じくstart==endを無条件no-op OKへ)"
    )
