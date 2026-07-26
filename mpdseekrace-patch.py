# mopidy_mpd/protocol/playback.py の `seek {SONGPOS} {TIME}` に残っていた TOCTOU レース。
# 自走エージェントが TODO/既知の残課題を全項目消化済みのため mopidy_mpd のコード品質を
# 再調査して発見した項目 (mpdcurrentsongrace-patch.py/mpdstatusrace-patch.py が
# status.py/current_playlist.py の currentsong・playlistid・plchanges で修正した
# get_current_tl_track()→tracklist.index() の2段階TOCTOUと全く同型の欠陥が、
# playback.py の seek() だけ同種の対策から漏れて残っていた)。
#
# 旧実装:
#   tl_track = context.core.playback.get_current_tl_track().get()   # 呼び出し1 (playback proxy)
#   if context.core.tracklist.index(tl_track).get() != songpos:      # 呼び出し2 (tracklist proxy)
#       play(context, songpos)
#   context.core.playback.seek(int(seconds * 1000)).get()
#
# `context.core` は単一の pykka actor (mopidy.core.actor.Core) をラップする ActorProxy で、
# `.playback`/`.tracklist` はその Core actor が直接保持する素の Python サブコントローラ
# インスタンスに過ぎない (別actorではない)。そのため `context.core.playback.xxx()` と
# `context.core.tracklist.yyy()` はそれぞれ独立したactorメッセージ往復であり、両者の間で
# 他クライアントの `move`/`swap`/`delete` 等のメッセージが割り込んで処理されうる。
# 割り込むと `tracklist.index(tl_track)` は「割り込み後の (呼び出し時点で最新の) 位置」を
# 返す (該当曲がもはやキューに存在しなければ ValueError を握り潰して None)。結果、
# songpos との一致判定がサイレントに (ACKにもならず) 誤り、意図しない曲へ再生が
# 切り替わる、または逆に必要な切り替えが行われない、という不具合が起こりうる。
#
# rmpc (mierak/rmpc) は seekcur のみを使い seek は送らないが、seek {SONGPOS} {TIME} は
# Droid MPD の使用例がdocstringに明記された標準コマンドであり一般的なMPDクライアントが
# 送りうる。
#
# 修正方針: `mopidy/core/tracklist.py` の `TracklistController.index(tl_track=None,
# tlid=None)` は、`tl_track`/`tlid` を省略すると内部で
# `self.core.playback.get_current_tl_track()` を (別途のactor往復を経ない、同一actor内の
# 素の属性アクセスとして) 呼び出し、そのまま `self._tl_tracks.index(...)` する実装になって
# いる。つまり `context.core.tracklist.index().get()` という引数無し呼び出し1回だけで
# 「現在再生中の曲の位置」を単一の Core actor メッセージ内でアトミックに取得できる。
# seek() は tl_track オブジェクト自体は使わず位置の比較にしか使っていないため、
# playlistid のTOCTOU修正 (get_tl_tracks()1回への一本化、`mpdcurrentsongrace-patch.py`
# 内コメント参照) と同じ「レースそのものを解消する」方針で、2回の別々のactor呼び出しを
# 引数無し index() 1回へ一本化する (リトライではなく根本的にレース窓を無くす)。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

old_seek = (
    "    tl_track = context.core.playback.get_current_tl_track().get()\n"
    "    if context.core.tracklist.index(tl_track).get() != songpos:\n"
    "        play(context, songpos)\n"
    "    context.core.playback.seek(int(seconds * 1000)).get()\n"
)

MARKER = "context.core.tracklist.index().get() != songpos"
if MARKER in s:
    print("seek race already patched, skip")
else:
    assert s.count(old_seek) == 1, f"old_seek count={s.count(old_seek)}"
    new_seek = (
        "    # get_current_tl_track()(playback)とtracklist.index(tl_track)(tracklist)は\n"
        "    # 別々のcore actor呼び出しで、間に他クライアントのmove/swap/delete等が割り込む\n"
        "    # と割り込み後の無関係な位置を掴んでしまい、songposとの一致判定が誤り意図しない\n"
        "    # 曲へ再生がサイレントに切り替わる(currentsong/plchangesと同根のTOCTOU)。\n"
        "    # tracklist.index()は引数省略時に内部でget_current_tl_track()を同一actor内で\n"
        "    # (別途の往復無く) 呼び出す実装のため、引数無し呼び出し1回に一本化することで\n"
        "    # 2回の別呼び出しの間に生じるレース窓自体を無くす。\n"
        "    if context.core.tracklist.index().get() != songpos:\n"
        "        play(context, songpos)\n"
        "    context.core.playback.seek(int(seconds * 1000)).get()\n"
    )
    s = s.replace(old_seek, new_seek, 1)

    open(p, "w").write(s)
    print(
        "patched playback.py: seekのget_current_tl_track()/tracklist.index()間の"
        "TOCTOUレースで無関係な曲へ再生がサイレントに切り替わりうる不具合を修正 "
        "(引数無しtracklist.index()への一本化でレース窓自体を解消)"
    )
