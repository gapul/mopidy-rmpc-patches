# dispatcher.py の MpdDispatcher.command_list (command_list_begin/
# command_list_ok_begin 〜 command_list_end の間に蓄積される、まだ未実行の
# コマンド文字列のリスト) に一切サイズ上限が無い不具合を修正。TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが(general-purposeサブエージェント
# への調査委任を経て)新規発見。
#
# mpdrecvbufcap-patch.py (実MPDのBufferedSocket、固定8192バイトの「1行分の
# 受信バッファ」上限)とは別レイヤの話: 改行区切りの正規のコマンド行を
# command_list_begin 〜 command_list_end の間に大量に送り続けるだけで、
# 個々の行はrecv_bufferの8192バイト制限を毎回クリアしたまま
# self.command_list (Pythonのlist) へ無条件appendされ続け、command_list_end
# が届くまでサーバー側メモリが無制限に伸び続ける。
#
# 実MPD本体 (gh rawで直接確認、WebFetch要約に頼らず生ソースを読んだ):
# - src/client/Config.cxx: `CLIENT_MAX_COMMAND_LIST_DEFAULT (2048*1024)`
#   (デフォルト2MiB、config key `max_command_list_size` 経由で変更可能、
#   `client_max_command_list_size` にバイト単位で格納)
# - src/command/CommandListBuilder.cxx `CommandListBuilder::Add()`:
#     size_t len = strlen(cmd) + 1;
#     size += len;
#     if (size > client_max_command_list_size) return false;
#     list.emplace_back(cmd);
#   1行ごとに (strlen+1) バイトを累積し、上限を超えたら追加を拒否。
# - src/client/Process.cxx `Client::ProcessLine()`:
#     if (!cmd_list.Add(line)) {
#         FmtWarning(..., "command list size is larger than the max ({})",
#                    ..., client_max_command_list_size);
#         return CommandResult::CLOSE;
#     }
#   ACKは一切送らず、警告ログのみ出してその場で接続を切断する
#   (CommandResult::CLOSEはsrc/client/Read.cxxのOnSocketInput()経由でClose()
#   を呼ぶ)。mpdcmdlistidleclose-patch.pyがlist内idle/noidleに対して既に
#   確立済みの「ACK無し・即座にsession.close()」という同じ挙動パターン。
#
# BACKLOG.mdを"max_command_list"/"command_list_size"/"コマンドリスト"の
# サイズ/上限で検索したが既出無し。
#
# 修正: dispatcher.pyにモジュールレベル定数
# `_MPD_MAX_COMMAND_LIST_SIZE = 2048 * 1024` (実MPDのデフォルトと同値) を追加し、
# MpdDispatcher.__init__() で `self.command_list_size = 0` を初期化、
# command_list.py の command_list_begin()/command_list_ok_begin() でも同様に
# 0へリセットする (command_list_end() は既存の command_list リセットのみで
# 十分、次のcommand_list_begin()が必ず0へ戻すため)。
# _command_list_filter() で list受信中の各行をappendする前に
# `len(request.encode("utf-8")) + 1` (実MPDのstrlen+1と同じ、UTF-8バイト数
# 基準。mpdstrictnumparse-patch.py/mpdwindowstrict-patch.py以来の「Pythonの
# 文字数ベースではなく実MPDのバイト数ベースに合わせる」既存方針を踏襲) を
# command_list_size へ加算し、上限を超えたらidle/noidleと全く同じ
# `self.context.session.close(); return []` で切断する。

p = "mopidy_mpd/dispatcher.py"
s = open(p).read()

CONST_MARKER = "_MPD_MAX_COMMAND_LIST_SIZE = "
if CONST_MARKER in s:
    print("mpdcmdlistsizecap already applied to dispatcher.py, skip")
