# mopidy-rmpc-patches

[Mopidy](https://mopidy.com/) をビルド時に強化するパッチ集。nixpkgs 素の
`mopidy-mpd` / `mopidy-ytmusic` / `mopidy-listenbrainz` が現行の YouTube Music /
[rmpc](https://github.com/mierak/rmpc) / MPD プロトコルに対して持つ不足・不具合を、
各拡張の `postPatch` で当てる Python パッチスクリプト (`*-patch.py`) として提供する。

- **mpd\*** — mopidy_mpd の MPD プロトコル互換 (フィルタ式 / sticker / partition /
  playlist / range / tagtypes など、実 MPD 挙動に寄せる多数の修正)
- **yt\*** — mopidy_ytmusic の検索 / アルバム / アップロード / OAuth ガード
- **lb\*** — mopidy_listenbrainz のネットワーク / JSON / プレイリスト堅牢化

各パッチは対象ソースを `open().read()` → 冪等マーカー確認 →
`assert count==1` で守った文字列置換 → 書き戻し、という手口で、適用順は消費側
(`mopidy-env.nix` の patch リスト) が決める。

## 利用 (Nix flake input)

```nix
inputs.mopidy-patches = {
  url = "github:gapul/mopidy-rmpc-patches";
  flake = false;
};
```

消費側で `patchDir = mopidy-patches;` として各拡張の `postPatch` に
`${py.interpreter} ${patchDir}/<name>-patch.py` を順に並べる
(例は [gapul/dotfiles](https://github.com/gapul/dotfiles) の `nix/lib/mopidy-env.nix`)。
