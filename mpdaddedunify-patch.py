# mpdadded-patch.py (キュー内Added、tlidキーの_queue_added、曲がキューへ
# 追加されるたびに新しい現在時刻でスタンプ) と mpdlibraryadded-patch.py
# (キュー外Added、uriキーの_library_added、このMPDセッションで最初にその
# uriを返した時刻を不変に保持) は、同一trackでも参照経路によって完全に
# 独立した2系統の揮発性ストアを見ており、同じ曲(同じuri)でも
# find/search経由かキュー経由かでAddedの値が食い違う不具合を修正。
# mpdlibraryadded-patch.py自身のコメントも「同一uriがキューにも同時に
# 載っている場合、キュー側は独立した_queue_addedを引き続き使う」と
# 明記しており自覚済みだが未修正のまま残されていた
# (mpdsavecreatedefault-patch.py等と同型の「既存コメントは検証済みの
# 証拠にならない」パターン)。
#
# 実MPD本体(gh rawでsrc/queue/Queue.hxxを確認)のQueue::Item構造体には
# id/song/version/priorityのみでAdded相当のフィールドが一切無い。
# つまり実MPDには「キューへの追加時刻」という概念自体が存在せず、
# playlistinfoが表示するAddedもfind/lsinfoと全く同じ、曲固有(DB登録
# 時刻、src/song/DetachedSong.hxxのコメント "The time stamp when the
# file was added to db")の値を再利用しているだけ。つまり同一uriなら
# 経路を問わず同じAddedを返すのが正しい挙動。
#
# rmpc本体(mierak/rmpc)のSongProperty::Added()
# (rmpc/src/config/theme/properties.rs)はrmpc/src/ui/dir_or_song.rsの
# CmpByProp::cmp(a.added, b.added)からキュー/検索結果/タグブラウザ/
# ストアドプレイリストいずれのペインでも同一の意味論のソート・カラム
# 表示プロパティとして参照されるため、経路による食い違いはキューへの
# 出し入れだけでソート順が不安定に変化するという実害がある
# (実機確認: 同一uriをaddid→playlistinfoで見たAddedが、delete後に
# 同じuriを再addidすると別の値に変わってしまう)。
#
# 修正: track_to_mpd_format()のキュー分岐(position/tlid有)のAdded取得を、
# tlidキーの get_added() から、mpdlibraryadded-patch.py が導入した
# uriキーの get_or_stamp_library_added() に一本化する。_queue_added/
# stamp_added/sync_added/get_added の書き込み経路
# (add/addid/findadd/searchadd/load/actor.py)はそのまま残しても実害は
# 無い(単に読まれなくなるだけ)ため、他ファイルには手を入れない。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

old = (
    "        added = get_added(tlid)\n"
    "        if added:\n"
    '            result.append(("Added", added))\n'
)
if old not in t:
    print("translator.py already patched (queue Added unified with library Added), skip")
else:
    assert t.count(old) == 1, f"old count={t.count(old)}"
    new = (
        "        added = get_or_stamp_library_added(track.uri)\n"
        "        if added:\n"
        '            result.append(("Added", added))\n'
    )
    t = t.replace(old, new, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: キュー内AddedもuriキーのAddedに統一"
        "(経路によらず同一uriなら同一値を返す)"
    )
