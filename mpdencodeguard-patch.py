# mopidy_mpd/network.py の LineProtocol.encode()/send_lines() と
# Connection.queue_send() の組み合わせに、レスポンス送信経路特有の未捕捉例外
# バグがあった。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (サブエージェントに調査を委任した上で) mopidy_mpd のコード品質を再調査して
# 新規発見した項目。
#
# LineProtocol.encode() は UnicodeError (例: 対になっていないUTF-16サロゲート
# 単体文字 "\ud83d" を含む文字列を str.encode("utf-8") しようとすると発生する
# UnicodeEncodeError はこのサブクラス) を catch すると self.stop() を呼ぶだけで
# 関数は暗黙に None を返す。ここで呼ばれる self.stop() は pykka.ThreadingActor
# (LineProtocol自身) の Actor.stop() であり、自分自身へ非同期の停止メッセージを
# キューイングするだけで即座には停止しない (現在実行中のこの関数の続きは中断
# されない)。
#
# 呼び出し元の send_lines() は encode() の戻り値を None チェックせずそのまま
# self.connection.queue_send(self.encode(data)) へ渡す。queue_send(None) は
# self.send_buffer + data で bytes + NoneType の TypeError を送出する。この
# TypeError は mopidy_mpd/dispatcher.py の except exceptions.MpdAckError の外側
# (network層) で発生するため捕捉されず、pykka の actor ループが on_failure()
# 経由で connection.stop() を呼びセッションが異常切断される (ERRORレベルの
# 未処理例外トレースバックがログに残る)。さらに queue_send() 自体は
# self.send_lock.acquire(True) の後に try/finally 無しで self.send_buffer =
# self.send(...) しているため、この TypeError 発生時 send_lock.release() に
# 到達せず、Lock が held のまま残ってしまう (この接続の以降の queue_send() 呼び
# 出しは全て永久にブロックする)。
#
# 踏む条件: mopidy_mpd の各プロトコルハンドラが組み立てるレスポンス文字列
# (search/find/playlistinfo/currentsong/lsinfo 等、フィールド値は
# mopidy_ytmusic のスクレイピング結果由来のタイトル/アーティスト名等を含みうる)
# に、対になっていないサロゲート単体文字が1文字でも混入していると、その
# レスポンス全体 (既に組み立て済みの他の正常な行も含む) を送信できずセッション
# 切断・Lock leak を引き起こす。decode() 側 (クライアント→サーバ) は
# on_receive() が既に `if line is not None: self.on_line_received(line)` で
# None ガード済みだが、send_lines() 側 (サーバ→クライアント) には対称の
# ガードが欠けていた。
#
# 修正: (1) send_lines() で encode() の戻り値を変数に受け、None なら
# queue_send() を呼ばずに何もしない (self.stop() は encode() 内で既に
# 呼ばれ済みのため二重に切断処理する必要は無い)。(2) queue_send() 自体も
# data is None を早期リターンでガードし (直接呼び出す既存コード
# mpd-patch.py 由来の albumart 送信箇所を含め、将来 None を渡す呼び出しが
# 増えても同様に安全にする)、send_lock.release() を try/finally で保護し
# 例外発生時も確実にロックを解放する (mpdstickersqlerr-patch.py 等が徹底する
# 「ロックは必ず解放する」流儀)。

p = "mopidy_mpd/network.py"
s = open(p).read()

MARKER = "if data is None:\n            # mpdencodeguard-patch.py"
if MARKER in s:
    print("mpdencodeguard already applied to network.py, skip")
else:
    old_queue_send = (
        "    def queue_send(self, data):\n"
        '        """Try to send data to client exactly as is and queue rest."""\n'
        "        self.send_lock.acquire(True)\n"
        "        self.send_buffer = self.send(self.send_buffer + data)\n"
        "        self.send_lock.release()\n"
        "        if self.send_buffer:\n"
        "            self.enable_send()\n"
    )
    assert s.count(old_queue_send) == 1, f"old_queue_send count={s.count(old_queue_send)}"
    new_queue_send = (
        "    def queue_send(self, data):\n"
        '        """Try to send data to client exactly as is and queue rest."""\n'
        "        if data is None:\n"
        "            # mpdencodeguard-patch.py: encode()がUnicodeError時に返すNoneを\n"
        "            # そのまま送ろうとするとself.send_buffer + dataでbytes+NoneType\n"
        "            # のTypeErrorになるため何もしない(呼び出し元は既に切断処理済み)。\n"
        "            return\n"
        "        self.send_lock.acquire(True)\n"
        "        try:\n"
        "            self.send_buffer = self.send(self.send_buffer + data)\n"
        "        finally:\n"
        "            self.send_lock.release()\n"
        "        if self.send_buffer:\n"
        "            self.enable_send()\n"
    )
    s = s.replace(old_queue_send, new_queue_send, 1)

    old_send_lines_tail = (
        "        data = self.join_lines(lines)\n"
        "        self.connection.queue_send(self.encode(data))\n"
    )
    assert s.count(old_send_lines_tail) == 1, f"old_send_lines_tail count={s.count(old_send_lines_tail)}"
    new_send_lines_tail = (
        "        data = self.join_lines(lines)\n"
        "        encoded = self.encode(data)\n"
        "        if encoded is not None:\n"
        "            # mpdencodeguard-patch.py: encode()がUnicodeError時に返すNoneを\n"
        "            # そのままqueue_send()へ渡さない(self.stop()は既にencode()内で\n"
        "            # 呼ばれ済みで二重に切断処理する必要は無い)。\n"
        "            self.connection.queue_send(encoded)\n"
    )
    s = s.replace(old_send_lines_tail, new_send_lines_tail, 1)

    open(p, "w").write(s)
    print(
        "patched network.py: LineProtocol.encode()がUnicodeError(対になっていない"
        "サロゲート単体文字を含む文字列のstr.encode()失敗等)時にNoneを返すが、"
        "send_lines()がNoneチェック無しでqueue_send()へ渡すためbytes+NoneTypeの"
        "TypeErrorが未捕捉のままセッションを異常切断しqueue_send()のLockが解放され"
        "ないまま残ってしまう不具合を修正 (send_lines()にNoneガードを追加、"
        "queue_send()にもdata is Noneガード+try/finallyによるLock解放保証を追加)"
    )
