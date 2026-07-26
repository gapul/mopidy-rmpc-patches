# mopidy-mpd 3.3.0 の `readcomments` はコメントアウトされた未登録コマンドで、本体も
# `pass` (何も返さない = クラッシュする) のスタブ。rmpc 等が楽観的に投げてきても
# 「未知コマンド」エラーにならないよう有効化する。mopidy の Track モデルは vorbis
# コメントのような任意 key-value ではなく単一の `comment` フィールドしか持たないため、
# 実データが無ければ空リスト (OK のみ、no such song でもない) で応答するのが妥当
# (仕様上も「対応していないデコーダでは空」が正しい)。URI がライブラリに存在しない
# 場合のみ `No such song` を返す。
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "@protocol.commands.add(\"readcomments\")"
if MARKER in s:
    print("readcomments already enabled, skip")
else:
    old_block = (
        "# TODO: add at least reflection tests before adding NotImplemented version\n"
        "# @protocol.commands.add('readcomments')\n"
        "def readcomments(context, uri):\n"
        '    """\n'
        "    *musicpd.org, music database section:*\n"
        "\n"
        "        ``readcomments [URI]``\n"
        "\n"
        '        Read "comments" (i.e. key-value pairs) from the file specified by\n'
        '        "URI". This "URI" can be a path relative to the music directory or a\n'
        '        URL in the form "file:///foo/bar.ogg".\n'
        "\n"
        "        This command may be used to list metadata of remote files (e.g. URI\n"
        '        beginning with "http://" or "smb://").\n'
        "\n"
        '        The response consists of lines in the form "KEY: VALUE". Comments with\n'
        "        suspicious characters (e.g. newlines) are ignored silently.\n"
        "\n"
        "        The meaning of these depends on the codec, and not all decoder plugins\n"
        "        support it. For example, on Ogg files, this lists the Vorbis comments.\n"
        '    """\n'
        "    pass\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = old_block.replace(
        "# @protocol.commands.add('readcomments')\ndef readcomments(context, uri):",
        '@protocol.commands.add("readcomments")\ndef readcomments(context, uri):',
    ).replace(
        '    """\n    pass\n',
        '    """\n'
        "    tracks = context.core.library.lookup(uris=[uri]).get().get(uri) or []\n"
        "    if not tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    comment = tracks[0].comment\n"
        "    if not comment:\n"
        "        return []\n"
        '    return [("comment", line) for line in comment.splitlines() if line.strip()]\n',
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    open(p, "w").write(s)
    print("patched music_db.py: readcomments を有効化 (comment フィールドを返却、無ければ空)")
