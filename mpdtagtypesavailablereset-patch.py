# connection.py の tagtypes() が実MPD 0.24 で追加された `tagtypes available` /
# `tagtypes reset {NAME...}` の2サブコマンドを一切認識せず、常に
# `ACK Unknown sub command` を返してしまう不具合を修正。TODO全項目消化済みのため
# 自走エージェントが(general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体 (gh raw で MusicPlayerDaemon/MPD master の
# src/command/ClientCommands.cxx handle_tagtypes() を確認、NEWS にも
# 「ver 0.24: new "available" and "reset" subcommands for tagtypes」と明記) は
# 6分岐 (all/clear/enable/disable/available/reset) を持つ:
#   - `available`: tag_print_types_available(r) — サーバー設定の global_tag_mask
#     (mopidy_mpdには metadata_to_use 相当の概念が無いため、常に
#     tagtype_list.TAGTYPE_LIST 全件を返せばよい)。クライアント個別の
#     enable/disable 状態 (context.session.tagtypes) とは無関係、既存の
#     ``tagtypes``(引数無し)が返すクライアント側の絞り込み状態と非対称なのが仕様通り。
#   - `reset {NAME...}`: client.tag_mask = None(); tag_mask |= ParseTagMask(request)
#     — clear + enable のアトミック版。ParseTagMask は request 空なら
#     "Not enough arguments" を送出 (src/command/ClientCommands.cxx
#     ParseTagMask())しており、これは既存の _resolve_tagtypes() の
#     空引数チェックと同じエラー文言・挙動のため同ヘルパをそのまま再利用できる。
#
# 兄弟コマンド protocol/stringnormalization (mpdprotocol-patch.py/
# mpdstringnorm-patch.py) は available サブコマンドを既に実装済みで、
# tagtypes だけこの非対称が残っていた。
cp = "mopidy_mpd/protocol/connection.py"
c = open(cp).read()

MARKER = 'subcommand == "reset"'
if MARKER in c:
    print("connection.py already patched for tagtypes available/reset, skip")
else:
    old_doc_and_body = (
        '    """\n'
        "    *mpd.readthedocs.io, connection settings section:*\n"
        "\n"
        "        ``tagtypes``\n"
        "\n"
        "        Shows a list of available song metadata.\n"
        "\n"
        "        ``tagtypes disable {NAME...}``\n"
        "\n"
        "        Remove one or more tags from the list of tag types the client is interested in.\n"
        "\n"
        "        ``tagtypes enable {NAME...}``\n"
        "\n"
        "        Re-enable one or more tags from the list of tag types for this client.\n"
        "\n"
        "        ``tagtypes clear``\n"
        "\n"
        "        Clear the list of tag types this client is interested in.\n"
        "\n"
        "        ``tagtypes all``\n"
        "\n"
        "        Announce that this client is interested in all tag types.\n"
        '    """\n'
        "    parameters = list(parameters)\n"
        "    if parameters:\n"
        "        subcommand = parameters.pop(0).lower()\n"
        '        if subcommand not in ("all", "clear", "disable", "enable"):\n'
        '            raise exceptions.MpdArgError("Unknown sub command")\n'
        '        elif subcommand == "all":\n'
        "            context.session.tagtypes.update(tagtype_list.TAGTYPE_LIST)\n"
        '        elif subcommand == "clear":\n'
        "            context.session.tagtypes.clear()\n"
        '        elif subcommand == "disable":\n'
        "            context.session.tagtypes.difference_update(\n"
        "                _resolve_tagtypes(parameters)\n"
        "            )\n"
        '        elif subcommand == "enable":\n'
        "            context.session.tagtypes.update(_resolve_tagtypes(parameters))\n"
        "        return\n"
        '    return [("tagtype", tagtype) for tagtype in context.session.tagtypes]\n'
    )
    assert c.count(old_doc_and_body) == 1, f"tagtypes body count={c.count(old_doc_and_body)}"
    new_doc_and_body = (
        '    """\n'
        "    *mpd.readthedocs.io, connection settings section:*\n"
        "\n"
        "        ``tagtypes``\n"
        "\n"
        "        Shows a list of available song metadata.\n"
        "\n"
        "        ``tagtypes disable {NAME...}``\n"
        "\n"
        "        Remove one or more tags from the list of tag types the client is interested in.\n"
        "\n"
        "        ``tagtypes enable {NAME...}``\n"
        "\n"
        "        Re-enable one or more tags from the list of tag types for this client.\n"
        "\n"
        "        ``tagtypes clear``\n"
        "\n"
        "        Clear the list of tag types this client is interested in.\n"
        "\n"
        "        ``tagtypes all``\n"
        "\n"
        "        Announce that this client is interested in all tag types.\n"
        "\n"
        "        ``tagtypes available``\n"
        "\n"
        "        Lists all tag types the server is able to provide.\n"
        "\n"
        "        ``tagtypes reset {NAME...}``\n"
        "\n"
        "        Clear the list of tag types this client is interested in, then "
        "re-enable one or more tags.\n"
        '    """\n'
        "    parameters = list(parameters)\n"
        "    if parameters:\n"
        "        subcommand = parameters.pop(0).lower()\n"
        '        if subcommand not in (\n'
        '            "all",\n'
        '            "available",\n'
        '            "clear",\n'
        '            "disable",\n'
        '            "enable",\n'
        '            "reset",\n'
        "        ):\n"
        '            raise exceptions.MpdArgError("Unknown sub command")\n'
        '        elif subcommand == "all":\n'
        "            context.session.tagtypes.update(tagtype_list.TAGTYPE_LIST)\n"
        '        elif subcommand == "available":\n'
        "            return [\n"
        '                ("tagtype", tagtype) for tagtype in tagtype_list.TAGTYPE_LIST\n'
        "            ]\n"
        '        elif subcommand == "clear":\n'
        "            context.session.tagtypes.clear()\n"
        '        elif subcommand == "disable":\n'
        "            context.session.tagtypes.difference_update(\n"
        "                _resolve_tagtypes(parameters)\n"
        "            )\n"
        '        elif subcommand == "enable":\n'
        "            context.session.tagtypes.update(_resolve_tagtypes(parameters))\n"
        '        elif subcommand == "reset":\n'
        "            context.session.tagtypes.clear()\n"
        "            context.session.tagtypes.update(_resolve_tagtypes(parameters))\n"
        "        return\n"
        '    return [("tagtype", tagtype) for tagtype in context.session.tagtypes]\n'
    )
    c = c.replace(old_doc_and_body, new_doc_and_body, 1)

    open(cp, "w").write(c)
    print("patched connection.py: tagtypes に available/reset サブコマンドを追加")
