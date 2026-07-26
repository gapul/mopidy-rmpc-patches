# mopidy_mpd/session.py の MpdSession.on_line_received() は、コマンド行の先頭文字が
# 小文字英字でない場合 (実MPDと同じCSRF/cross-protocol scripting対策: ブラウザ経由で
# HTTPリクエスト等の異種プロトコルのバイト列をMPDの待受ポートへ送りつけ、その中に
# 紛れ込ませたMPDコマンド文字列を実行させる攻撃を防ぐガード)、即座に
# `self.connection.stop("Malformed command")` を呼んで接続を切断する設計になっている。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが mopidy_mpd のコード品質を
# 再調査して発見した。
#
# ところが network.py の `LineProtocol.on_receive()` は、1回の `recv()` で受信した
# バッファ内に含まれる複数行を単一の for ループで最後まで処理する:
#   for line in self.parse_lines():
#       line = self.decode(line)
#       if line is not None:
#           self.on_line_received(line)
# `on_line_received()` 内で `self.connection.stop()` を呼んでソケットを close() しても、
# これは for ループを中断させない。`Connection.stop()` は `self.stopping = True` を
# 立てソケットを閉じるだけで、`on_receive()` 自身の実行は継続する
# (pykka の Actor は現在処理中のメッセージ本体を中断する機構を持たない)。
#
# 実害: 攻撃者が1回のTCP書き込み (= 1回の recv()) にまとめて
#   POST / HTTP/1.1\r\nHost: 127.0.0.1:6600\r\n\r\nplay\r\n
# のようなペイロードを送ると、`"POST / HTTP/1.1"` の時点で malformed 判定され
# `connection.stop()` によりソケットは即座に close() されるが、for ループは
# 後続の `"Host: ..."` / 空行を経て最後の `"play"` (先頭が小文字英字なのでガードを
# 通過する) まで処理を続け、`self.dispatcher.handle_request("play")` が実際に
# 呼ばれて `core.playback.play()` が発火してしまう。応答の送信こそソケットが
# 既に閉じているため失敗する (握り潰される) が、mopidy本体の状態変更
# (再生開始/停止/キュー操作/ストアドプレイリスト削除等、パスワード未設定または
# 認証不要なコマンドなら何でも) は既に実行済みになる。「不正な形式のリクエストを
# 検知したら即座に接続を切断しそれ以降は一切処理しない」という CSRF 対策の意図が、
# 同一チャンク内の後続行に対しては素通りしてしまうセキュリティ境界のすり抜けであり、
# BACKLOG.md 記載の既存パッチ群 (未捕捉例外によるセッション切断、read-modify-write の
# 競合、引数バリデーション漏れ) のいずれとも異なる新種の不具合。
#
# 修正: `LineProtocol.on_receive()` の for ループ内で `on_line_received()` 呼び出し後に
# `self.connection.stopping` を確認し、真になっていれば即座に break して同一チャンク内の
# 後続行の処理を打ち切る。ループを抜けた後の `self.connection.enable_timeout()` も、
# 既に切断済みの接続へ無意味なタイムアウトを再設定しないよう `stopping` 済みならスキップする。

p = "mopidy_mpd/network.py"
s = open(p).read()

MARKER = "if not self.prevent_timeout and not self.connection.stopping:"
if MARKER in s:
    print("mpdrecvhalt already applied to network.py, skip")
else:
    old = (
        "        for line in self.parse_lines():\n"
        "            line = self.decode(line)\n"
        "            if line is not None:\n"
        "                self.on_line_received(line)\n"
        "\n"
        "        if not self.prevent_timeout:\n"
        "            self.connection.enable_timeout()\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "        for line in self.parse_lines():\n"
        "            line = self.decode(line)\n"
        "            if line is not None:\n"
        "                self.on_line_received(line)\n"
        "            if self.connection.stopping:\n"
        "                # on_line_received()内のCSRF対策(不正な形式のコマンド検知)等が\n"
        "                # connection.stop()を呼んでも、pykka actorはこのメッセージの\n"
        "                # 処理自体を中断しないため、同一recv()チャンク内に残る後続行が\n"
        "                # そのままdispatchされてしまう(mpdrecvhalt-patch.py)。\n"
        "                break\n"
        "\n"
        "        if not self.prevent_timeout and not self.connection.stopping:\n"
        "            self.connection.enable_timeout()\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print(
        "patched network.py: on_line_received()内のconnection.stop()(不正な形式の"
        "コマンドを検知したCSRF対策)が呼ばれても、同一recv()チャンク内に含まれる"
        "後続行の処理をon_receive()のforループが打ち切らず、切断決定後もコマンドが"
        "dispatchされてしまう不具合を修正 (stopping確認によるbreakを追加)"
    )
