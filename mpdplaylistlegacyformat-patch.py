# current_playlist.py の非推奨コマンド `playlist`(引数なし)が
# `playlistinfo` へそのまま委譲しており、タグ・時間等の詳細メタデータを
# 丸ごと返してしまう不具合を修正。TODO/既知の残課題を全項目消化済みの
# ため自走エージェントが(general-purposeサブエージェントへの調査委任
# を経て)新規発見。
#
# 実MPD本体(gh rawで src/command/QueueCommands.cxx handle_playlist()
# / src/PlaylistPrint.cxx playlist_print_uris() / src/queue/Print.cxx
# queue_print_uris() / src/SongPrint.cxx song_print_uri() を確認):
# `playlist` は `playlist_print_uris()` → `queue_print_uris()` を経由し
# `r.Fmt("{}:", i); song_print_uri(r, queue.Get(i));` のみを実行する。
# `song_print_uri()` は `"file: {}\n"` のみを出力するため、結合すると
# 各行は `POS:file: URI` の1行だけになり、`song_print_info()`(Artist/
# Title/Time等の詳細タグ)は一切呼ばれない。
#
# 一方 mopidy_mpd の `playlist(context)` は `return playlistinfo(context)`
# であり、`playlistinfo` の全出力(translator.tracks_to_mpd_format 経由の
# Artist/Title/Time/Pos/Id/Added等)をそのまま返してしまい実MPDの出力
# 形式と一致しない。
#
# BACKLOG.mdを "def playlist(context)"/"queue_print_uris"/
# "playlist_print_uris"/"旧式"/"レガシー" 等で検索したが既出無しと確認
# (ヒットしたのは stickernamestypes の TYPE="playlist" や idle
# サブシステム"playlist"の誤発火など無関係な既知修正のみ)。
#
# 修正: `playlist(context)` を、キューの各曲を
# `f"{pos}:file: {uri}"` 形式で列挙する独自実装に置き換える
# (listplaylist()の `f"file: {track.uri}"` と同じ「URIのみ」出力
# パターンに pos プレフィックスを付けたもの)。

ap = "mopidy_mpd/protocol/current_playlist.py"
a = open(ap).read()

MARKER = "# mpdplaylistlegacyformat-patch.py: playlist()を実MPD準拠のURIのみ形式へ"
if MARKER in a:
    print("playlistlegacyformat already patched, skip")
else:
    old = '''@protocol.commands.add("playlist")
def playlist(context):
    """
    *musicpd.org, current playlist section:*

        ``playlist``

        Displays the current playlist.

        .. note::

            Do not use this, instead use ``playlistinfo``.
    """
    return playlistinfo(context)'''
    assert a.count(old) == 1, f"old count={a.count(old)}"

    new = '''@protocol.commands.add("playlist")
def playlist(context):
    """
    *musicpd.org, current playlist section:*

        ``playlist``

        Displays the current playlist.

        .. note::

            Do not use this, instead use ``playlistinfo``.
    """
    # mpdplaylistlegacyformat-patch.py: playlist()を実MPD準拠のURIのみ形式へ
    # 修正 (実MPDはこの非推奨コマンドをplaylistinfoと同じ詳細タグ出力では
    # なく "POS:file: URI" のみの1行/曲で返す。QueueCommands.cxx
    # handle_playlist() -> PlaylistPrint.cxx playlist_print_uris() ->
    # queue/Print.cxx queue_print_uris() -> SongPrint.cxx song_print_uri())
    return [
        f"{position}:file: {tl_track.track.uri}"
        for position, tl_track in enumerate(
            context.core.tracklist.get_tl_tracks().get()
        )
    ]'''

    a = a.replace(old, new, 1)
    open(ap, "w").write(a)
    print("patched current_playlist.py: playlist()を実MPD準拠のURIのみ形式へ修正")
