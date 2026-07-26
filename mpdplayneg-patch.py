# mopidy_mpd/protocol/playback.py の `play [SONGPOS]` が、`SONGPOS` に `-1`
# 以外の負数 (`-2`, `-3`, ...) を渡された場合に `ACK Bad song index` を返さず、
# キュー末尾付近の無関係な曲をサイレントに再生してしまう不具合。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが mopidy_mpd のコード品質を
# 再調査して発見した項目。
#
# `play()` は `songpos == -1` だけを `_play_minus_one()` へ特別扱いする
# (このドキュメント化された `-1` の意味は「一時停止なら再開、停止中で現在曲が
# あればそれを再生、無ければ先頭を再生」という mopidy-mpd 独自の互換仕様)。
# それ以外の `songpos` は素通しして
#   `context.core.tracklist.slice(songpos, songpos + 1).get()[0]`
# に渡される。`mopidy/core/tracklist.py` の `slice()` は素の Python リスト
# スライス (`self._tl_tracks[start:end]`) であり、Python のスライスは負数の
# start/end を「末尾からの相対位置」として解釈し `IndexError` を投げない
# (存在確認済み: `[0,1,2,3,4][-2:-1]` は空にならず `[3]` を返す)。結果、
# 例えば5曲キューに `play "-2"` を送ると、実際には存在しない「-2番目」の曲を
# 拒否する代わりに位置3(末尾から2番目)の無関係な曲をそのまま再生してしまう。
# 一方、範囲外に大きく振れた負数 (`play "-100"`) はスライス結果が空リストに
# なるため既存の `except IndexError` (`[0]` で発生) で正しく
# `ACK Bad song index` になっており、この中間の負数域だけが可観測に
# サイレント破損する非対称な挙動だった。
#
# 実 MPD のドキュメント (musicpd.org) は `SONGPOS` を非負のキュー内位置として
# のみ定義しており、mopidy-mpd 独自の `-1` 拡張以外の負数は無効な範囲外指定と
# 扱うのが実 MPD の `CheckClip`/範囲検証の意図と整合する。他の類似コマンド
# (`swap`/`delete` 等の POS 系) は `protocol.UINT` で負数自体を受理しない設計
# だが、`play` の `songpos` だけ `-1` の特別扱いのため `protocol.INT`
# (符号付き) を使っており、この非対称がガードの抜け穴になっていた。
#
# 修正: `songpos == -1` の直後に `songpos < 0` を判定し、`-1` 以外の負数は
# core への `slice()` 呼び出しに到達させず即座に `ACK Bad song index` を返す。
# `-1` 自体の既存の特別扱いと、非負値の既存の動作 (範囲内なら再生、範囲外なら
# 既存の `except IndexError` 経由で `ACK Bad song index`) は変更しない。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    "    if songpos is None:\n"
    "        return context.core.playback.play().get()\n"
    "    elif songpos == -1:\n"
    "        return _play_minus_one(context)\n"
    "    elif songpos < 0:\n"
    "        # tracklist.slice()は素のPythonリストスライスのため-1以外の負数を\n"
    "        # 素通しするとIndexErrorにならず末尾付近の無関係な曲を再生してしまう\n"
    '        raise exceptions.MpdArgError("Bad song index")\n'
    "\n"
    "    try:\n"
    "        tl_track = context.core.tracklist.slice(songpos, songpos + 1).get()[0]\n"
    "        return context.core.playback.play(tl_track).get()\n"
    "    except IndexError:\n"
    '        raise exceptions.MpdArgError("Bad song index")\n'
)

if NEW in s:
    print("play() negative songpos already patched, skip")
else:
    OLD = (
        "    if songpos is None:\n"
        "        return context.core.playback.play().get()\n"
        "    elif songpos == -1:\n"
        "        return _play_minus_one(context)\n"
        "\n"
        "    try:\n"
        "        tl_track = context.core.tracklist.slice(songpos, songpos + 1).get()[0]\n"
        "        return context.core.playback.play(tl_track).get()\n"
        "    except IndexError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: play()の-1以外の負数songposがtracklist.slice()の"
        "Python負数インデックス解釈でサイレントに無関係な曲を再生してしまう"
        "不具合を修正 (ACK Bad song indexへ)"
    )
