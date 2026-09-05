"""模块（插件）管理器。

模块放在 QQBotData/modules/ 下。每个模块 = 一个 .py 文件，可选配套同名 .html
作为它在面板中的配置界面。约定：

    MODULE_INFO = {"name": "显示名", "description": "描述", "version": "0.1"}
    def register(app):                 # 可选，加载时调用一次
    async def on_event(bot, event):    # 可选，收到 OneBot 事件
    def on_config(app, config):        # 可选，面板保存该模块配置时调用

模块数据存储在 QQBotData/data/<模块名>.json（面板自动读写），不会回写模块文件。

同名 .html 即模块配置界面，服务在 /api/modules/<模块文件名>/ui；
界面 JS 可用 ?token= 会话令牌调用 /api/modules/<名>/config 读写自身数据。

modules 文件夹有任何变动（新增/删除 .py）都会被自动检测并热重载。
"""
import asyncio
import importlib.util
import logging
import os
import sys

from framework.paths import MODULES_DIR

log = logging.getLogger("modules")

EXAMPLE_PY = '''"""示例模块：欢迎与 /ping。演示 MODULE_INFO 元数据 + 配套配置界面。"""

MODULE_INFO = {"name": "欢迎助手", "description": "私聊回复你好；/ping 测活", "version": "0.1"}


def on_config(app, config):
    print("[欢迎助手] 配置已更新:", config)


async def on_event(bot, event):
    if event.get("post_type") != "message":
        return
    raw = str(event.get("raw_message", "")).strip()
    cfg = app.get_module_config("example_welcome")
    welcome = cfg.get("welcome_text") or "你好，我是基于原版 QQ 运行的机器人~"

    if raw == "/ping":
        text = "pong! 核心运行正常，模块已加载"
        if event.get("message_type") == "group":
            await bot.send_group_msg(event["group_id"], text)
        else:
            await bot.send_private_msg(event["user_id"], text)
    elif event.get("message_type") == "private" and raw == "你好":
        await bot.send_private_msg(event["user_id"], welcome)
'''

EXAMPLE_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: "Microsoft YaHei", sans-serif; color: #e6edf3;
         background: transparent; padding: 6px 2px; }
  label { display: block; font-size: 13px; color: #8b98a5; margin: 10px 0 6px; }
  input, textarea { width: 100%; max-width: 480px; background: #212a33; color: #e6edf3;
    border: 1px solid #2c3742; border-radius: 8px; padding: 9px 12px; font-size: 13px;
    outline: none; box-sizing: border-box; }
  input:focus, textarea:focus { border-color: #4c8dff; }
  button { background: #4c8dff; color: #fff; border: 0; border-radius: 8px;
    padding: 9px 20px; font-size: 13px; cursor: pointer; margin-top: 14px; }
  #tip { margin-top: 10px; font-size: 12px; color: #2ea86b; min-height: 16px; }
</style>
</head>
<body>
  <h3 style="margin:4px 0 2px;font-size:15px">欢迎助手 — 配置</h3>
  <p style="font-size:12px;color:#8b98a5;margin:0 0 4px">数据保存在 QQBotData/data/，不会修改模块文件</p>
  <label>私聊"你好"时的回复内容</label>
  <input id="welcomeText" placeholder="你好，我是基于原版 QQ 运行的机器人~">
  <button onclick="save()">保存</button>
  <div id="tip"></div>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
const base = "/api/modules/example_welcome/config";
const H = {"Content-Type": "application/json", "X-Access-Token": token};

async function load(){
  try {
    const r = await fetch(base, {headers: H});
    const cfg = await r.json();
    if (cfg.welcome_text) document.getElementById("welcomeText").value = cfg.welcome_text;
  } catch(e) { tip("加载失败: " + e.message, true); }
}
async function save(){
  const welcome_text = document.getElementById("welcomeText").value;
  try {
    const r = await fetch(base, {method: "POST", headers: H,
      body: JSON.stringify({config: {welcome_text}})});
    const d = await r.json();
    tip(d.ok ? "已保存 ✓" : "保存失败: " + d.error, !d.ok);
  } catch(e) { tip("保存失败: " + e.message, true); }
}
function tip(msg, err){ const t = document.getElementById("tip");
  t.textContent = msg; t.style.color = err ? "#e5534b" : "#2ea86b"; }
load();
</script>
</body>
</html>
'''


class ModuleManager:
    def __init__(self, app):
        self.app = app
        self.modules: dict[str, object] = {}   # 模块文件名 -> 模块对象
        self.meta: dict[str, dict] = {}        # 模块文件名 -> MODULE_INFO
        self._ensure_example()

    def _ensure_example(self):
        os.makedirs(MODULES_DIR, exist_ok=True)
        py = os.path.join(MODULES_DIR, "example_welcome.py")
        if not os.path.exists(py):
            with open(py, "w", encoding="utf-8") as f:
                f.write(EXAMPLE_PY)
        html = os.path.join(MODULES_DIR, "example_welcome.html")
        if not os.path.exists(html):
            with open(html, "w", encoding="utf-8") as f:
                f.write(EXAMPLE_HTML)

    def load_all(self):
        if MODULES_DIR not in sys.path:
            sys.path.insert(0, MODULES_DIR)
        for fname in sorted(os.listdir(MODULES_DIR)):
            if fname.endswith(".py") and not fname.startswith("_"):
                self._load(fname[:-3])

    def reload_all(self) -> list[str]:
        """卸载全部已加载模块后重新扫描 modules/ 目录。"""
        for name in list(self.modules):
            sys.modules.pop(f"qqbot_module_{name}", None)
        self.modules.clear()
        self.meta.clear()
        self.load_all()
        log.info("模块已重载，共 %d 个: %s", len(self.modules), list(self.modules))
        return list(self.modules)

    def list_modules(self) -> list[dict]:
        out = []
        for name, module in self.modules.items():
            info = self.meta.get(name, {})
            out.append({
                "file": name,
                "name": info.get("name", name),
                "description": info.get("description", ""),
                "version": info.get("version", ""),
                "has_ui": os.path.exists(os.path.join(MODULES_DIR, name + ".html")),
            })
        return sorted(out, key=lambda m: m["file"])

    def _load(self, name: str):
        path = os.path.join(MODULES_DIR, name + ".py")
        try:
            spec = importlib.util.spec_from_file_location(f"qqbot_module_{name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                module.register(self.app)
            self.modules[name] = module
            self.meta[name] = getattr(module, "MODULE_INFO", {}) or {}
            desc = self.meta[name].get("description", "")
            log.info("模块已加载: %s %s", name, f"({desc})" if desc else "")
        except Exception:
            log.exception("模块加载失败: %s", path)

    def dispatch(self, event: dict):
        bot = self.app.bot
        for name, module in self.modules.items():
            handler = getattr(module, "on_event", None)
            if not handler:
                continue
            try:
                result = handler(bot, event)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(self._safe(name, result))
            except Exception:
                log.exception("模块 %s 事件处理出错", name)

    async def _safe(self, name: str, coro):
        try:
            await coro
        except Exception:
            log.exception("模块 %s 异步处理出错", name)
