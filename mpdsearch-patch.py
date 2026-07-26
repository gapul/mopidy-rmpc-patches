# mopidy-mpd 3.3.0 は旧来の `search TYPE VALUE` 構文しか解さず、rmpc 等が送る
# 新しい MPD フィルタ式 `search "(Artist contains \"x\")"` を "incorrect arguments" で弾く。
# フィルタ式を解釈して mopidy クエリへ変換する処理を _query_from_mpd_search_parameters に足す。
# (mopidy クエリは AND 結合の field->[values] のみ表現可。否定/OR は best-effort でスキップ)
p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

if "_query_from_mpd_filter_expression" not in s:
    # ヘルパは raw triple-single string で逐語コピー (二重エスケープ回避)
    helper = r'''

def _query_from_mpd_filter_expression(expr, mapping):
    query = {}
    idx = 0
    L = len(expr)
    while idx < L:
        qpos = -1
        for qi in range(idx, L):
            if expr[qi] in "'\"":
                qpos = qi
                break
        if qpos < 0:
            break
        op_open = expr.rfind("(", idx, qpos)
        if op_open < 0:
            idx = qpos + 1
            continue
        head = expr[op_open + 1:qpos]
        quote = expr[qpos]
        j = qpos + 1
        buf = []
        while j < L:
            c = expr[j]
            if c == "\\" and j + 1 < L:
                buf.append(expr[j + 1])
                j += 2
                continue
            if c == quote:
                break
            buf.append(c)
            j += 1
        value = "".join(buf)
        idx = j + 1
        parts = head.split()
        if len(parts) >= 2:
            tag = parts[0].strip("\"'").lstrip("(")
            op = parts[-1]
            if op in ("!=", "!~"):
                continue
            field = mapping.get(tag.lower())
            if field and value.strip():
                query.setdefault(field, []).append(value)
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")
    return query
'''
    s += helper

    anchor = (
        "def _query_from_mpd_search_parameters(parameters, mapping):\n"
        "    query = {}\n"
        "    parameters = list(parameters)\n"
    )
    inject = (
        "def _query_from_mpd_search_parameters(parameters, mapping):\n"
        "    parameters = list(parameters)\n"
        "    if parameters and isinstance(parameters[0], str) and parameters[0][:1] == \"(\":\n"
        "        return _query_from_mpd_filter_expression(parameters[0], mapping)\n"
        "    query = {}\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    s = s.replace(anchor, inject, 1)
    open(p, "w").write(s)
    print("patched music_db.py: MPD filter式構文をサポート")
else:
    print("filter support already present, skip")
