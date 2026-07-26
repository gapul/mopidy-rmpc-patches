# mopidy-mpd 3.3.0 の `outputs` は outputid/outputname/outputenabled の3フィールドしか
# 返さない。musicpd.org protocol (audio output devices 節、WebFetch で実際に確認済み) は
# `plugin` フィールドを常時必須で返す仕様 (例: outputid/outputname/plugin/outputenabled/
# attribute の順)。TODO 全項目消化済みのため自走エージェントが調査して新規発見・追加した
# 項目: 実際に rmpc 本体 (mierak/rmpc) を clone してソース確認したところ、
# rmpc-mpd/src/commands/outputs.rs の `Output` 構造体が `plugin: String` を専用フィールドとして
# パースし、rmpc/src/ui/modals/outputs.rs のアウトプット一覧モーダルが実際に "Plugin" 列として
# 描画している (Cell::new(output.plugin.as_str()))。plugin キー自体が応答に無いと
# FromMpd 側は単に未知キーとして無視するだけでクラッシュはしないが、常に空欄の列になり
# 実 MPD 互換の情報が欠落する実害を確認した。
#
# 実装: mopidy core (mixer.py) は GStreamer レベルの出力プラグイン概念を持たず、
# audio_output.py が返す "Mute" は実出力ではなく core.mixer の mute 状態を模した仮想出力
# (outputname も "Mute" 固定のハードコード) のため、plugin も同様に固定文字列
# "mopidy" を返す (crossfade/mount 等と同じく「プロトコル層の応答を仕様に合わせるだけで
# 実体を持たない」既知の限界)。
p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

MARKER = '("plugin", "mopidy")'
if MARKER in s:
    print("outputs plugin field already added, skip")
else:
    old_block = (
        "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
        "    return [\n"
        '        ("outputid", 0),\n'
        '        ("outputname", "Mute"),\n'
        '        ("outputenabled", muted),\n'
        "    ]\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
        "    return [\n"
        '        ("outputid", 0),\n'
        '        ("outputname", "Mute"),\n'
        '        ("plugin", "mopidy"),\n'
        '        ("outputenabled", muted),\n'
        "    ]\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print("patched audio_output.py: outputs に plugin フィールドを追加")
