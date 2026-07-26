# mopidy_mpd/tokenize.py の split() が、1コマンド行に含まれる引数トークンの
# 総数に一切上限を設けていない不具合を修正。TODO/既知の残課題を全項目消化済み
# のため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# 実MPD本体 (gh rawで直接確認、WebFetch要約に頼らず生ソースを読んだ):
# - src/command/AllCommands.cxx (command_process()):
#     static constexpr std::size_t COMMAND_ARGV_MAX = 2 + TAG_NUM_OF_ITEM_TYPES * 2;
#     ...
#     StaticVector<const char *, COMMAND_ARGV_MAX> argv;
#     while (true) {
#         char *a = tokenizer.NextParam();
#         if (a == nullptr) break;
#         if (argv.full()) {
#             r.Error(ACK_ERROR_ARG, "Too many arguments");
#             return CommandResult::ERROR;
#         }
#         argv.push_back(a);
#     }
#     const Request args{argv};
#     const struct command *cmd =
#         command_checked_lookup(r, client.GetPermission(), cmd_name, args);
#   argv.full() の検査はコマンド名の字句解析(NextWord())が終わった後、かつ
#   command_checked_lookup()(=コマンド名の妥当性検証・存在チェック)より前段
#   で行われる。つまり未知コマンド名であっても引数トークンが上限を超えていれば
#   "unknown command" ではなく "Too many arguments" が優先して返る。
# - src/tag/Type.hxx (enum TagType): ARTIST〜LABEL(29種)+
#   MUSICBRAINZ_ARTISTID〜MUSICBRAINZ_RELEASEGROUPID(7種)の計36種
#   (TAG_NUM_OF_ITEM_TYPES=36)。よって COMMAND_ARGV_MAX = 2 + 36*2 = 74。
# - src/client/Response.hxx: `const char *command = "";` (デフォルト空文字列)、
#   SetCommand() は command_checked_lookup() 内でのみ呼ばれる。argv.full() の
#   検査時点ではまだ呼ばれていないため、ACKの `{}` フィールドは空文字列のまま
#   ("{}" Too many arguments、コマンド名が既知/未知いずれの場合も同じ)。
#
# mopidy_mpd側 (tokenize.py split()) は PARAM_RE でトークンを1つずつ剥がして
# result (= [command, *args]) へ無条件に append し続けるだけで総数の上限が無く、
# 例えば同じコマンド名に対し引数トークンを100個以上並べても
# tokenize.split() 自体は成功してしまい、後続のコマンドハンドラ(存在すれば
# その引数個数チェック、存在しなければ unknown command)へそのまま渡ってしまう。
#
# BACKLOG.md/nix/lib/mopidy-env.nixを"ARGV_MAX"/"argv_max"/"Too many arguments"/
# "COMMAND_ARGV_MAX"/"引数の総数"/"引数上限"で検索したが既出無し。tokenize.pyを
# 触る既存パッチ(mpdauthtabsplit/mpdcmdlisttabsplit/mpdcommandnamecase/
# mpdstrictnumparse/mpdtokenizecommandnone)を確認したが、いずれもコマンド名の
# 字句解析(WORD_RE)や数値パーサの文字種/範囲の話であり、split()の
# 引数トークン総数という別軸には触れていない。
#
# 修正: tokenize.py に実MPDのCOMMAND_ARGV_MAXと同値のモジュール定数を追加し、
# split()のwhileループ内、PARAM_REでのトークン抽出成功直後・result.appendの
# 直前に「resultに既にCOMMAND_ARGV_MAX個の引数が入っていれば拒否」する検査を
# 追加(実MPDのargv.full()と同じ検査タイミング)。raiseするMpdArgErrorの
# commandは実MPDの「SetCommand()未実行=空文字列」に合わせ""を明示指定
# (mpdtokenizecommandnone-patch.pyと同じ流儀。指定しないとMpdAckError.__init__
# のデフォルトcommand=Noneのまま伝播し、tokenize.split()の例外はdispatcher.pyの
# tokens[0]によるcommand補完(protocol.commands.call()を囲むtry節の中でのみ動作
# し、split()自体には掛からない)を一切通らないため、同ファイルの過去のバグ
# (mpdtokenizecommandnone-patch.py)と同じ"{None}"漏れを再発させてしまう)。

p = "mopidy_mpd/tokenize.py"
s = open(p).read()

CONST_MARKER = "_MPD_COMMAND_ARGV_MAX = "
if CONST_MARKER in s:
    print("mpdargvmax already applied to tokenize.py, skip")
else:
    old_import = "from mopidy_mpd import exceptions\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = (
        "from mopidy_mpd import exceptions\n"
        "\n"
        "#: mpdargvmax-patch.py: 実MPDのCOMMAND_ARGV_MAX (src/command/AllCommands.cxx)\n"
        "#: と同値。 2 + TAG_NUM_OF_ITEM_TYPES*2 (src/tag/Type.hxx、現行36種のタグ型)\n"
        "#: = 2 + 36*2 = 74。1コマンド行あたりの引数トークン数(コマンド名を除く)\n"
        "#: がこれを超えたら実MPDのargv.full()同様に拒否する。\n"
        "_MPD_COMMAND_ARGV_MAX = 74\n"
    )
    s = s.replace(old_import, new_import, 1)

    old_loop = (
        "    result = [command]\n"
        "    while remainder:\n"
        "        match = PARAM_RE.match(remainder)\n"
        "        if not match:\n"
        "            msg = _determine_error_message(remainder)\n"
        "            raise exceptions.MpdArgError(msg, command=command)\n"
        "        unquoted, quoted, remainder = match.groups()\n"
        "        result.append(unquoted or UNESCAPE_RE.sub(r\"\\g<1>\", quoted))\n"
        "    return result\n"
    )
    assert s.count(old_loop) == 1, f"old_loop count={s.count(old_loop)}"
    new_loop = (
        "    result = [command]\n"
        "    while remainder:\n"
        "        match = PARAM_RE.match(remainder)\n"
        "        if not match:\n"
        "            msg = _determine_error_message(remainder)\n"
        "            raise exceptions.MpdArgError(msg, command=command)\n"
        "        if len(result) - 1 >= _MPD_COMMAND_ARGV_MAX:\n"
        "            # mpdargvmax-patch.py: 実MPDのargv.full()と同じ検査タイミング\n"
        "            # (トークン抽出成功直後、result.append直前)。command_checked_lookup()\n"
        "            # (=SetCommand())より前段のため、実MPD同様commandは空文字列のまま。\n"
        "            raise exceptions.MpdArgError(\"Too many arguments\", command=\"\")\n"
        "        unquoted, quoted, remainder = match.groups()\n"
        "        result.append(unquoted or UNESCAPE_RE.sub(r\"\\g<1>\", quoted))\n"
        "    return result\n"
    )
    s = s.replace(old_loop, new_loop, 1)

    open(p, "w").write(s)
    print(
        "patched tokenize.py: split()が1コマンド行あたりの引数トークン数に"
        "上限を設けていない不具合を修正 (実MPDのCOMMAND_ARGV_MAX=74と同じ上限を"
        "超えたらACK Too many argumentsを返す)"
    )
