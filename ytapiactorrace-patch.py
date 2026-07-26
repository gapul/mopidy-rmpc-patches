# mopidy_ytmusic.backend.py の on_start() が起動する2本の RepeatingTimer
# (_auto_playlist_refresh_timer / _youtube_player_refresh_timer、repeating_timer.py) は
# 素の threading.Thread サブクラスであり、YTMusicBackend (pykka.ThreadingActor) 自身の
# 受信ループ (actorの単一ワーカースレッド) を経由せず self._refresh_auto_playlists /
# self._refresh_youtube_player を直接タイマー自身のスレッドで実行する。
#
# 一方 mopidy core は backend.library / backend.playlists / backend.playback への
# 全アクセスを ActorProxy 経由 (core/library.py 等が保持する proxy 越しの呼び出し) で
# 行うため、rmpc からの browse/search/lookup や YTMusicScrobbleListener 経由の
# scrobble_track も含め、それ以外の全ての self.api (ytmusicapi.YTMusic の単一共有
# インスタンス) アクセスは必ず YTMusicBackend actor の単一ワーカースレッド上で直列に
# 実行される。つまりこの2本のタイマースレッドだけが、actorのメッセージループを経由せず
# self.api へ並行アクセスする唯一の経路になっている。TODO/既知の軽微な残課題を全項目
# 消化済みのため自走エージェントが、ytcipherfail-patch.py が発見した「RepeatingTimerが
# 無保護」問題の隣接領域としてバックエンドのスレッドモデル自体を再調査して発見した項目。
#
# self.api.headers (ytmusicapi/ytmusic.py の YTMusicBase.headers プロパティ) は
# @cached_property の self.api.base_headers (requests.structures.CaseInsensitiveDict、
# プロセス生存中ずっと同一のオブジェクト) をそのまま in-place で書き換えて返す実装
# (`headers["authorization"] = ...`)。CaseInsensitiveDict.__setitem__ は内部の
# OrderedDict (_store) へ書き込むため、まだ存在しないキーの初回追加時 (base_headers
# 生成直後の1回目の headers 呼び出しや、get_visitor_id() 経由の初回 base_headers
# 生成そのもの) は _store のリサイズを伴う。一方 requests.PreparedRequest.prepare_headers()
# (self.api._send_request()/_send_get_request() が headers=self.api.headers をコピーせず
# そのまま渡す) は `for header in headers.items():` でこの共有オブジェクトを直接走査する。
# 別スレッドがこの走査中に同じ _store へ新規キーを追加すると
# `RuntimeError: OrderedDict mutated during iteration` が発生しうる。
#
# 実際に requests.structures.CaseInsensitiveDict を使い、新規キーを追加し続けるwriter
# スレッドと `for k in d: ...; d[k]` で走査するreaderスレッド (1件ごとの走査に人為的な
# sleepを挟み走査時間の窓を広げる、mpdmountrace-patch.py 等の既存レース検証と同じ手法) を
# 並行実行するオフライン決定的再現テストで、"OrderedDict mutated during iteration" が
# 確実に発生することを確認済み。
#
# 実害: RepeatingTimer.run() (repeating_timer.py) は interval設定に関わらず起動直後に
# self._method() を無条件で1回呼ぶため、mopidy起動直後は auto_playlist_refresh_timer /
# youtube_player_refresh_timer の両スレッドがほぼ同時に self.api 経由でHTTPリクエストを
# 送る。この直後 (あるいは15分/60分毎の定期実行と) rmpcが同時に ytmusic: を
# browse/search/lookupすると、actorスレッドとタイマースレッドが同時に self.api.headers に
# 触れる窓ができる。pykka自体はこの種の通常の Exception をアクター停止ではなく
# 該当リクエストの Future への例外設定として吸収する
# (pykka._actor.Actor._actor_loop_running が Exception をここで捕捉するため actor 自体は
# 生存し続ける) が、発生したその browse/search/lookup リクエスト自体は失敗し rmpc側には
# エラーとして表示される、実MPD互換層としては望ましくない不具合。
#
# 対策: RepeatingTimer に private メソッド (self._refresh_auto_playlists /
# self._refresh_youtube_player) を直接渡すのではなく、self.actor_ref.proxy() 経由の
# アンダースコア無し公開ラッパーメソッドを渡すよう on_start() を変更する。pykka の
# ActorProxy 越しのメソッド呼び出しは常にactor自身の受信ループへメッセージとして送られる
# (pykka公式ドキュメントの「actorが自分自身に将来の作業をスケジュールする」用法と同じ) ため、
# これにより2本のタイマースレッドが行っていた self.api アクセスも全て actor の単一
# ワーカースレッドへ直列化され、core駆動のアクセスと二度と競合しなくなる。
# 注意: pykka の ActorProxy は `_` で始まる属性を意図的に公開しない
# (pykka/_introspection.py introspect_attrs が attr_path[-1].startswith("_") を除外) ため、
# 既存の private メソッド名をそのまま proxy 越しに呼ぶことはできず、アンダースコア無しの
# 薄いラッパーメソッドを新設して委譲する (既存の _refresh_auto_playlists /
# _refresh_youtube_player 自体のロジックは無変更)。

p = "mopidy_ytmusic/backend.py"
s = open(p).read()

MARKER = "def refresh_youtube_player_from_timer"
if MARKER in s:
    print("backend.py already patched (timer/actor race), skip")
else:
    OLD = '''    def on_start(self):
        if self._auto_playlist_refresh_rate:
            self._auto_playlist_refresh_timer = RepeatingTimer(
                self._refresh_auto_playlists, self._auto_playlist_refresh_rate
            )
            self._auto_playlist_refresh_timer.start()

        self._youtube_player_refresh_timer = RepeatingTimer(
            self._refresh_youtube_player, self._youtube_player_refresh_rate
        )
        self._youtube_player_refresh_timer.start()
'''
    assert s.count(OLD) == 1, f"on_start anchor count={s.count(OLD)}"

    NEW = '''    def on_start(self):
        # ytapiactorrace-patch.py: self.api への並行アクセス(RuntimeError要因)を
        # 避けるため、RepeatingTimer にはactor自身のメッセージループへ委譲する
        # アンダースコア無し公開ラッパーを渡す(直接 self._refresh_* を渡さない)。
        proxy = self.actor_ref.proxy()
        if self._auto_playlist_refresh_rate:
            self._auto_playlist_refresh_timer = RepeatingTimer(
                proxy.refresh_auto_playlists_from_timer,
                self._auto_playlist_refresh_rate,
            )
            self._auto_playlist_refresh_timer.start()

        self._youtube_player_refresh_timer = RepeatingTimer(
            proxy.refresh_youtube_player_from_timer,
            self._youtube_player_refresh_rate,
        )
        self._youtube_player_refresh_timer.start()

    def refresh_youtube_player_from_timer(self):
        # RepeatingTimerの生スレッドから ActorProxy 経由で呼ばれる公開ラッパー。
        # pykka がこの呼び出し自体をactor自身の単一ワーカースレッドへ委譲するため、
        # 実体はcore駆動のself.apiアクセスと直列化された状態で実行される
        # (ロジック自体は _refresh_youtube_player から無変更)。
        self._refresh_youtube_player()

    def refresh_auto_playlists_from_timer(self):
        # 同上 (_refresh_auto_playlists 委譲)。
        self._refresh_auto_playlists()
'''
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched backend.py: RepeatingTimerの2本のスレッドをactor自身のメッセージ"
        "ループ経由に変更し、self.api(ytmusicapi)への並行アクセスによる"
        "RuntimeError(OrderedDict mutated during iteration)を解消"
    )
