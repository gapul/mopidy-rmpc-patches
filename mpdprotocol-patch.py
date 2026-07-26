# mopidy-mpd 3.3.0 は `protocol` (MPD 0.24+, connection settings section) を一切登録して
# いない (`ACK unknown command`)。TODO 全項目消化済みのため自走エージェントが実 MPD の完全な
# コマンド一覧 (mpd.readthedocs.io/protocol.html) と mopidy_mpd の登録済みコマンド一覧を
# 突き合わせて新規発見・追加した項目 (rmpc 本体を実際に clone して調査したが
# rmpc-mpd/src/mpd_client.rs 、rmpc/src 双方に `protocol` コマンドの送信箇所は無く、rmpc固有の
# 実害ではなく decoders/mixrampdb/outputs-plugin と同種の「標準 MPD プロトコル準拠」の不備)。
#
# 実 MPD (MusicPlayerDaemon/MPD を実際に gh api で確認: src/command/ClientCommands.cxx
# handle_protocol、src/client/ProtocolFeature.{hxx,cxx}) を確認し仕様を確定:
#   - 対応 FEATURE は "hide_playlists_in_root" の1種類のみ (現行 MPD 最新版時点)
#   - `protocol` (引数無し): 現在有効な機能を `feature: NAME` で列挙 (キーは
#     "protocol"/"stringnormalization" ではなく "feature"、ProtocolFeature.cxx
#     protocol_features_print の `r.Fmt("feature: {}\n", ...)` で確認)
#   - `protocol all`: 全機能を有効化 (余分な引数があれば `ACK Too many arguments`)
#   - `protocol clear`: 全機能を無効化 (同上)
#   - `protocol available`: 対応している全機能を列挙 (有効/無効に関わらず、同上、キーも "feature")
#   - `protocol enable {FEATURE...}` / `disable {FEATURE...}`: 引数無しなら
#     `ACK Not enough arguments`、未知の FEATURE なら `ACK Unknown protocol feature`
#     (StringIsEqualIgnoreCase で大文字小文字を区別しない)
#   - 未知のサブコマンドは `ACK Unknown sub command`
#   - 状態はクライアント接続ごと (実 MPD の Client メンバ、切断で消える) —
#     mpdstringnorm-patch.py の `context.session.string_normalization` と全く同じ流儀で
#     `context.session` の属性として保持すればよい。
#
# `hide_playlists_in_root` の実際の効果 (ProtocolFeature.hxx のコメント "disables the listing
# of stored playlists for the lsinfo") を実装するには mopidy_mpd 側で実際にストアドプレイリスト
# を列挙している箇所を見つける必要がある。music_db.py の `lsinfo` がルート (`uri in (None, "",
# "/")`) の場合に無条件で `protocol.stored_playlists.listplaylists(context)` を追記しており
# (docstring 曰く "When listing the root directory, this currently returns the list of stored
# playlists. This behavior is deprecated; use listplaylists instead." — まさに実 MPD が
# `hide_playlists_in_root` で無効化できる対象と一致)、ここを機能フラグでゲートすれば良いと
# 判明。`listplaylists` コマンド自体 (専用コマンド) は実 MPD 同様この機能の影響を受けない
# (lsinfo 経由の暗黙列挙のみを止める) ため、既存の `listplaylists` 呼び出しは無変更で維持する。

sp = "mopidy_mpd/session.py"
s_session = open(sp).read()

SESSION_MARKER = "self.protocol_features = set()"
if SESSION_MARKER in s_session:
    print("session.py already patched, skip")
else:
    anchor = "        self.string_normalization = set()\n"
    assert s_session.count(anchor) == 1, f"session anchor count={s_session.count(anchor)}"
    replacement = anchor + (
        "        # MPD 0.24+ protocol: このセッションで有効なプロトコル機能\n"
        "        # (現状 hide_playlists_in_root のみ)。実 MPD 同様、接続ごとに保持し切断で破棄。\n"
        "        self.protocol_features = set()\n"
    )
    s_session = s_session.replace(anchor, replacement, 1)
    open(sp, "w").write(s_session)
    print("patched session.py: protocol_features state を追加")

