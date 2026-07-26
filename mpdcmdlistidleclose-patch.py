# mpdcmdlistidle-patch.py が command_list_end() のリプレイループ内で idle/noidle に
# ACK_ERROR_NOT_LIST を返す実装にした際の「実MPD (src/client/Process.cxx) が
# list内のidle/noidleをACK_ERROR_NOT_LIST(1)で拒否するのに倣い」という根拠が誤り
# だったと判明した不具合。TODO 全項目消化済みのため自走エージェントが実MPD本体
# ソース (MusicPlayerDaemon/MPD、GitHubから直接取得) を確認して発見。
#
# 実MPDの src/client/Process.cxx Client::ProcessLine():
#   if (cmd_list.IsActive() && IsAsyncCommmand(line)) {
#       FmtWarning(...);
#       return CommandResult::CLOSE;
#   }
# (IsAsyncCommmand() は "idle"/"noidle" の完全一致のみ判定)
# であり、ACKは一切送らない。src/client/Read.cxx OnSocketInput() の
#   case CommandResult::CLOSE: Close(); return InputResult::CLOSED;
# により、この行を読み取った時点(command_list_endを待たず、コマンドリストの
# 蓄積前)で無応答のままTCP接続を即座に切断する。mpd.readthedocs.io の command
# lists節も "Only synchronous commands can be used in command lists... idle
# and noidle are not allowed." と書くのみでACK応答を返す仕様だとはどこにも
# 書いていない。
#
# 現状 (mpdcmdlistidle-patch.py 適用後) の mopidy_mpd は、idle/noidleを一旦
# self.command_list へ蓄積し、command_list_end() 受信時のリプレイループ内で
# 初めてACKを返し接続は維持したままにする — 実MPDより緩い(親切な)独自挙動に
# なっており、切断タイミングも「idle行を受信した瞬間」ではなく
# 「command_list_endを受信した後」まで遅延してしまう。
#
# 修正: dispatcher.py の _command_list_filter() で、list受信中に届いた行が
# idle/noidleならば self.command_list へ積む前に context.session.close() で
# 即座に切断する (実MPDの「行を読んだ瞬間、リストへの蓄積前に切断」と同じ
# タイミング)。command_list_index/context.subscriptions等の状態には一切触れず
# ハンドラも呼ばないため、mpdcmdlistidle-patch.py が修正した汚染経路とも無関係。
# mpdcmdlistidle-patch.py がcommand_list_end()のリプレイループへ追加した
# idle/noidle分岐は、本パッチ適用後は idle/noidle が self.command_list に
# 二度と入らなくなるため到達不能になるが、albumart/readpicture分岐
# (mpdalbumartcmdlist-patch.py) は引き続き有効なので、そのループ自体は残す。

p = "mopidy_mpd/dispatcher.py"
s = open(p).read()

NEW = (
    "    def _command_list_filter(self, request, response, filter_chain):\n"
    "        if self._is_receiving_command_list(request):\n"
    '            command_name = re.split(r"\\s+", request, 1)[0]\n'
    '            if command_name in ("idle", "noidle"):\n'
    "                self.context.session.close()\n"
    "                return []\n"
    "            self.command_list.append(request)\n"
    "            return []\n"
    "        else:\n"
)

if NEW in s:
    print("_command_list_filter() idle/noidle immediate-close guard already patched, skip")
else:
    OLD = (
        "    def _command_list_filter(self, request, response, filter_chain):\n"
        "        if self._is_receiving_command_list(request):\n"
        "            self.command_list.append(request)\n"
        "            return []\n"
        "        else:\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched dispatcher.py: _command_list_filter()がlist受信中のidle/noidleを"
        "一旦バッファへ蓄積しcommand_list_end受信まで応答/切断を遅延させ、かつ"
        "ACKを返して接続を維持する実MPDより緩い独自挙動になっていた不具合を修正 "
        "(実MPDのProcess.cxx同様、行受信時点で無応答のまま即座に切断)"
    )
