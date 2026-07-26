# `tagtypes enable/disable {NAME...}` / `protocol enable/disable {FEATURE...}` /
# `stringnormalization enable/disable {FEATURE...}` (connection.py、mpdstringnorm-patch.py/
# mpdprotocol-patch.pyが追加した2コマンドも同型) が、いずれも `_validate_*(parameters)` で
# `set(parameters).issubset(既知の固定集合)` という大文字小文字を区別する完全一致判定を行って
# いる不具合。TODO 全項目消化済みのため自走エージェントがExploreサブエージェントに委任し
# connection.py/current_playlist.pyを既存パッチ群と突き合わせて新規発見・追加した項目。
#
# 実 MPD (MusicPlayerDaemon/MPD を実際に gh raw で取得しソース確認) はこの3コマンドいずれも
# 大文字小文字を区別しない専用パーサーで名前解決している:
#   - `tagtypes`: src/command/ClientCommands.cxx の ParseTagMask() が
#     src/tag/ParseName.cxx の tag_name_parse_i()(StringIsEqualIgnoreCase)を使用
#   - `protocol`: 同ファイルの ParseProtocolFeature() が protocol_feature_parse_i() を使用
#   - `stringnormalization`: 同ファイルの ParseStringNormalization() が
#     string_normalization_parse_i() を使用
# つまり `tagtypes disable artist`(小文字)は実 MPD では `tagtypes disable Artist` と等価に
# 動作するが、本実装では `TAGTYPE_LIST` が `{"Artist", "Album", ...}` という大文字始まりの
# 固定集合のため小文字を渡すと `ACK Unknown tag type` になり失敗する。mpdprotocol-patch.py
# 自身のコメントに「(StringIsEqualIgnoreCase で大文字小文字を区別しない)」と実MPD仕様を
# 明記していながら実装がその通りになっていない(コード⇔コメント不一致)ことでも発覚。
#
# 仮に issubset の判定だけ緩めても、`context.session.tagtypes.update(parameters)` 等は
# 検証前の生の文字列をそのままセットへ格納するため、出力側の translator._has_value() の
# `tagtype in tagtypes`(`tagtype` は "Artist" 等の固定表記のキー)判定と一致せず、
# enable/disableが実質無効化されたまま(タグが消えない/意図せず出続ける)になってしまう。
# そのため単純に issubset の集合を大文字小文字無視に変えるのではなく、正規名へ解決した
# 上でセットに格納する必要がある。
#
# `addtagid`/`cleartagid` (mpdaddtagid-patch.py) が同じ問題を `_mpd_canonical_tag_type()`
# (小文字比較で1件ずつ正規名を解決)で既に正しく解決済みだったため、同じ手法を
# `tagtypes`/`stringnormalization`/`protocol` の3関数に適用し、`_validate_*` (bool検証のみ)
# を `_resolve_*` (正規名リストを返す)へ置き換える。
cp = "mopidy_mpd/protocol/connection.py"
c = open(cp).read()

MARKER = "_resolve_tagtypes"
if MARKER in c:
    print("connection.py already patched for case-insensitive tagtypes/protocol/stringnormalization, skip")
