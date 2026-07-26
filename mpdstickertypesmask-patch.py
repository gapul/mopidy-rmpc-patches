# `stickertypes` が実MPD 0.24+と異なり、クライアントごとの `tagtypes`
# enable/disable/clear状態を一切反映せず、常に全17タグドメインを列挙してしまう
# 不具合を修正。TODO全項目消化済みのため自走エージェントが(general-purpose
# サブエージェントへの調査委任を経て)新規発見。実MPD本体(gh rawで
# src/command/StickerCommands.cxx handle_sticker_types()を確認)は
# `const auto tag_mask = global_tag_mask & r.GetTagMask();`で接続ごとの
# タグマスク(=tagtypesコマンドが操作するのと同じマスク、mopidy_mpdには
# `metadata_to_use`サーバ設定相当が無いためglobal_tag_mask側は常に全許可、
# mpdtagtypesavailablereset-patch.py導入時の既存方針と同じ)と
# sticker_allowed_tags(17タグの固定許可リスト)の両方を満たすタグ名のみを
# 列挙するが、mopidy_mpd側の`stickertypes()`(mpdstickertagdomain-patch.py導入)は
# `_MPD_STICKER_TAG_DOMAIN_NAMES`を無条件にそのまま返しており
# `context.session.tagtypes`を一切参照していなかった。
# 一方 `stickernamestypes {TYPE}` (handle_sticker_names_types()) は
# 別マスク(`sticker_allowed_tags`のみ、接続ごとのtagtypesマスクは無関係)で
# 判定しており対象外(既存の`_mpd_sticker_resolve_domain()`のままで良い)。
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント):
# `tagtypes clear` -> OK 後の `stickertypes` が修正前は変わらず全17タグ+
# song/playlist/filterの20行、修正後は song/playlist/filterの3行のみ。
# `tagtypes enable Artist` -> OK 後は `stickertype: Artist` の1行が追加され4行。
# `tagtypes all` -> OK で20行に復帰(回帰無し)。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_mpd_sticker_types_tagmask"
if MARKER in s:
    print("stickertypes tagtypes masking already present, skip")
else:
    old_stickertypes = (
        '    return [("stickertype", t) for t in _MPD_STICKER_DOMAINS] + [\n'
        '        ("stickertype", name) for name in _MPD_STICKER_TAG_DOMAIN_NAMES\n'
        "    ]\n"
    )
    assert s.count(old_stickertypes) == 1, (
        f"old_stickertypes count={s.count(old_stickertypes)}"
    )
    new_stickertypes = (
        "    return [\n"
        '        ("stickertype", t) for t in _MPD_STICKER_DOMAINS\n'
        "    ] + _mpd_sticker_types_tagmask(context)\n"
    )
    s = s.replace(old_stickertypes, new_stickertypes, 1)

    old_def_anchor = "@protocol.commands.add(\"stickertypes\")\ndef stickertypes(context):"
    assert s.count(old_def_anchor) == 1, f"old_def_anchor count={s.count(old_def_anchor)}"
    new_def_anchor = (
        "def _mpd_sticker_types_tagmask(context):\n"
        "    # 実MPD(handle_sticker_types)のtag_mask(接続ごとのtagtypesマスク)\n"
        "    # 相当。mopidy_mpdにはglobal_tag_mask(サーバ設定)に相当するものが\n"
        "    # 無いため常に全許可扱いとし、context.session.tagtypesのみで絞る。\n"
        "    return [\n"
        '        ("stickertype", name)\n'
        "        for name in _MPD_STICKER_TAG_DOMAIN_NAMES\n"
        "        if name in context.session.tagtypes\n"
        "    ]\n"
        "\n"
        "\n"
        '@protocol.commands.add("stickertypes")\n'
        "def stickertypes(context):"
    )
    s = s.replace(old_def_anchor, new_def_anchor, 1)

open(p, "w").write(s)
