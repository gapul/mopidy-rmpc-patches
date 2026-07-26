# actor.py の MpdFrontend._CORE_EVENTS_TO_IDLE_SUBSYSTEMS が mopidy core の
# "stream_title_changed" イベント (ストリーム再生中に GStreamer が報告する title
# タグが現在曲の名前と食い違った際に core/actor.py Core.tags_changed() が発火、
# mopidy_ytmusic のライブストリームURI (ytlivestream-patch.py) でも起こりうる) を
# idle サブシステム "playlist" へ誤って割り当てている不具合を修正。
#
# 実MPD本体 (gh rawで doc/protocol.rst / src/Partition.cxx を確認) は「現在再生中の
# 曲のタグが変化した (例: ストリームから受信)」を明確に idle サブシステム "player"
# の説明として定義しており (protocol.rst: "the player has been started, stopped or
# seeked or tags of the currently playing song have changed (e.g. received from
# stream)")、実装側の Partition::OnPlayerTagModified() も
#   EmitIdle(IDLE_PLAYER);
# と "player" のみを発火する ("playlist" には一切触れない)。
#
# 一方 mopidy_mpd (upstream mopidy-mpd 3.3.0、パッチ対象外の元々のソース、
# https://github.com/mopidy/mopidy-mpd の actor.py) は
#   "stream_title_changed": "playlist",
# と誤って "playlist" サブシステムに割り当てており、`idle player` のみを購読する
# 一般的なMPDクライアント (mpc/ncmpcpp等) はストリームのタイトル変化で一切起床
# しない (`idle playlist` を購読していれば発火してしまう、意味的に無関係な
# サブシステム)。同じ辞書内の他のイベント (playback_state_changed/seeked→player、
# tracklist_changed→playlist、options_changed→options 等) は全て実MPDの
# IDLE_* 定義と一致しておりこの1エントリのみが非対称。

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER = '"stream_title_changed": "player"'
if MARKER in a:
    print("streamtitleidle already patched, skip")
else:
    old_entry = '    "stream_title_changed": "playlist",\n'
    assert a.count(old_entry) == 1, f"old_entry count={a.count(old_entry)}"
    new_entry = '    "stream_title_changed": "player",\n'
    a = a.replace(old_entry, new_entry, 1)

    open(ap, "w").write(a)
    print("patched actor.py: stream_title_changed の idle サブシステムを playlist から player へ修正")