else:
    # --- tagtypes ---
    old_def = (
        "def _validate_tagtypes(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    if not param_set.issubset(tagtype_list.TAGTYPE_LIST):\n"
        '        raise exceptions.MpdArgError("Unknown tag type")\n'
    )
    assert c.count(old_def) == 1, f"tagtypes def count={c.count(old_def)}"
    new_def = (
        "def _resolve_tagtypes(parameters):\n"
        "    # 実 MPD (tag_name_parse_i) と同様、大文字小文字を無視して正規名へ解決する。\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    lookup = {known.lower(): known for known in tagtype_list.TAGTYPE_LIST}\n"
        "    resolved = []\n"
        "    for name in param_set:\n"
        "        canonical = lookup.get(name.lower())\n"
        "        if canonical is None:\n"
        '            raise exceptions.MpdArgError("Unknown tag type")\n'
        "        resolved.append(canonical)\n"
        "    return resolved\n"
    )
    c = c.replace(old_def, new_def, 1)

    old_calls = (
        '        elif subcommand == "disable":\n'
        "            _validate_tagtypes(parameters)\n"
        "            context.session.tagtypes.difference_update(parameters)\n"
        '        elif subcommand == "enable":\n'
        "            _validate_tagtypes(parameters)\n"
        "            context.session.tagtypes.update(parameters)\n"
    )
    assert c.count(old_calls) == 1, f"tagtypes calls count={c.count(old_calls)}"
    new_calls = (
        '        elif subcommand == "disable":\n'
        "            context.session.tagtypes.difference_update(\n"
        "                _resolve_tagtypes(parameters)\n"
        "            )\n"
        '        elif subcommand == "enable":\n'
        "            context.session.tagtypes.update(_resolve_tagtypes(parameters))\n"
    )
    c = c.replace(old_calls, new_calls, 1)

    # --- stringnormalization ---
    old_def = (
        "def _validate_stringnorm_features(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    if not param_set.issubset(_STRINGNORM_FEATURES):\n"
        '        raise exceptions.MpdArgError("Unknown string normalization")\n'
    )
    assert c.count(old_def) == 1, f"stringnorm def count={c.count(old_def)}"
    new_def = (
        "def _resolve_stringnorm_features(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    lookup = {f.lower(): f for f in _STRINGNORM_FEATURES}\n"
        "    resolved = []\n"
        "    for name in param_set:\n"
        "        canonical = lookup.get(name.lower())\n"
        "        if canonical is None:\n"
        '            raise exceptions.MpdArgError("Unknown string normalization")\n'
        "        resolved.append(canonical)\n"
        "    return resolved\n"
    )
    c = c.replace(old_def, new_def, 1)

    old_calls = (
        '    elif subcommand == "enable":\n'
        "        _validate_stringnorm_features(parameters)\n"
        "        context.session.string_normalization.update(parameters)\n"
        '    elif subcommand == "disable":\n'
        "        _validate_stringnorm_features(parameters)\n"
        "        context.session.string_normalization.difference_update(parameters)\n"
    )
    assert c.count(old_calls) == 1, f"stringnorm calls count={c.count(old_calls)}"
    new_calls = (
        '    elif subcommand == "enable":\n'
        "        context.session.string_normalization.update(\n"
        "            _resolve_stringnorm_features(parameters)\n"
        "        )\n"
        '    elif subcommand == "disable":\n'
        "        context.session.string_normalization.difference_update(\n"
        "            _resolve_stringnorm_features(parameters)\n"
        "        )\n"
    )
    c = c.replace(old_calls, new_calls, 1)

    # --- protocol ---
    old_def = (
        "def _validate_protocol_features(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    if not param_set.issubset(_PROTOCOL_FEATURES):\n"
        '        raise exceptions.MpdArgError("Unknown protocol feature")\n'
    )
    assert c.count(old_def) == 1, f"protocol def count={c.count(old_def)}"
    new_def = (
        "def _resolve_protocol_features(parameters):\n"
        "    param_set = set(parameters)\n"
        "    if not param_set:\n"
        '        raise exceptions.MpdArgError("Not enough arguments")\n'
        "    lookup = {f.lower(): f for f in _PROTOCOL_FEATURES}\n"
        "    resolved = []\n"
        "    for name in param_set:\n"
        "        canonical = lookup.get(name.lower())\n"
        "        if canonical is None:\n"
        '            raise exceptions.MpdArgError("Unknown protocol feature")\n'
        "        resolved.append(canonical)\n"
        "    return resolved\n"
    )
    c = c.replace(old_def, new_def, 1)

    old_calls = (
        '    elif subcommand == "enable":\n'
        "        _validate_protocol_features(parameters)\n"
        "        context.session.protocol_features.update(parameters)\n"
        '    elif subcommand == "disable":\n'
        "        _validate_protocol_features(parameters)\n"
        "        context.session.protocol_features.difference_update(parameters)\n"
    )
    assert c.count(old_calls) == 1, f"protocol calls count={c.count(old_calls)}"
    new_calls = (
        '    elif subcommand == "enable":\n'
        "        context.session.protocol_features.update(\n"
        "            _resolve_protocol_features(parameters)\n"
        "        )\n"
        '    elif subcommand == "disable":\n'
        "        context.session.protocol_features.difference_update(\n"
        "            _resolve_protocol_features(parameters)\n"
        "        )\n"
    )
    c = c.replace(old_calls, new_calls, 1)

    open(cp, "w").write(c)
    print(
        "patched connection.py: tagtypes/protocol/stringnormalization の "
        "enable/disable を大文字小文字を区別しない解決に変更"
    )
