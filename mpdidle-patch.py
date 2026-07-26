# mopidy-mpd 3.3.0 の `idle [SUBSYSTEMS...]` (mopidy_mpd/protocol/status.py) は
# ソース自身に `# TODO: test against valid subsystems` と残されている通り、クライアントが
# 送った SUBSYSTEMS 引数を一切検証しない。存在しないサブシステム名 (typo 含む) を送っても
# 黙って `context.subscriptions` に追加するだけで、該当イベントは絶対に発火しないため
# 実質「その idle 呼び出しは(他の有効な引数が無ければ)永久にブロックしたまま応答が返らない」
# という無言のハングになる。TODO 全項目消化済みのため自走エージェントが
# mopidy_mpd 本体に残る他の `# TODO` コメント (music_db.py/status.py/dispatcher.py/
# stored_playlists.py 等) を洗い出す中で発見し、実 MPD
# (MusicPlayerDaemon/MPD src/command/OtherCommands.cxx handle_idle,
# src/protocol/IdleFlags.cxx idle_parse_name/idle_names) を実際に取得してソース確認した
# ところ、実 MPD は各引数を `idle_names` (database/stored_playlist/playlist/player/mixer/
# output/options/sticker/update/subscription/message/neighbor/mount/partition の14種、
# 大文字小文字を区別しない ASCII 比較) と照合し、1つでも一致しなければ即座に
# `ACK_ERROR_ARG` (コード2) で `Unrecognized idle event: {name}` を返し、idle モードには
# 一切入らない (状態変更も無い) ことを確認した。
#
# さらに mopidy_mpd の `SUBSYSTEMS` 定数自体、実 MPD の `idle_names` 14種のうち
# `neighbor` だけが欠落している (13種のみ) ことも判明。`listneighbors`
# (mpdlistneighbors-patch.py) はプラグイン皆無のため常に ACK エラーだが、"neighbor"
# という名前自体は実 MPD で正当なサブシステム名であり、mopidy 側にも neighbor
# 探索プラグインの実装が無いだけで名前としては予約されているべきなので、
# `idle neighbor` は(検証を追加した後も)エラーにせず正常に受理できるよう
# SUBSYSTEMS にも追加する。
#
# 実装: 実 MPD と同じ2段構成 — 受け取った引数を先に全件検証 (大文字小文字を区別しない
# 比較、実 MPD の StringEqualsCaseASCII に相当) し、1つでも不正なら
# `context.subscriptions` を一切変更せず即座に ACK エラー、全件正当なら小文字化して
# 従来通り登録する。rmpc 本体 (mierak/rmpc) は常に有効なサブシステム名のみ送信するため
# 実害は無いが (grep 済み)、`command_blacklist` 越しに任意コマンドを送れる汎用
# MPD クライアント (mpc/ncmpcpp 等) が typo したサブシステム名を送った場合の
# 無応答ハングを防ぐ、標準 MPD プロトコル準拠の不備修正。

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER = "Unrecognized idle event"
if MARKER in s:
    print("status.py already patched, skip")
else:
    old_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "options",\n'
        '    "output",\n'
        '    "partition",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "sticker",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]"
    )
    assert s.count(old_subsystems) == 1, f"old_subsystems count={s.count(old_subsystems)}"
    new_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "neighbor",\n'
        '    "options",\n'
        '    "output",\n'
        '    "partition",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "sticker",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]"
    )
    assert new_subsystems != old_subsystems
    s = s.replace(old_subsystems, new_subsystems, 1)

    old_body = (
        "    # TODO: test against valid subsystems\n"
        "\n"
        "    if not subsystems:\n"
        "        subsystems = SUBSYSTEMS\n"
        "\n"
        "    for subsystem in subsystems:\n"
        "        context.subscriptions.add(subsystem)\n"
    )
    assert s.count(old_body) == 1, f"old_body count={s.count(old_body)}"
    new_body = (
        "    # 実MPD (OtherCommands.cxx handle_idle) と同じく、引数を1つでも登録する前に\n"
        "    # 全件を既知のサブシステム名 (大文字小文字を区別しない) と照合し、不正な名前が\n"
        "    # あれば状態を一切変更せず即座に ACK エラーにする (無効な名前を黙って登録すると\n"
        "    # 該当イベントが永遠に発火せず idle が無応答のままハングするため)。\n"
        "    for subsystem in subsystems:\n"
        "        if subsystem.lower() not in SUBSYSTEMS:\n"
        "            raise exceptions.MpdArgError(\n"
        "                f\"Unrecognized idle event: {subsystem}\"\n"
        "            )\n"
        "\n"
        "    if not subsystems:\n"
        "        subsystems = SUBSYSTEMS\n"
        "\n"
        "    for subsystem in subsystems:\n"
        "        context.subscriptions.add(subsystem.lower())\n"
    )
    assert new_body != old_body
    s = s.replace(old_body, new_body, 1)

    open(sp, "w").write(s)
    print(
        "patched status.py: idle が不正なサブシステム名を ACK エラーで拒否するよう修正 "
        "(SUBSYSTEMS に neighbor も追加)"
    )
