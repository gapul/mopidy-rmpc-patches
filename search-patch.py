# mopidy-ytmusic 0.3.9 の parseSearch は filter=None(any検索) で返る多様な結果に脆く、
# 1件でも想定外(album=None / browseId欠落 / エラーハンドラ自身のKeyError 等)があると
# 例外が parseSearch 全体を突き抜けて検索結果が丸ごと 0 件になる。rmpc の any 検索が全滅する。
# 対策:
#  (1) 既知の None を安全化 (album=None / duration=None) して正当な曲を取りこぼさない
#  (2) ループ本体を try/except で包み、壊れた結果は1件だけスキップして全体を守る
p = "mopidy_ytmusic/library.py"
s = open(p).read()

# (1) 既知フィールドの None 安全化
for old, new in [
    ('if "album" in result:', 'if result.get("album"):'),
    (
        'length = [int(i) for i in result["duration"].split(":")]',
        'length = [int(i) for i in (result.get("duration") or "0:00").split(":")]',
    ),
]:
    assert s.count(old) == 1, f"expected 1 occurrence of: {old!r} (got {s.count(old)})"
    s = s.replace(old, new)

# (2) `for result in results:` の本体を try/except でラップ
MARK = "skipping unparseable search result"
if MARK not in s:
    FOR = "        for result in results:"
    lines = s.split("\n")
    out = []
    i = 0
    done = False
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if not done and line == FOR:
            done = True
            body = []
            while i < len(lines):
                l = lines[i]
                if l.strip() == "":
                    body.append(l)
                    i += 1
                    continue
                indent = len(l) - len(l.lstrip(" "))
                if indent >= 12:
                    body.append(l)
                    i += 1
                else:
                    break
            out.append("            try:")
            for bl in body:
                out.append(("    " + bl) if bl.strip() else bl)
            out.append("            except Exception:")
            out.append(
                '                logger.warning('
                '"YTMusic: ' + MARK + ' (%r)", '
                'result.get("resultType") if isinstance(result, dict) else result)'
            )
            out.append("                continue")
    assert done, "for-loop anchor not found"
    s = "\n".join(out)

open(p, "w").write(s)
print("patched library.py: parseSearch を堅牢化 (None安全化 + ループ本体try/except)")
