# mpdoutputpartition-patch.py が実装した audio_output.py の `outputs()` は、現在の
# セッションのパーティションが仮想出力「Mute」の所属パーティション
# (translator.output_partition_get("Mute")) と一致しない場合、default/非defaultを
# 区別せず常に plugin: "dummy" の偽の1行 (outputid 0 / outputname Mute /
# outputenabled 0) を返す。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (rmpc本体 mierak/rmpc および実MPD本体 MusicPlayerDaemon/MPD を実際にcloneして調査した
# 上で) 新規発見した項目。
#
# 実MPD仕様 (src/output/Print.cxx の printAudioDevices()) を実際に確認したところ:
#   for (...) { if (!outputs.Owns(ao)) continue; r.Fmt("outputid: ...", ...); }
# という実装で、"dummy" というプレースホルダ機構自体が実MPDに一切存在しない
# (src/output/plugins/ 配下の全出力プラグイン名を確認したが "dummy" は無く、
# "null" という別プラグインがあるのみ)。実MPDは default を含めどのパーティション
# からの `outputs` であっても、そのパーティションが所有していない出力は単に列挙から
# 除外する (該当出力ゼロなら空の OK のみ)。この除外はパーティション作成時の
# `MultipleOutputs::AcquireAll()`(未所有の出力を先着 = 通常はdefaultが総取り)と
# `moveoutput` による明示的な所有権移動でのみ変わる。
#
# rmpc本体 (rmpc/src/shared/mpd_client_ext.rs の list_partitioned_outputs()) を
# 実際に読むと、非default パーティションからの呼び出しでは
# 「defaultへ一時切替→outputsを取得(全出力の実名/実plugin)→元のパーティションへ戻し
# 再度outputsを取得→前者のうち後者にplugin!="dummy"で同名一致するものだけを
# CurrentPartition、それ以外はOtherPartition」という2段階の突き合わせを行っており、
# 非default側の応答で当該出力が単に「含まれない」ことを正しく扱える設計になっている
# (含まれていなければ自動的にOtherPartition側に落ちる)。つまり「dummyという偽の1行」
# は実MPD互換の観点でもrmpcの非default分岐の実装の観点でも必要とされておらず、
# mpdoutputpartition-patch.py の非default時のこの偽1行は実MPDの応答形状から逸脱した
# 過剰実装だったと判明した (rmpc/rmpc-mpd/src/config/cli.rs 経由の `rmpc --partition
# NAME outputs` サブコマンドはこの2段階突き合わせを経由せず生の `outputs` 応答を
# そのままJSON化するため、非default・非所有パーティションから直接 `outputs` を叩くと
# 実在しない出力の偽情報が混入したJSONを返してしまう実害がある)。
#
# 一方 default パーティションが不所有の場合に dummy 行を返す既存の分岐は、rmpc の
# default分岐(`outputs()`の応答内でplugin=="dummy"の行をOtherPartition扱いする
# ヒューリスティック)向けに意図的に追加されたものであり、既にBACKLOG.md/実機検証で
# 動作確認済みのため本項目では変更しない。本項目は非default時の偽1行だけを実MPD準拠の
# 空リストへ修正する。
#
# 検証: `newpartition work` → `partition work` (Mute はまだdefault所属、workは何も
# 所有していない) → `outputs` を実際に送り、修正前は偽の `outputid: 0` 行が返る
# (実MPD仕様なら空のOKのみ) ことをdev mopidyで実機確認する。

p = "mopidy_mpd/protocol/audio_output.py"
s = open(p).read()

old_outputs_not_owned = (
    "    if not _mpdoutputpartition_owned(context):\n"
    "        return [\n"
    '            ("outputid", 0),\n'
    '            ("outputname", "Mute"),\n'
    '            ("plugin", "dummy"),\n'
    '            ("outputenabled", 0),\n'
    "        ]\n"
    "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
)
new_outputs_not_owned = (
    "    if not _mpdoutputpartition_owned(context):\n"
    "        if translator.partition_get(id(context.session)) == translator.partition_list()[0]:\n"
    "            return [\n"
    '                ("outputid", 0),\n'
    '                ("outputname", "Mute"),\n'
    '                ("plugin", "dummy"),\n'
    '                ("outputenabled", 0),\n'
    "            ]\n"
    "        return []\n"
    "    muted = 1 if context.core.mixer.get_mute().get() else 0\n"
)

if "== translator.partition_list()[0]" in s:
    print("audio_output.py already patched for non-default empty outputs, skip")
else:
    assert s.count(old_outputs_not_owned) == 1, (
        f"old_outputs_not_owned count={s.count(old_outputs_not_owned)}"
    )
    s = s.replace(old_outputs_not_owned, new_outputs_not_owned, 1)
    open(p, "w").write(s)
    print(
        "patched audio_output.py: outputs() の非defaultパーティション不所有時を"
        " 偽のdummy行から実MPD準拠の空リストへ修正"
    )
