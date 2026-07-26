# `sticker` コマンドの URI 実在検証(`_mpd_sticker_validate_uri()`)が、action名や
# 各actionごとの引数個数が正しいかのチェックより先に無条件で走ってしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 現状のsticker()は関数冒頭で
#     _mpd_sticker_check_type(field)
#     if action != "find":
#         _mpd_sticker_validate_uri(context, field, uri)
# を実行してから各action分岐(get/set/delete/inc/dec/list/find、未知語ならエラー)へ
# 進むため、「URIが存在しない」+「actionが未知語、または既知actionだが引数個数が違う」
# という壊れたコマンドに対して、本来送出すべき引数エラーより先にURI不在エラーが出て
# しまう(例: `sticker foobar song "存在しないuri" name` は本来action不明のエラーに
# なるべきだが、URI不在エラーが先に出る)。
#
# 実MPD本体(gh rawでsrc/command/StickerCommands.cxx handle_sticker()を確認)は
# `args.size() == N && StringIsEqual(cmd, "get")`のように**コマンド名と引数個数が
# 完全一致した分岐内でのみ**`handler->Get/Set/Inc/Dec/Delete/List()`(=URI検証の
# 発生源であるDomainHandler::ValidateUri()の呼び出し)を実行し、どの分岐にも
# 一致しない場合は`r.Error(ACK_ERROR_ARG, "bad request")`に落ちてURI検証は一切
# 行われない。つまり「引数が壊れているコマンド」に対しては、URIの実在有無に
# 関係なく常にACK_ERROR_ARG(2)を返すのが実MPDの挙動。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): `sticker foobar song
# "totally-bogus-uri-xyz" name`(未知action)が修正前`ACK [50@0] {sticker} no
# such song: totally-bogus-uri-xyz`、修正後`ACK [2@0] {sticker} Unknown sticker
# action: foobar`になることを確認。
#
# 修正: 関数冒頭の無条件`_mpd_sticker_validate_uri()`呼び出しを削除し、
# get/set/delete/inc/dec/listの各分岐内、その分岐固有の引数個数チェックが
# 通った直後(ヘルパー呼び出しの直前)に個別に呼ぶよう移動する
# (find分岐は元々呼んでおらず無変更、実MPDのDomainHandler::Find()もURI検証を
# 行わない非対称仕様と一致)。

import ast

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = (
    '        _mpd_sticker_validate_uri(context, field, uri)\n'
    "        return _mpd_sticker_list(context, field, uri)\n"
)
if MARKER in s:
    print("stickers.py sticker() validate-uri ordering already fixed, skip")
else:
    old_top = (
        "    _mpd_sticker_check_type(field)\n"
        '    if action != "find":\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        '    if action == "list":\n'
    )
    assert s.count(old_top) == 1, f"old_top count={s.count(old_top)}"
    new_top = (
        "    _mpd_sticker_check_type(field)\n"
        '    if action == "list":\n'
    )
    s = s.replace(old_top, new_top, 1)

    old_list = (
        '    if action == "list":\n'
        "        if rest:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        return _mpd_sticker_list(context, field, uri)\n"
    )
    assert s.count(old_list) == 1, f"old_list count={s.count(old_list)}"
    new_list = (
        '    if action == "list":\n'
        "        if rest:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        "        return _mpd_sticker_list(context, field, uri)\n"
    )
    s = s.replace(old_list, new_list, 1)

    old_get = (
        '    elif action == "get":\n'
        "        if len(rest) != 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        return _mpd_sticker_get(context, field, uri, rest[0])\n"
    )
    assert s.count(old_get) == 1, f"old_get count={s.count(old_get)}"
    new_get = (
        '    elif action == "get":\n'
        "        if len(rest) != 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        "        return _mpd_sticker_get(context, field, uri, rest[0])\n"
    )
    s = s.replace(old_get, new_get, 1)

    old_set = (
        '    elif action == "set":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_set(context, field, uri, rest[0], rest[1])\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    assert s.count(old_set) == 1, f"old_set count={s.count(old_set)}"
    new_set = (
        '    elif action == "set":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        "        _mpd_sticker_set(context, field, uri, rest[0], rest[1])\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    s = s.replace(old_set, new_set, 1)

    old_delete = (
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    assert s.count(old_delete) == 1, f"old_delete count={s.count(old_delete)}"
    new_delete = (
        '    elif action == "delete":\n'
        "        if len(rest) > 1:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        "        _mpd_sticker_delete(context, field, uri, rest[0] if rest else None)\n"
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    s = s.replace(old_delete, new_delete, 1)

    old_inc = (
        '    elif action == "inc":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "+")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    assert s.count(old_inc) == 1, f"old_inc count={s.count(old_inc)}"
    new_inc = (
        '    elif action == "inc":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "+")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    s = s.replace(old_inc, new_inc, 1)

    old_dec = (
        '    elif action == "dec":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "-")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    assert s.count(old_dec) == 1, f"old_dec count={s.count(old_dec)}"
    new_dec = (
        '    elif action == "dec":\n'
        "        if len(rest) != 2:\n"
        '            raise exceptions.MpdArgError("wrong number of arguments")\n'
        "        _mpd_sticker_validate_uri(context, field, uri)\n"
        '        _mpd_sticker_inc_dec(context, field, uri, rest[0], rest[1], "-")\n'
        "        _mpdsticker_notify()\n"
        "        return None\n"
    )
    s = s.replace(old_dec, new_dec, 1)

    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stickers.py: sticker()のURI実在検証を各actionの引数個数"
        "チェック通過後へ移動(実MPD準拠、引数不正時は常にACK 2)"
    )
