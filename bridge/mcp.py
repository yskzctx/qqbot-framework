# -*- coding: utf-8 -*-
"""云电脑 MCP 调用辅助：python mcp.py <tool> [json参数]"""
import json
import sys
import urllib.request

URL = "https://fairfield-competent-description-talks.trycloudflare.com/mcp"
TOKEN = "kxj110625"
_id = [100]


def call(method, params, timeout=120):
    _id[0] += 1
    req = urllib.request.Request(URL, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params}).encode()
    try:
        with urllib.request.urlopen(req, body, timeout=timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "body": e.read().decode()[:300]}
    d = json.loads(raw.split("data: ")[-1]) if "data: " in raw else json.loads(raw)
    return d.get("result", d)


def tool(name, args=None, timeout=120):
    r = call("tools/call", {"name": name, "arguments": args or {}}, timeout)
    if "_http_error" in r:
        return f"[HTTP {r['_http_error']}] {r['body']}"
    content = r.get("content", [])
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text") or "(无文本输出)"


if __name__ == "__main__":
    t = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(tool(t, args))
