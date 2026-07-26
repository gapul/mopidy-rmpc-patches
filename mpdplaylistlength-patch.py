# `playlistlength {NAME}` (musicpd.org protocol, stored playlists section、
# MPD 0.24+ で追加。ストアドプレイリストの曲数/総再生時間だけを軽量に返す。
# `count`/`stats` の per-playlist 版に相当) が mopidy-mpd 3.3.0 にはコマンド自体
# 丸ごと存在せず常に `ACK Unknown command` になる件: TODO/既知の軽微な残課題を
# 全項目消化済みのため自走エージェントが mopidy_mpd の再洗い出しでは新規発見が
# 尽きたため mpd.readthedocs.io の protocol リファレンスを実際に fetch し、
# 実装済みコマンド一覧 (`@protocol.commands.add(...)` を全 grep) と全文照合して
# 差分を選定 (searchcount/outputset/getfingerprint/playlistlength/searchplaylist/
# protocol の6件が未実装と判明)。rmpc 本体 (mierak/rmpc) を実際に clone して
# grep したが、いずれも rmpc 自身は送信しない (rmpc は `playlistlength` フィールドを
# 含む `status` 応答は解釈するが、同名のこのコマンド自体は使わない) と確認した上で、
# mpdlistfiles-patch.py/mpdstickernames-patch.py 等と同種の「rmpc固有ではなく
# 標準 MPD プロトコル準拠の不備 (mpc/ncmpcpp 等の互換性)」として選定。
# 実装が本質的に必要とする getfingerprint(要libchromaprint、mopidyのリモート
# バックエンドでは経路が存在しない)/outputset(mopidyのaudio output抽象に
# runtime attributeの概念が無い)/protocol(サブコマンドでコマンド可視性自体を
# 動的に変える大掛かりな機能でdispatcherの権限モデルに触れる)/searchcount・
# searchplaylist(既存の肯定/否定フィルタ演算子機構(mpdfilterkind-patch.py等)
# との整合を要し1回のパッチとしては範囲が広い)より、既存の `_get_playlist`
# ヘルパ(listplaylist/listplaylistinfoが使用)だけで完結し外部依存が無い
# `playlistlength` を今回のスコープとした。
#
# 実 MPD 仕様 (WebFetch で mpd.readthedocs.io/protocol.html を確認済み):
#   playlistlength {NAME}
#     Count the number of songs and their total playtime (seconds) in the
#     playlist.
#   応答フィールドは count/stats/mpdcount-patch.py の非group応答と全く同じ
#   `songs: N` / `playtime: T` のペア。NAME が存在しない場合のエラーは
#   listplaylist/listplaylistinfo と同じ `_get_playlist(context, name)`
#   (must_exist=True) が投げる既存の `MpdNoExistError("No such playlist")`
#   をそのまま流用する (実MPDも同様に "No such playlist" を返す)。
#
# 修正方針: mpdcount-patch.py の非group応答生成ロジック (`t.length` の合計を
# 秒へ丸めるだけ) を、DB全体ではなく `_get_playlist` が返す1プレイリストの
# `tracks` に対して適用するだけの新規コマンドを追加する。
#
# 実機検証で判明した罠: `_get_playlist` (= `context.core.playlists.lookup(uri)`)
# が返す Track は listplaylist が使う分には十分だが、実際には length が
# 常に None/0 の軽量版で、listplaylistinfo が別途 `context.core.library.lookup()`
# で本物の Track (length 込み) に差し替えているのはタグ表示のためだけでなく
# 曲長を得るためにも必須だったと実機で確認 (最初の実装では playlist.tracks を
# 直接使ったところ songs は正しいが playtime が常に 0 になった)。そのため
# playlistlength も listplaylistinfo と同じ library.lookup() 差し替えを行う。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

MARKER = '@protocol.commands.add("playlistlength")'
if MARKER in s:
    print("playlistlength already present in stored_playlists.py, skip")
else:
    anchor = (
        '@protocol.commands.add("listplaylists")\n'
        "def listplaylists(context):\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"

    new_command = (
        '@protocol.commands.add("playlistlength")\n'
        "def playlistlength(context, name):\n"
        '    """\n'
        "    *musicpd.org, stored playlists section:*\n"
        "\n"
        "        ``playlistlength {NAME}``\n"
        "\n"
        "        Count the number of songs and their total playtime (seconds) in\n"
        "        the playlist.\n"
        "\n"
        "    .. versionadded:: 0.24\n"
        "        New in MPD protocol version 0.24\n"
        '    """\n'
        "    playlist = _get_playlist(context, name)\n"
        "    track_uris = [track.uri for track in playlist.tracks]\n"
        "    tracks_map = context.core.library.lookup(uris=track_uris).get()\n"
        "    tracks = []\n"
        "    for uri in track_uris:\n"
        "        tracks.extend(tracks_map[uri])\n"
        "    total_length = sum(t.length for t in tracks if t.length)\n"
        "    return [\n"
        '        ("songs", len(track_uris)),\n'
        '        ("playtime", int(total_length / 1000)),\n'
        "    ]\n"
        "\n"
        "\n"
    )
    s = s.replace(anchor, new_command + anchor, 1)
    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: playlistlength を実装 "
        "(ストアドプレイリストの songs/playtime を返す、MPD0.24+)"
    )
