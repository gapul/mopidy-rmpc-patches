# `binarylimit {SIZE}` (mpdbinarylimitargerr-patch.py が下限(64未満)と非数値引数の
# バリデーションを実MPD準拠に修正済み) に、実MPDが持つ上限チェックが一切無い不具合。
#
# 実MPD本体 (MusicPlayerDaemon/MPD、gh rawで src/command/ClientCommands.cxx の
# handle_binary_limit() を確認):
#   size_t value = args.ParseUnsigned(0, client.GetOutputMaxSize() - 4096);
# `ParseUnsigned` (src/protocol/ArgParser.cxx) は第2引数を上限として渡され、
# 超過時に ACK_ERROR_ARG (2) の "Number too large" を送出する。`GetOutputMaxSize()`
# (src/event/FullyBufferedSocket.hxx) はサーバ設定 `max_output_buffer_size`
# (デフォルト `CLIENT_MAX_OUTPUT_BUFFER_SIZE_DEFAULT` = 8192*1024バイト、
# src/client/Config.cxx) が返す値そのもの。つまり実際の上限はデフォルト設定下で
# 8192*1024 - 4096 = 8,384,512 であり、これは protocol.UINT が持つ汎用の
# 0xFFFFFFFF (mpduintmax-patch.py) よりもずっと小さいコマンド固有の上限。
#
# mopidy_mpd の binarylimit() は下限のみを明示チェックしており、上限は
# protocol.UINT のパース時チェック (0xFFFFFFFF) しか無いため、8,384,513 から
# 4,294,967,295 までの値が本来 ACK "Number too large" されるべきところ黙って
# OK になってしまう。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
# BACKLOG.md全体を"8384512"/"8388608"/"client_max_output_buffer_size"/
# "GetOutputMaxSize"で検索したが既出無し(既存のbinarylimit項目は下限・非数値
# バリデーションのみを扱っている)。
#
# 修正: mopidy_mpd 側に相当するサーバ設定は存在しないため、実MPDのデフォルト値
# 8192*1024バイトを `client_max_output_buffer_size` 相当としてハードコードし、
# `_MPD_BINARYLIMIT_MAX = 8192 * 1024 - 4096` (= 8,384,512) を超える limit を
# 既存の "Value too small" と同じ流儀で exceptions.MpdArgError("Number too
# large") として ACK する。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

NEW = (
    '@protocol.commands.add("binarylimit", limit=protocol.UINT)\n'
    "def binarylimit(context, limit):\n"
    "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。\n"
    "    # 実MPD (ClientCommands.cxx handle_binary_limit()) と同じく64未満は拒否。\n"
    "    if limit < 64:\n"
    '        raise exceptions.MpdArgError("Value too small")\n'
    "    # 実MPDのGetOutputMaxSize()-4096 (デフォルトclient_max_output_buffer_size\n"
    "    # =8192*1024バイト相当) を超える値も同じくACKで拒否する\n"
    "    # (mpdbinarylimitmax-patch.py)。\n"
    "    if limit > _MPD_BINARYLIMIT_MAX:\n"
    '        raise exceptions.MpdArgError("Number too large")\n'
    "    context.session.binary_limit = limit\n"
)

if NEW in s:
    print("binarylimit max-size guard already patched, skip")
else:
    OLD = (
        '@protocol.commands.add("binarylimit", limit=protocol.UINT)\n'
        "def binarylimit(context, limit):\n"
        "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。\n"
        "    # 実MPD (ClientCommands.cxx handle_binary_limit()) と同じく64未満は拒否。\n"
        "    if limit < 64:\n"
        '        raise exceptions.MpdArgError("Value too small")\n'
        "    context.session.binary_limit = limit\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(
        OLD,
        "_MPD_BINARYLIMIT_MAX = 8192 * 1024 - 4096\n\n\n" + NEW,
        1,
    )
    open(p, "w").write(s)
    print(
        "patched connection.py: binarylimitが実MPDのGetOutputMaxSize()-4096"
        "(デフォルト8,384,512)相当のコマンド固有上限を一切チェックせず、"
        "protocol.UINTの汎用上限0xFFFFFFFFまでの値を黙って受理していた不具合を"
        "修正 (超過時にACK Number too largeを送出)"
    )
