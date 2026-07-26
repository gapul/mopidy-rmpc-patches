# mopidy_mpd/dispatcher.py の MpdDispatcher._authenticate_filter() が、
# パスワード認証有効時 ([mpd] password 設定時) に未認証の接続が「存在しない
# コマンド名」を送った場合、実MPDなら本来返すべき ACK_ERROR_UNKNOWN
# ("unknown command") ではなく、常に ACK_ERROR_PERMISSION ("you don't have
# permission for ...") を誤って返してしまう不具合。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見。
# mpdauthtabsplit-patch.py が同じ関数の同じブロックの「コマンド名抽出」
# (タブ区切りですり抜ける不具合) を既に修正済みだが、その1行下の
# 「抽出したコマンド名がハンドラテーブルに無いときの分類」は未修正のまま
# 残っていた。
#
# 現状コード (_authenticate_filter() の else 節):
#   command_name = re.split(r"\s+", request, 1)[0]
#   command = protocol.commands.handlers.get(command_name)
#   if command and not command.auth_required:
#       return self._call_next_filter(request, response, filter_chain)
#   else:
#       raise exceptions.MpdPermissionError(command=command_name)
# command_name がそもそもハンドラテーブルに存在しない(未知コマンド)場合も
# command は None になり `if command and ...` が False になるため、
# 「未知コマンドかどうか」と「権限があるかどうか」を区別せず一律
# MpdPermissionError に落ちる。
#
# 実際に確認済み (gh raw で src/command/AllCommands.cxx
# command_checked_lookup() を直接取得):
#   const struct command *cmd = command_lookup(cmd_name);
#   if (cmd == nullptr) {
#       r.FmtError(ACK_ERROR_UNKNOWN, "unknown command {:?}", cmd_name);
#       return nullptr;
#   }
#   ...
#   if (!command_check_request(cmd, r, permission, args))
#       return nullptr;
# 実MPDはコマンド名の存在確認 (command_lookup) を権限チェック
# (command_check_request、ACK_ERROR_PERMISSION) より必ず先に行っており、
# 未接続クライアントの認証状態に関わらず「未知コマンド」は常に
# ACK_ERROR_UNKNOWN (5) になる (ACK_ERROR_PERMISSION=4 とは別コード、
# src/protocol/Ack.hxx)。
#
# mopidy_mpd 自身も認証後の未知コマンド判定には既に正規の
# exceptions.MpdUnknownCommand (ACK_ERROR_UNKNOWN、
# mopidy_mpd/protocol/__init__.py の通常コマンド解決時に使用) を持っており、
# 今回のギャップは「未認証時のみ」このクラスを使わず MpdPermissionError に
# 丸め込んでしまっている非対称。
#
# 修正: 「存在確認 → 権限確認」の順に分離し、command_checked_lookup() と
# 同じ順序にする。command が None (未知コマンド) なら MpdUnknownCommand、
# 存在するが auth_required なら従来通り MpdPermissionError。

p = "mopidy_mpd/dispatcher.py"
s = open(p).read()

OLD = """            command = protocol.commands.handlers.get(command_name)
            if command and not command.auth_required:
                return self._call_next_filter(request, response, filter_chain)
            else:
                raise exceptions.MpdPermissionError(command=command_name)
"""
NEW = """            command = protocol.commands.handlers.get(command_name)
            if command is None:
                raise exceptions.MpdUnknownCommand(command=command_name)
            if not command.auth_required:
                return self._call_next_filter(request, response, filter_chain)
            raise exceptions.MpdPermissionError(command=command_name)
"""

if OLD not in s:
    print("dispatcher.py の認証フィルタの未知コマンド分類は既にパッチ済み、skip")
else:
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched dispatcher.py: MpdDispatcher._authenticate_filter()が"
        "パスワード認証有効時、未認証接続の送った未知コマンドを"
        "ACK_ERROR_PERMISSIONに丸め込んでいた不具合を修正 "
        "(実MPDのcommand_checked_lookup()と同じ「存在確認→権限確認」の"
        "順序で、未知コマンドはMpdUnknownCommand/ACK_ERROR_UNKNOWNを返す)"
    )
