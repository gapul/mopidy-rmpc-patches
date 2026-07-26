# mopidy-mpd 3.3.0 の MpdUriMapper.refresh_playlists_mapping() (uri_mapper.py) は
# 名前→URI / URI→名前のキャッシュに一度登録したエントリを一切削除しない(pop/del する箇所が
# 存在しない)。rename() の実装自体が末尾に
# `# TODO: should we purge the mapping in an else?` と自認している通り、上流未対応の不具合。
#
# 再現: rmpc等で名前「Test」のプレイリストを作成し listplaylists 等で一度キャッシュさせた後
# (uri=U1)、それを削除して同じ名前「Test」で新規プレイリストを作る(YTMusic 等は削除ごとに
# 新IDを振るため uri=U2)。古い "Test"->U1 が _uri_from_name に残り続けるため、
# _create_unique_name("Test", U2) は「別URIで同名が既存」と誤判定し U2 側を "Test [2]" という
# 不要なサフィックス付き名前にしてしまう。さらに悪いのは、rm/load/playlistadd/rename が使う
# lookup_playlist_uri_from_name("Test") がキャッシュヒットする限り常に実在しない古い U1 を
# 返し続けるため、クライアントが「Test」という名前で操作しようとした対象が食い違う。
# rename() (URI が変わる新規作成+旧URI削除という実装) は毎回このケースを引き起こす。
p = "mopidy_mpd/uri_mapper.py"
s = open(p).read()

MARKER = "current_uris = {ref.uri for ref in playlist_refs}"
if MARKER in s:
    print("mpdplaylistcache already applied, skip")
else:
    old_block = (
        "    def refresh_playlists_mapping(self):\n"
        '        """\n'
        "        Maintain map between playlists and unique playlist names to be used by\n"
        "        MPD.\n"
        '        """\n'
        "        if self.core is None:\n"
        "            return\n"
        "\n"
        "        for playlist_ref in self.core.playlists.as_list().get():\n"
        "            if not playlist_ref.name:\n"
        "                continue\n"
        '            name = self._invalid_playlist_chars.sub("|", playlist_ref.name)\n'
        "            self.insert(name, playlist_ref.uri, playlist=True)\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    def refresh_playlists_mapping(self):\n"
        '        """\n'
        "        Maintain map between playlists and unique playlist names to be used by\n"
        "        MPD.\n"
        "\n"
        "        Also purges cache entries for playlists that no longer exist (renamed\n"
        "        away or deleted), so a reused name does not keep resolving to a dead\n"
        "        URI and does not get needlessly uniquified against itself.\n"
        '        """\n'
        "        if self.core is None:\n"
        "            return\n"
        "\n"
        "        playlist_refs = [\n"
        "            ref for ref in self.core.playlists.as_list().get() if ref.name\n"
        "        ]\n"
        "        current_uris = {ref.uri for ref in playlist_refs}\n"
        "\n"
        "        stale_uris = set(self._playlist_name_from_uri) - current_uris\n"
        "        for uri in stale_uris:\n"
        "            stale_name = self._playlist_name_from_uri.pop(uri)\n"
        "            if self._uri_from_name.get(stale_name) == uri:\n"
        "                del self._uri_from_name[stale_name]\n"
        "\n"
        "        for playlist_ref in playlist_refs:\n"
        '            name = self._invalid_playlist_chars.sub("|", playlist_ref.name)\n'
        "            self.insert(name, playlist_ref.uri, playlist=True)\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    open(p, "w").write(s)
    print(
        "patched uri_mapper.py: refresh_playlists_mapping()が削除/リネームされた"
        "旧プレイリストのキャッシュを永久に残す不具合を修正 (再利用された名前の誤判定を解消)"
    )
