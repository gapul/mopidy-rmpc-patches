# mopidy-mpd 3.3.0 の `decoders` は常に `return  # TODO` で何も返さない (OKのみ)。TODO 全項目
# 消化済みのため自走エージェントが rmpc 本体 (mierak/rmpc) を実際に clone して調査したところ、
# キーバインド 'op' (GlobalAction::ShowDecoders, rmpc/src/config/keys/mod.rs) で開く
# "Decoder plugins" モーダル (rmpc/src/ui/modals/decoders.rs) が client.decoders() の結果
# (plugin/mime_types/suffixes の3列テーブル) をそのまま描画する実装で、クラッシュはしない
# ものの常に空のモーダルが出るだけの実害ある新規ギャップと判明。
#
# 実装: mopidy の再生は GStreamer (playbin) 経由で、mopidy パッケージの nix closure に実際に
# 同梱されているプラグイン (gst-plugins-base/good/bad/ugly + gst-libav) が対応フォーマットを
# 決める (nix-store -q --requisites と各 lib/gstreamer-1.0/*.dylib で実在確認済み)。ただし
# GStreamer のプラグインレジストリは実行時の GST_PLUGIN_PATH 相当の設定に依存し、この
# パッケージ構成では自動では埋まらない (実際に Gst.Registry.get().get_feature_list() を
# 起動済み env で確認したところコア組込み要素のみでコーデック別プラグインは0件だった)ため、
# ライブでレジストリを introspection すると実装前と同じく空になってしまう。そのため
# mount/partition/outputs plugin 等と同じ「プロトコル層の応答を仕様に合わせるだけで実体は
# 静的」方針で、上記 closure に実在するプラグイン名と対応拡張子/MIMEタイプを静的に列挙する。
p = "mopidy_mpd/protocol/reflection.py"
s = open(p).read()

MARKER = "DECODER_PLUGINS = ["
if MARKER in s:
    print("decoders already added, skip")
else:
    import_anchor = "from mopidy_mpd import exceptions, protocol\n\n\n"
    assert s.count(import_anchor) == 1, f"import_anchor count={s.count(import_anchor)}"

    table = (
        import_anchor
        + "# mopidy パッケージの nix closure に実在するコーデック関連 GStreamer プラグイン\n"
        + "# (gst-plugins-base/good/bad/ugly + gst-libav) の静的な一覧。ライブのレジストリ\n"
        + "# 問い合わせはこの構成では空になるため使わない (詳細は mpddecoders-patch.py)。\n"
        + "DECODER_PLUGINS = [\n"
        + '    ("flac", ("flac",), ("audio/x-flac",)),\n'
        + '    ("vorbis", ("ogg", "oga"), ("audio/x-vorbis", "application/ogg")),\n'
        + '    ("opus", ("opus",), ("audio/x-opus", "audio/opus")),\n'
        + '    ("wavparse", ("wav",), ("audio/x-wav",)),\n'
        + '    ("wavpack", ("wv",), ("audio/x-wavpack",)),\n'
        + '    ("isomp4", ("m4a", "m4b", "mp4"), ("audio/mp4", "audio/x-m4a")),\n'
        + '    ("matroska", ("mka", "mkv"), ("audio/x-matroska",)),\n'
        + '    (\n'
        + '        "libav",\n'
        + '        ("mp3", "aac", "wma", "ac3"),\n'
        + '        ("audio/mpeg", "audio/aac", "audio/x-ms-wma", "audio/ac3"),\n'
        + "    ),\n"
        + "]\n\n\n"
    )
    assert s.count(import_anchor) == 1
    s = s.replace(import_anchor, table, 1)

    old_return = "    return  # TODO\n"
    assert s.count(old_return) == 1, f"old_return count={s.count(old_return)}"
    new_return = (
        "    result = []\n"
        "    for plugin, suffixes, mime_types in DECODER_PLUGINS:\n"
        '        result.append(("plugin", plugin))\n'
        "        for suffix in suffixes:\n"
        '            result.append(("suffix", suffix))\n'
        "        for mime_type in mime_types:\n"
        '            result.append(("mime_type", mime_type))\n'
        "    return result\n"
    )
    s = s.replace(old_return, new_return, 1)
    open(p, "w").write(s)
    print("patched reflection.py: decoders に静的なプラグイン一覧を実装")
