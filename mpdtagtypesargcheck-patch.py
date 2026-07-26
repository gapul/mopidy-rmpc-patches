# `tagtypes all {余分な引数}` / `tagtypes clear {余分な引数}` が引数を無条件で無視し
# 常にOKを返してしまう不具合(実MPDはACK Too many argumentsを返すべき)を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体(gh rawでsrc/command/ClientCommands.cxx handle_tagtypes()を確認)は
# "all"/"clear"の各分岐冒頭で`if (!request.empty()) { r.Error(ACK_ERROR_ARG,
# "Too many arguments"); return CommandResult::ERROR; }`という引数チェックを持つ。
# 兄弟コマンドprotocol/stringnormalization(mpdprotocol-patch.py/
# mpdstringnorm-patch.pyが実MPD調査の上でall/clear/availableに同じチェックを
# 実装済み)はこの非対称を踏まえて正しく実装されているが、tagtypes自体は
# mpdtagtypesavailablereset-patch.pyがavailable/resetを追加した際もこのチェックを
# 移植し忘れており、"all"/"clear"に余分な引数を付けても素通りしOKを返していた
# (enable/disable/resetはNAMEリストを取るためチェック対象外、availableは
# 実MPD自身にもチェックが無くmopidy_mpdも元々未チェックのため対象外)。
cp = "mopidy_mpd/protocol/connection.py"
c = open(cp).read()

MARKER = "tagtypes: all/clear too many arguments guard"
if MARKER in c:
    print("connection.py already patched for tagtypes all/clear arg check, skip")
else:
    OLD_ALL = (
        '        elif subcommand == "all":\n'
        "            context.session.tagtypes.update(tagtype_list.TAGTYPE_LIST)\n"
    )
    assert c.count(OLD_ALL) == 1, f"tagtypes all count={c.count(OLD_ALL)}"
    NEW_ALL = (
        '        elif subcommand == "all":\n'
        f"            # {MARKER}\n"
        "            if parameters:\n"
        '                raise exceptions.MpdArgError("Too many arguments")\n'
        "            context.session.tagtypes.update(tagtype_list.TAGTYPE_LIST)\n"
    )
    c = c.replace(OLD_ALL, NEW_ALL, 1)

    OLD_CLEAR = (
        '        elif subcommand == "clear":\n'
        "            context.session.tagtypes.clear()\n"
    )
    assert c.count(OLD_CLEAR) == 1, f"tagtypes clear count={c.count(OLD_CLEAR)}"
    NEW_CLEAR = (
        '        elif subcommand == "clear":\n'
        "            if parameters:\n"
        '                raise exceptions.MpdArgError("Too many arguments")\n'
        "            context.session.tagtypes.clear()\n"
    )
    c = c.replace(OLD_CLEAR, NEW_CLEAR, 1)

    open(cp, "w").write(c)
    print(
        "patched connection.py: tagtypes all/clearに余分な引数を渡すとACK "
        "Too many argumentsを返すよう修正"
    )
