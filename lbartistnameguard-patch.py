# mopidy_listenbrainz/frontend.py の ListenbrainzFrontend.track_playback_started()/
# track_playback_ended() が、`", ".join(sorted([a.name for a in track.artists]))` で
# アーティスト名を無条件に文字列扱いしている不具合。
#
# mopidy.models.fields.Field.__set__ (実ソース確認済み: `if value is not None:
# value = self.validate(value)`) は None を渡された場合バリデーション自体を
# バイパスするため、`Artist(name=None, ...)` は完全に正当な mopidy.models.Artist
# インスタンスであり、name フィールドは仕様上 optional (非nullを保証しない)。
# mopidy_ytmusic/library.py は複数箇所 (playlistToTracks() の
# `Artist(name=a["name"], sortname=a["name"], musicbrainz_id="")` 等、YouTube Music
# APIのartist dictを`.get("name", "")`のような既定値なしに素通しする箇所) があり、
# 同ファイル内の既存パッチ群 (ytartistcache-patch.py/yttopresultartist-patch.py/
# ytmoodgenre-patch.py 等) が繰り返し扱ってきた「YouTube Music APIのartistメタデータが
# id/name欠落を伴う」という既知の傾向と整合するため、Artist(name=None) を含む Track が
# 実際の再生対象になり得る。
#
# 実害: track_playback_started/track_playback_ended は mopidy.core.CoreListener
# イベントとして mopidy.listener.send() 経由でpykkaの"tell"(reply_to無し)メッセージ
# として配送される。この中で `sorted([a.name for a in track.artists])` が
# (複数アーティストでNoneと文字列が混在すれば`TypeError: '<' not supported between
# instances of 'NoneType' and 'str'`、単一アーティストでNoneのみなら直後の
# `", ".join(...)` で`TypeError: sequence item 0: expected str instance, NoneType
# found`という形で) TypeError を送出すると、pykka _actor_loop_running() (実ソース
# 確認済み、pykka/_actor.py) の `except Exception:` 分岐で reply_to is None のため
# self._handle_failure() が呼ばれ ActorRegistry.unregister() + self.actor_stopped.set()
# でアクターが永久停止する。ListenbrainzFrontend.on_start() はプロセス起動時に1度
# しか呼ばれないため、以後の submit_listen()(scrobble) も週次プレイリスト再インポート
# も含め ListenBrainz 連携全体がプロセス生涯にわたり無効化される。lbnetguard-patch.py/
# lbtokennetguard-patch.py/lbjsonguard-patch.py 等は同種の「actorクラッシュ」パターンを
# ネットワーク/JSON応答まわりで修正済みだったが、この曲メタデータ整形経路
# (ネットワークI/Oを伴わない) は無防備のまま残っていた。
#
# 修正: 同じコードベース内の mopidy_mpd/protocol/current_playlist.py の
# _pf_field_values() (`[a.name for a in track.artists if a.name]`、空/None名を除外)
# と同じ防御を、track_playback_started()/track_playback_ended() 両方の
# アーティスト名整形にも適用する。

p = "mopidy_listenbrainz/frontend.py"
s = open(p).read()

OLD = '        artists = ", ".join(sorted([a.name for a in track.artists]))\n'
NEW = '        artists = ", ".join(sorted(a.name for a in track.artists if a.name))\n'

if NEW in s and OLD not in s:
    print("track_playback_started/ended already guarded against None artist name, skip")
else:
    count = s.count(OLD)
    assert count == 2, f"OLD count={count}"
    s = s.replace(OLD, NEW)
    open(p, "w").write(s)
    print(
        "patched frontend.py: track_playback_started()/track_playback_ended() が "
        "Artist(name=None)を含むtrack.artistsでTypeErrorを送出しactorをクラッシュさせる "
        "不具合を修正 (name=Noneのアーティストをsorted/join対象から除外)"
    )