else:
    old_header = (
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "protocol.load_protocol_modules()\n"
    )
    assert s.count(old_header) == 1, f"old_header count={s.count(old_header)}"
    new_header = (
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "#: mpdcmdlistsizecap-patch.py: 実MPDのCLIENT_MAX_COMMAND_LIST_DEFAULT\n"
        "#: (src/client/Config.cxx) と同じデフォルト上限 (2MiB)。command_list_begin\n"
        "#: 〜 command_list_end の間に蓄積される未実行コマンド文字列の合計バイト数\n"
        "#: がこれを超えたら、実MPDのCommandListBuilder::Add()同様に受理を拒否する。\n"
        "_MPD_MAX_COMMAND_LIST_SIZE = 2048 * 1024\n"
        "\n"
        "protocol.load_protocol_modules()\n"
    )
    s = s.replace(old_header, new_header, 1)

    old_init = (
        "        self.command_list = []\n"
        "        self.command_list_index = None\n"
    )
    assert s.count(old_init) == 1, f"old_init count={s.count(old_init)}"
    new_init = (
        "        self.command_list = []\n"
        "        self.command_list_size = 0\n"
        "        self.command_list_index = None\n"
    )
    s = s.replace(old_init, new_init, 1)

    old_filter = (
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
    assert s.count(old_filter) == 1, f"old_filter count={s.count(old_filter)}"
    new_filter = (
        "    def _command_list_filter(self, request, response, filter_chain):\n"
        "        if self._is_receiving_command_list(request):\n"
        '            command_name = re.split(r"\\s+", request, 1)[0]\n'
        '            if command_name in ("idle", "noidle"):\n'
        "                self.context.session.close()\n"
        "                return []\n"
        "            self.command_list_size += (\n"
        '                len(request.encode("utf-8")) + 1\n'
        "            )\n"
        "            if self.command_list_size > _MPD_MAX_COMMAND_LIST_SIZE:\n"
        "                # mpdcmdlistsizecap-patch.py: 実MPDのProcess.cxxと同じく\n"
        "                # ACK無しで即座に切断する(list蓄積前にreturn)。\n"
        "                self.context.session.close()\n"
        "                return []\n"
        "            self.command_list.append(request)\n"
        "            return []\n"
        "        else:\n"
    )
    s = s.replace(old_filter, new_filter, 1)

    open(p, "w").write(s)
    print(
        "patched dispatcher.py: MpdDispatcher.command_listにサイズ上限が無く、"
        "command_list_begin~command_list_endの間に正規のコマンド行を大量に送る"
        "だけで1接続がサーバーメモリを無制限に消費できる不具合を修正 "
        "(実MPDのCLIENT_MAX_COMMAND_LIST_DEFAULTと同じ2MiB上限を超えたら"
        "ACK無しで即座に切断)"
    )

p2 = "mopidy_mpd/protocol/command_list.py"
s2 = open(p2).read()

if "command_list_size = 0" in s2:
    print("mpdcmdlistsizecap already applied to command_list.py, skip")
else:
    old_begin = (
        "    context.dispatcher.command_list_ok = False\n"
        "    context.dispatcher.command_list = []\n"
    )
    assert s2.count(old_begin) == 1, f"old_begin count={s2.count(old_begin)}"
    new_begin = (
        "    context.dispatcher.command_list_ok = False\n"
        "    context.dispatcher.command_list = []\n"
        "    context.dispatcher.command_list_size = 0\n"
    )
    s2 = s2.replace(old_begin, new_begin, 1)

    old_ok_begin = (
        "    context.dispatcher.command_list_ok = True\n"
        "    context.dispatcher.command_list = []\n"
    )
    assert s2.count(old_ok_begin) == 1, f"old_ok_begin count={s2.count(old_ok_begin)}"
    new_ok_begin = (
        "    context.dispatcher.command_list_ok = True\n"
        "    context.dispatcher.command_list = []\n"
        "    context.dispatcher.command_list_size = 0\n"
    )
    s2 = s2.replace(old_ok_begin, new_ok_begin, 1)

    open(p2, "w").write(s2)
    print(
        "patched command_list.py: command_list_begin()/command_list_ok_begin()で"
        "command_list_sizeを0へリセットするよう追加"
    )