cp = "mopidy_mpd/protocol/connection.py"
s_conn = open(cp).read()

CONN_MARKER = '@protocol.commands.add("protocol")'
if CONN_MARKER in s_conn:
    print("connection.py already patched, skip")
else:
    anchor = (
        "    elif subcommand == \"disable\":\n"
        "        _validate_stringnorm_features(parameters)\n"
        "        context.session.string_normalization.difference_update(parameters)\n"
        "    else:\n"
        "        raise exceptions.MpdArgError(\"Unknown sub command\")\n"
        "    return None\n"
    )
    assert s_conn.count(anchor) == 1, f"conn anchor count={s_conn.count(anchor)}"

    helper = anchor + '''

_PROTOCOL_FEATURES = frozenset({"hide_playlists_in_root"})


def _validate_protocol_features(parameters):
    param_set = set(parameters)
    if not param_set:
        raise exceptions.MpdArgError("Not enough arguments")
    if not param_set.issubset(_PROTOCOL_FEATURES):
        raise exceptions.MpdArgError("Unknown protocol feature")


@protocol.commands.add("protocol")
def mpd_protocol_features(context, *parameters):
    """
    *mpd.readthedocs.io, connection settings section:*

        ``protocol``

        Shows a list of enabled protocol features.

        ``protocol disable {FEATURE...}``

        Disables one or more protocol features.

        ``protocol enable {FEATURE...}``

        Enables one or more protocol features.

        ``protocol clear``

        Disables all protocol features.

        ``protocol all``

        Enables all protocol features.

        ``protocol available``

        Lists all available protocol features.
    """
    parameters = list(parameters)
    if not parameters:
        return [
            ("feature", feature)
            for feature in sorted(context.session.protocol_features)
        ]
    subcommand = parameters.pop(0).lower()
    if subcommand == "all":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        context.session.protocol_features = set(_PROTOCOL_FEATURES)
    elif subcommand == "clear":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        context.session.protocol_features = set()
    elif subcommand == "available":
        if parameters:
            raise exceptions.MpdArgError("Too many arguments")
        return [
            ("feature", feature)
            for feature in sorted(_PROTOCOL_FEATURES)
        ]
    elif subcommand == "enable":
        _validate_protocol_features(parameters)
        context.session.protocol_features.update(parameters)
    elif subcommand == "disable":
        _validate_protocol_features(parameters)
        context.session.protocol_features.difference_update(parameters)
    else:
        raise exceptions.MpdArgError("Unknown sub command")
    return None
'''
    s_conn = s_conn.replace(anchor, helper, 1)
    open(cp, "w").write(s_conn)
    print("patched connection.py: protocol コマンドを追加")

mp = "mopidy_mpd/protocol/music_db.py"
s_mdb = open(mp).read()

MDB_MARKER = '"hide_playlists_in_root" not in context.session.protocol_features'
if MDB_MARKER in s_mdb:
    print("music_db.py already patched, skip")
else:
    anchor = (
        '    if uri in (None, "", "/"):\n'
        "        result.extend(protocol.stored_playlists.listplaylists(context))\n"
    )
    assert s_mdb.count(anchor) == 1, f"music_db anchor count={s_mdb.count(anchor)}"
    replacement = (
        '    if uri in (None, "", "/") and (\n'
        '        "hide_playlists_in_root" not in context.session.protocol_features\n'
        "    ):\n"
        "        result.extend(protocol.stored_playlists.listplaylists(context))\n"
    )
    s_mdb = s_mdb.replace(anchor, replacement, 1)
    open(mp, "w").write(s_mdb)
    print("patched music_db.py: lsinfo の暗黙プレイリスト列挙を hide_playlists_in_root でゲート")
