# mopidy-mpd 3.3.0 の現行キュー `move`(current_playlist.py の move_range())は
# `FROM` が開放端レンジ(`"N:"`、または mpdrangeminusone-patch.py 導入後は裸の
# `"-1"`も同様に slice(0, None) へ正規化される)でも一切拒否せず、暗黙に
# キュー末尾までとして受理してしまう。TODO 全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体(gh rawで src/command/QueueCommands.cxx handle_move() を確認)は
# レンジをパースした直後、TOの解決より前に
#   if (range.IsOpenEnded()) {
#       r.Error(ACK_ERROR_ARG, "Open-ended range not supported");
#       return CommandResult::ERROR;
#   }
# と明示的に拒否する(`delete`/`shuffle`は同ファイルの handle_delete/
# handle_shuffle で ParseOptional(..., RangeArg::All()) を使い open-ended を
# 意図的に許容しており、`move` だけが拒否対象という非対称は実MPD自身の仕様通り)。
# 兄弟コマンド `playlistmove`(stored_playlists.py)は mpdplaylistrange-patch.py
# で既にこの拒否を実装済みだが、現行キューの `move` は
# mpdrangeminusone-patch.py 自身が「本パッチはその既存ポリシーを変更せず…
# 新たな非対称は生まない」と明記した通り、意図的に据え置かれたまま残っていた。
#
# rmpc本体(mierak/rmpc)を確認したところ rmpc-mpd/src/single_or_range.rs の
# SingleOrRange は常に有界な RangeInclusive/単一indexしか構築せず、rmpcの
# キューペインの移動操作は現状この経路を踏まない。それでも実MPDとの明確な
# プロトコル非準拠(実MPDならACKになるところをmopidyは黙って成功させる)であり、
# 将来のクライアント/手動テストで無音の誤動作を招きうるため修正する。
# BACKLOG.md全体を `IsOpenEnded`/`Open-ended`/`move_range` で検索し、
# playlistmove側の対応(mpdplaylistrange-patch.py)以外にこの現行キュー`move`の
# 開放端拒否を実装した既存項目が無いことを確認済み。

pp = "mopidy_mpd/protocol/current_playlist.py"
s = open(pp).read()

MARKER = "``TO`` in the playlist. Open-ended ranges (``START:``) are not\n        supported here, matching real MPD."
if MARKER in s:
    print("move open-ended range already patched, skip")
else:
    old = (
        '@protocol.commands.add("move", songrange=protocol.RANGE, to=_mpd_move_to)\n'
        "def move_range(context, songrange, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``move [{FROM} | {START:END}] {TO}``\n"
        "\n"
        "        Moves the song at ``FROM`` or range of songs at ``START:END`` to\n"
        "        ``TO`` in the playlist.\n"
        "\n"
        "        ``TO`` may be relative to the current song: ``+N`` moves right\n"
        "        after the current song (``+0`` = directly after), ``-N`` moves\n"
        "        right before it (``-0`` = directly before).\n"
        '    """\n'
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    version = context.core.tracklist.get_version().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    if start == end:\n"
        "        return\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"

    new = (
        '@protocol.commands.add("move", songrange=protocol.RANGE, to=_mpd_move_to)\n'
        "def move_range(context, songrange, to):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``move [{FROM} | {START:END}] {TO}``\n"
        "\n"
        "        Moves the song at ``FROM`` or range of songs at ``START:END`` to\n"
        "        ``TO`` in the playlist. Open-ended ranges (``START:``) are not\n"
        "        supported here, matching real MPD.\n"
        "\n"
        "        ``TO`` may be relative to the current song: ``+N`` moves right\n"
        "        after the current song (``+0`` = directly after), ``-N`` moves\n"
        "        right before it (``-0`` = directly before).\n"
        '    """\n'
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        '        raise exceptions.MpdArgError("Open-ended range not supported")\n'
        "    version = context.core.tracklist.get_version().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    if start == end:\n"
        "        return\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert new != old
    s = s.replace(old, new, 1)

    open(pp, "w").write(s)
    print(
        "patched current_playlist.py: move の FROM に開放端レンジ拒否 "
        "(playlistmove と同じ Open-ended range not supported) を追加"
    )
