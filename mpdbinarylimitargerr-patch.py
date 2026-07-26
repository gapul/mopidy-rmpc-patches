# `binarylimit {SIZE}` (mpd-patch.py が rmpc の albumart/readpicture 対応のため追加した
# コネクション設定コマンド) に非数値・空文字・負数の SIZE (`binarylimit "abc"`、
# `binarylimit ""`、`binarylimit -5` 等) を渡すと `int(limit)` が素の `ValueError` を
# 送出するが、その直後の `except (TypeError, ValueError): pass` が無条件に握り潰して
# しまい、`context.session.binary_limit` を更新しないまま関数が正常終了してしまう
# 不具合。mopidy_mpd の dispatcher (`_add_ok_filter`) は例外(ACK)が飛ばなければ
# 無条件に "OK" を付加するため、不正な引数を渡したのにクライアントには
# `ACK` ではなく `OK` が返ってしまう(実MPD仕様からの逸脱)。
#
# さらに `64` 未満の有効な正の数値 (`binarylimit 10` 等) も、実 MPD
# (MusicPlayerDaemon/MPD `src/command/ClientCommands.cxx` の `handle_binary_limit()`、
# 実際に clone してソース確認: `args.ParseUnsigned(0, ...)` でパースした後
# `if (value < 64) { r.Error(ACK_ERROR_ARG, "Value too small"); return
# CommandResult::ERROR; }`)と異なり、現状は `max(64, int(limit))` で
# エラーにせず黙って64へクランプしOKを返してしまう。これも「不正な値を拒否せず
# 静かに補正して正常応答する」という、mpdregexvalidate-patch.py が直前に修正した
# 「不正な正規表現を黙って受理する」問題と同種の実害パターン。
#
# TODO/既知の残課題を全項目消化済みのため自走エージェントが横断調査
# (mpd-patch.py が実装した connection.py の全コマンドの引数バリデーションを
# 実MPDソースと突き合わせて再監査) して新規発見・追加した項目。
#
# 修正: `seekcur`/`playlistinfo` 等と同じ流儀 (mpdseekcurargerr-patch.py/
# mpdplaylistinfoargerr-patch.py) で、数値引数を `@protocol.commands.add(...,
# limit=protocol.UINT)` のようにデコレータの型バリデータへ委譲する
# (フレームワーク側の `validate()` が `ValueError` を自動的に
# `exceptions.MpdArgError("incorrect arguments")` へ変換し ACK にしてくれる)。
# 加えて `limit < 64` は実MPDと同じく `exceptions.MpdArgError("Value too
# small")` を明示的に送出し、クランプではなく ACK で拒否する。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

NEW = (
    '@protocol.commands.add("binarylimit", limit=protocol.UINT)\n'
    "def binarylimit(context, limit):\n"
    "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。\n"
    "    # 実MPD (ClientCommands.cxx handle_binary_limit()) と同じく64未満は拒否。\n"
    "    if limit < 64:\n"
    '        raise exceptions.MpdArgError("Value too small")\n'
    "    context.session.binary_limit = limit\n"
)

if NEW in s:
    print("binarylimit arg-error guard already patched, skip")
else:
    OLD = (
        '@protocol.commands.add("binarylimit")\n'
        "def binarylimit(context, limit):\n"
        "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。未実装エラー回避も兼ねる。\n"
        "    try:\n"
        "        context.session.binary_limit = max(64, int(limit))\n"
        "    except (TypeError, ValueError):\n"
        "        pass\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched connection.py: binarylimitが非数値/負数のSIZEをACKにせず"
        "except(TypeError, ValueError): passで握り潰しOKを返してしまう不具合、"
        "および64未満の有効な数値を拒否せず黙って64へクランプしてしまう不具合を修正 "
        "(protocol.UINTデコレータバリデータへ委譲しACK化、64未満は明示的にACK Value too small)"
    )
