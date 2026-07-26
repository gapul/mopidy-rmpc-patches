# mopidy-mpd 3.3.0 は `stringnormalization` (MPD 0.25+, string normalization commands
# section) を一切登録していない (`ACK unknown command`)。rmpc 本体 (mierak/rmpc) を実際に
# clone してソース確認したところ、rmpc-mpd/src/client.rs の `search()` は
# `self.supported_commands.contains("stringnormalization")` かつ ignore_diacritics 有効時に
# `stringnormalization enable strip_diacritics` -> `search` -> `stringnormalization disable
# strip_diacritics` をコマンドリストで送る実装で、rmpc/src/ui/panes/search/mod.rs の検索ペインは
# `strip_diacritics_supported: ctx.mpd_version >= Version::new(0, 25, 0)` の場合のみ
# 「Ignore diacritics」トグルを表示する。mpdversion-patch.py は当時この機能が未実装だったため
# 意図的に VERSION を 0.24.0 に留めてこのトグル自体を隠していた
# ("stringnormalization は未実装のため 0.25 は名乗らない" とコメント済み)。本パッチで
# `stringnormalization` を実装した上で、mpdversion-patch.py 側の VERSION を 0.25.0 へ引き上げ、
# 実際にトグルが機能するようにする (対になる作業は mpdversion-patch.py 側で実施)。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/ClientCommands.cxx handle_string_normalization,
# src/client/StringNormalization.{hxx,cxx}) を実際に clone してソース確認し仕様を確定:
#   - 対応 FEATURE は "strip_diacritics" の1種類のみ
#   - `stringnormalization` (引数無し): 現在有効な機能を `stringnormalization: NAME` で列挙
#   - `stringnormalization all`: 全機能を有効化 (余分な引数があれば `ACK Too many arguments`)
#   - `stringnormalization clear`: 全機能を無効化 (同上)
#   - `stringnormalization available`: 対応している全機能を列挙 (有効/無効に関わらず、同上)
#   - `stringnormalization enable {FEATURE...}` / `disable {FEATURE...}`: 引数無しなら
#     `ACK Not enough arguments`、未知の FEATURE なら `ACK Unknown string normalization`
#   - 未知のサブコマンドは `ACK Unknown sub command`
#   - 状態はクライアント接続ごと (実 MPD の Client メンバ、切断で消える) — mopidy_mpd の
#     `context.session.tagtypes` と全く同じ流儀で `context.session` の属性として保持すればよく、
#     channels/partition のようなセッション横断の揮発性ストア・on_stop cleanup は不要。
#   - 実 MPD の `search`/`searchadd`/`searchaddpl`/`searchcount`/`playlistsearch` はこの状態を
#     読んで比較時に "NFD; 結合文字(Mark)を除去; NFC" (ICU strip_diacritics transliterator、
#     WebFetch/ソースで src/lib/icu/Canonicalize.cxx を確認済み) を適用するが、mopidy_mpd の
#     `search`/`find`/`count`/`list` は全て `context.core.library.search()` 経由でバックエンド
#     (mopidy-ytmusic ならリモート YouTube Music 検索API) へ丸投げしており、ローカルな文字列
#     比較を一切行わないため diacritics ストリップを適用する対象コードが存在しない (bare
#     `stringnormalization` の状態保持・プロトコル往復のみ提供、search 自体への効果は無し —
#     mount/crossfade と同種の割り切り)。唯一ローカルに文字列比較を行うのは
#     mpdplaylistfind-patch.py の `playlistsearch` (現在のキュー内の大文字小文字を区別しない
#     部分一致検索、実 MPD の QueueCommands.cxx でも strip_diacritics が実際に効く対象) なので、
#     そちらは本パッチと対になる形で mpdplaylistfind-patch.py 側に diacritics 対応を追加する。
sp = "mopidy_mpd/session.py"
s_session = open(sp).read()

SESSION_MARKER = "self.string_normalization = set()"
if SESSION_MARKER in s_session:
    print("session.py already patched, skip")
else:
    anchor = "        self.tagtypes = tagtype_list.TAGTYPE_LIST.copy()\n"
    assert s_session.count(anchor) == 1, f"session anchor count={s_session.count(anchor)}"
    replacement = anchor + (
        "        # MPD 0.25+ stringnormalization: このセッションで有効な正規化機能\n"
        "        # (現状 strip_diacritics のみ)。実 MPD 同様、接続ごとに保持し切断で破棄。\n"
        "        self.string_normalization = set()\n"
    )
    s_session = s_session.replace(anchor, replacement, 1)
    open(sp, "w").write(s_session)
    print("patched session.py: string_normalization state を追加")

cp = "mopidy_mpd/protocol/connection.py"
s_conn = open(cp).read()

CONN_MARKER = '@protocol.commands.add("stringnormalization")'
if CONN_MARKER in s_conn:
    print("connection.py already patched, skip")
else:
    anchor = (
        "def _validate_tagtypes(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    if not param_set.issubset(tagtype_list.TAGTYPE_LIST):\n"
        '        raise exceptions.MpdArgError("Unknown tag type")\n'
    )
    assert s_conn.count(anchor) == 1, f"conn anchor count={s_conn.count(anchor)}"

    helper = anchor + '''

_STRINGNORM_FEATURES = frozenset({"strip_diacritics"})


def _validate_stringnorm_features(parameters):
    param_set = set(parameters)
    if not param_set:
        raise exceptions.MpdArgError("Not enough arguments")
    if not param_set.issubset(_STRINGNORM_FEATURES):
        raise exceptions.MpdArgError("Unknown string normalization")


@protocol.commands.add("stringnormalization")
def stringnormalization(context, *parameters):
    """
    *mpd.readthedocs.io, string normalization commands section:*

        ``stringnormalization``

        Shows a list of enabled string normalization options when
        searching using ``search``.

        ``stringnormalization disable {FEATURE...}``

        Disables one or more string normalization options.

        ``stringnormalization enable {FEATURE...}``

        Enables one or more string normalization options.

        ``stringnormalization clear``

        Disables all string normalization options.

        ``stringnormalization all``

        Enables all string normalization options.

        ``stringnormalization available``

        Lists all available string normalization options.
    """
    parameters = list(parameters)
    if not parameters:
        return [
            ("stringnormalization", feature)
            for feature in sorted(context.session.string_normalization)
        ]
    subcommand = parameters.pop(0).lower()
    if subcommand == "all":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        context.session.string_normalization = set(_STRINGNORM_FEATURES)
    elif subcommand == "clear":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        context.session.string_normalization = set()
    elif subcommand == "available":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        return [
            ("stringnormalization", feature)
            for feature in sorted(_STRINGNORM_FEATURES)
        ]
    elif subcommand == "enable":
        _validate_stringnorm_features(parameters)
        context.session.string_normalization.update(parameters)
    elif subcommand == "disable":
        _validate_stringnorm_features(parameters)
        context.session.string_normalization.difference_update(parameters)
    else:
        raise exceptions.MpdArgError("Unknown sub command")
    return None
'''
    s_conn = s_conn.replace(anchor, helper, 1)
    open(cp, "w").write(s_conn)
    print("patched connection.py: stringnormalization コマンドを追加")
