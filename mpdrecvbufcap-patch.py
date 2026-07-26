# mopidy_mpd/network.py の LineProtocol.on_receive() は、受信データを
# `self.recv_buffer += message["received"]` で無条件に蓄積し、改行が見つかった
# 分だけ parse_lines() で切り出す設計だが、recv_buffer自体のサイズに一切上限が
# 無い。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purpose サブエージェントへの調査委任を経て)新規発見した項目。
#
# 実MPD本体は接続ごとに固定サイズの受信バッファしか持たない:
# src/event/BufferedSocket.hxx の `StaticFifoBuffer<std::byte, 8192> input;`
# (8192バイト固定)。src/event/BufferedSocket.cxx の ResumeInput() は、行の
# 区切り(改行)がまだ見つからず追加データを要求する状態 (`InputResult::MORE`)
# で `input.IsFull()` になった時点で
#   OnSocketError(std::make_exception_ptr(
#       std::runtime_error("Input buffer is full")));
# を呼んで即座に接続を切断する。この `BufferedSocket` は src/client/Client.hxx
# が `FullyBufferedSocket` 経由で継承しており、MPDのテキストプロトコル接続
# (`Client`) 全てに適用される制限であることを確認済み。
#
# mopidy_mpd にはこの上限が無いため、クライアントが改行を含まない任意長の
# バイト列を送り続けるだけで recv_buffer が無制限に伸び続け、1接続だけで
# サーバープロセスのメモリを枯渇させられる (接続も切断されない)。実機確認
# (TCP 6601) で、改行無しの20000バイトを送信後も接続がREADY状態のまま維持
# され続けることを確認した。BACKLOG.md を "recv_buffer"/"LineProtocol"/
# "parse_lines"/"Input buffer" で検索したが、network.py に対する既存パッチは
# mpdrecvhalt-patch.py (同一recv()チャンク内の後続行処理を打ち切るCSRF対策の
# 穴) と mpdencodeguard-patch.py (encode() の UnicodeError 時の None 伝播) の
# 2件のみで、いずれも受信バッファの上限とは無関係。
#
# 修正: モジュールレベルに実MPDと同じ `_MAX_RECV_BUFFER_SIZE = 8192` を追加し、
# on_receive() の parse_lines() ループ後 (＝そのチャンクで切り出せる完全な行を
# 全て処理し終えた後)、まだ改行の来ない残り(recv_buffer)が上限を超えていれば
# `self.connection.stop("Input buffer is full")` を呼んで切断する。ループ内で
# 既に mpdrecvhalt-patch.py の break により停止済み (`connection.stopping`)
# の場合は二重に stop() を呼ばないようガードする。ループの前ではなくループの
# 後で判定することで、1回の recv() チャンクに正規のコマンド行と改行無しの
# 巨大な残りバイト列が両方含まれる場合でも、先行する正規コマンドは実MPDの
# 「完全な行から順に処理し、行になっていない残りだけがバッファ上限に抵触する」
# という挙動に近い形でまず処理される。

p = "mopidy_mpd/network.py"
s = open(p).read()

MARKER = "_MAX_RECV_BUFFER_SIZE = "
if MARKER in s:
    print("mpdrecvbufcap already applied to network.py, skip")
else:
    old_const = "CONTROL_CHARS = dict.fromkeys(range(32))\n"
    assert s.count(old_const) == 1, f"old_const count={s.count(old_const)}"
    new_const = (
        "CONTROL_CHARS = dict.fromkeys(range(32))\n"
        "\n"
        "#: mpdrecvbufcap-patch.py: 実MPDのBufferedSocket (src/event/\n"
        "#: BufferedSocket.hxx) が持つ固定8192バイト入力バッファと同じ上限。\n"
        "#: 改行が見つからないまま recv_buffer がこのサイズを超えたら\n"
        "#: 実MPD同様に接続を切断する (LineProtocol.on_receive() 参照)。\n"
        "_MAX_RECV_BUFFER_SIZE = 8192\n"
    )
    s = s.replace(old_const, new_const, 1)

    old_tail = (
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
    assert s.count(old_tail) == 1, f"old_tail count={s.count(old_tail)}"
    new_tail = (
        "            if self.connection.stopping:\n"
        "                # on_line_received()内のCSRF対策(不正な形式のコマンド検知)等が\n"
        "                # connection.stop()を呼んでも、pykka actorはこのメッセージの\n"
        "                # 処理自体を中断しないため、同一recv()チャンク内に残る後続行が\n"
        "                # そのままdispatchされてしまう(mpdrecvhalt-patch.py)。\n"
        "                break\n"
        "\n"
        "        if (\n"
        "            not self.connection.stopping\n"
        "            and len(self.recv_buffer) > _MAX_RECV_BUFFER_SIZE\n"
        "        ):\n"
        "            # mpdrecvbufcap-patch.py: 改行がまだ来ない残りデータが実MPDの\n"
        "            # 固定入力バッファ上限(8192バイト)を超えた。実MPDの\n"
        "            # BufferedSocket::ResumeInput()と同様に接続を切断し、無制限な\n"
        "            # recv_buffer肥大化によるメモリ枯渇を防ぐ。\n"
        "            self.connection.stop(\"Input buffer is full\")\n"
        "\n"
        "        if not self.prevent_timeout and not self.connection.stopping:\n"
        "            self.connection.enable_timeout()\n"
    )
    s = s.replace(old_tail, new_tail, 1)

    open(p, "w").write(s)
    print(
        "patched network.py: LineProtocol.on_receive()のrecv_bufferにサイズ上限が"
        "無く、改行を含まないデータを送り続けるだけで1接続がサーバーメモリを"
        "無制限に消費できる不具合を修正 (実MPDのBufferedSocketと同じ8192バイト"
        "上限を超えたら接続を切断)"
    )
