# mpdsticker-patch.py が `sticker` コマンドを実装した際、元のスタブ実装
# (`raise exceptions.MpdNotImplemented`) に付いていた
# `@protocol.commands.add("sticker", list_command=False)` の `list_command=False` を
# 引き継いだまま残してしまっていた。`list_command` は reflection.py の `commands` 応答
# (rmpc-mpd 含む多くのクライアントが「このコマンドをサーバがサポートしているか」の
# 判定に使う) に載せるかどうかのフラグで、`False` だと当該コマンドが実装済みでも
# `commands` の一覧に一切出てこない。
# 実 MPD (musicpd.org protocol, sticker section) は sticker データベースが有効な限り
# `commands` に `sticker` を含める。TODO/既知の軽微な残課題を全項目消化済みのため
# 自走エージェントが実際に dev mopidy へ `commands` を送って確認したところ、
# 本実装は `sticker get/set/delete/list/find` を全て実装済み (mpdsticker-patch.py
# 以下一連のパッチ) にもかかわらず `commands` 応答に `sticker` が一切含まれないことを
# 発見した。rmpc (rmpc/src/ctx.rs Ctx::try_new) はまさにこの `commands` 応答の
# `sticker` の有無だけで `StickersSupport::Supported`/`Unsupported` を判定し、
# `Unsupported` だと以後一切 sticker コマンドを送らない (曲への評価 = レーティング
# 機能が常に無効化される) ため、この一致漏れは実装済み機能が rmpc 側から永久に
# 使われないという実害がある。
# 対策: `list_command=False` を外し (デフォルトの `True` に戻し)、`commands` に
# 実装状態通りに `sticker` を含める。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

old_anchor = '@protocol.commands.add("sticker", list_command=False)\ndef sticker(context, *args):\n'
new_anchor = '@protocol.commands.add("sticker")\ndef sticker(context, *args):\n'

if new_anchor in s:
    print("sticker already listed in reflection, skip")
else:
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"
    s = s.replace(old_anchor, new_anchor, 1)
    open(p, "w").write(s)
    print("patched stickers.py: sticker を commands の reflection 一覧に含めるよう修正")
