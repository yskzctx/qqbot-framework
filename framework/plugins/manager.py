"""模块（插件）管理器 —— 万物皆可插件。

模块 = QQBotData/modules/ 下一个 .py 文件（可带同名 .html 作为配置界面）。

支持的全部写法（均可选，可混用）：
    MODULE_INFO = {"name": "显示名", "description": "描述", "version": "0.1"}
    PRIORITY = 100                       # 事件处理顺序，越小越先

    def register(app): ...               # 加载时
    def on_config(app, config): ...      # 面板保存该模块配置时
    def on_unload(app): ...              # 卸载/重载前（清理线程、连接等）
    async def on_event(bot, event): ...  # 传统事件处理；返回 False 拦截后续模块

    from framework.plugins import cmd, api, event
    @cmd("签到")  async def f(bot, ev, args)   # 聊天命令，args=剩余参数
    @cmd("危险", admin=True)                    # 仅管理员
    @event(priority=10)  async def f(bot, ev)  # 事件订阅，返回 False 拦截
    @api("GET", "/x")    async def f(bot, req) # 自有 API: /api/m/<文件名>/x

数据存 QQBotData/data/<文件名>.json（bot.app.get/set_module_config）。
modules 文件夹内容或修改时间变化都会自动热重载。
"""
import asyncio
import importlib.util
import logging
import os
import sys

from framework.paths import MODULES_DIR

log = logging.getLogger("modules")

EXAMPLE_PY = '''"""示例模块：演示命令 / 事件 / API / 配置界面（example_welcome.html）。"""
from framework.plugins import cmd, api

MODULE_INFO = {"name": "欢迎助手", "description": "示例：命令+事件+API", "version": "0.2"}


@cmd("你好")
async def hello(bot, event, args):
    cfg = bot.app.get_module_config("example_welcome")
    await bot.send_private_msg(event["user_id"], cfg.get("welcome_text", "你好~"))


async def on_event(bot, event):
    if event.get("raw_message") == "/ping":
        await bot.send_private_msg(event["user_id"], "pong! 模块正常")
'''

EXAMPLE_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8">
<style>
  body { font-family: "Microsoft YaHei", sans-serif; color: #e6edf3; padding: 6px 2px; }
  input { width: 90%; max-width: 420px; background: #212a33; color: #e6edf3;
    border: 1px solid #2c3742; border-radius: 8px; padding: 9px 12px; font-size: 13px; }
  button { background: #4c8dff; color: #fff; border: 0; border-radius: 8px;
    padding: 8px 18px; cursor: pointer; margin-top: 12px; }
  #tip { margin-top: 10px; font-size: 12px; color: #2ea86b; }
</style></head>
<body>
  <h3 style="font-size:15px">欢迎助手 — 配置</h3>
  <label style="display:block;font-size:12px;color:#8b98a5;margin:10px 0 6px">私聊"你好"的回复内容</label>
  <input id="welcome_text" placeholder="你好，我是基于原版 QQ 运行的机器人~">
  <br><button onclick="save()">保存</button>
  <div id="tip"></div>
<script>
const H = {"Content-Type": "application/json",
           "X-Access-Token": new URLSearchParams(location.search).get("token") || ""};
const base = "/api/modules/example_welcome/config";
load();
async function load(){
  try { const c = await (await fetch(base, {headers:H})).json();
        if (c.welcome_text) document.getElementById("welcome_text").value = c.welcome_text;
  } catch(e){ document.getElementById("tip").textContent = "加载失败"; }
}
async function save(){
  const welcome_text = document.getElementById("welcome_text").value;
  const r = await fetch(base, {method:"POST", headers:H, body: JSON.stringify({config:{welcome_text}})});
  document.getElementById("tip").textContent = (await r.json()).ok ? "已保存 ✓" : "保存失败";
}
</script></body></html>
'''


class _Sub:
    """事件订阅者。"""
    __slots__ = ("priority", "post_type", "func", "module")

    def __init__(self, priority, post_type, func, module):
        self.priority = priority
        self.post_type = post_type
        self.func = func
        self.module = module


class ModuleManager:
    def __init__(self, app):
        self.app = app
        self.modules: dict[str, object] = {}
        self.meta: dict[str, dict] = {}
        self._cmds: dict[str, tuple[str, object, bool]] = {}       # name -> (module, func, admin)
        self._apis: dict[tuple[str, str, str], tuple[object, bool]] = {}  # (module, method, path) -> (func, admin)
        self._subs: list[_Sub] = []
        self._example()

    # ---------- 加载 / 卸载 ----------

    def _example(self):
        os.makedirs(MODULES_DIR, exist_ok=True)
        py = os.path.join(MODULES_DIR, "example_welcome.py")
        if not os.path.exists(py):
            open(py, "w", encoding="utf-8").write(EXAMPLE_PY)
        html = os.path.join(MODULES_DIR, "example_welcome.html")
        if not os.path.exists(html):
            open(html, "w", encoding="utf-8").write(EXAMPLE_HTML)

    def load_all(self):
        if MODULES_DIR not in sys.path:
            sys.path.insert(0, MODULES_DIR)
        for fname in sorted(os.listdir(MODULES_DIR)):
            if fname.endswith(".py") and not fname.startswith("_"):
                self._load(fname[:-3])
        self._subs.sort(key=lambda s: s.priority)

    def reload_all(self) -> list[str]:
        for name, module in self.modules.items():
            hook = getattr(module, "on_unload", None)
            if hook:
                try:
                    hook(self.app)
                except Exception:
                    log.exception("模块 %s on_unload 出错", name)
            sys.modules.pop(f"qqbot_module_{name}", None)
        self.modules.clear()
        self.meta.clear()
        self._cmds.clear()
        self._apis.clear()
        self._subs.clear()
        self.load_all()
        log.info("模块已重载，共 %d 个: %s", len(self.modules), list(self.modules))
        return list(self.modules)

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
            priority = getattr(module, "PRIORITY", 100)

            # 扫描装饰器标记
            for obj in vars(module).values():
                mark = getattr(obj, "_qqbot_cmd", None)
                if mark:
                    self._cmds[mark[0]] = (name, obj, mark[1])
                mark = getattr(obj, "_qqbot_api", None)
                if mark:
                    self._apis[(name, mark[0], mark[1])] = (obj, False)
                mark = getattr(obj, "_qqbot_event", None)
                if mark:
                    self._subs.append(_Sub(mark[1], mark[0], obj, name))

            # 传统 on_event 作为默认优先级的事件订阅者
            handler = getattr(module, "on_event", None)
            if handler and not getattr(module, "PRIORITY_HANDLED", False):
                self._subs.append(_Sub(priority, None, handler, name))
            log.info("模块已加载: %s%s", name,
                     f"（{self.meta[name].get('description', '')}）"
                     if self.meta[name].get("description") else "")
        except Exception:
            log.exception("模块加载失败: %s", path)

    # ---------- 查询 ----------

    def list_modules(self) -> list[dict]:
        out = []
        for name, module in self.modules.items():
            info = self.meta.get(name, {})
            cmds = [n for n, (m, _, _) in self._cmds.items() if m == name]
            apis = [f"{m} {p}" for (mn, m, p) in self._apis if mn == name]
            out.append({
                "file": name,
                "name": info.get("name", name),
                "description": info.get("description", ""),
                "version": info.get("version", ""),
                "has_ui": os.path.exists(os.path.join(MODULES_DIR, name + ".html")),
                "commands": sorted(cmds),
                "apis": sorted(apis),
            })
        return sorted(out, key=lambda m: m["file"])

    def match_command(self, raw: str):
        """消息匹配命令 -> (func, args, admin)；无匹配返回 None。"""
        for name in sorted(self._cmds, key=len, reverse=True):
            if raw == name or raw.startswith(name + " "):
                module, func, admin = self._cmds[name]
                return func, raw[len(name):].split(), admin, name
        return None

    def resolve_api(self, module: str, method: str, path: str):
        return self._apis.get((module, method.upper(), path))

    # ---------- 事件分发（串行管道，支持拦截） ----------

    def dispatch(self, event: dict):
        asyncio.ensure_future(self._dispatch(event))

    async def _dispatch(self, event: dict):
        bot = self.app.bot
        # 命令优先：命中即独占处理
        if event.get("post_type") == "message":
            raw = str(event.get("raw_message", "")).strip()
            hit = self.match_command(raw)
            if hit:
                func, args, admin, name = hit
                try:
                    if admin and not self.app.is_admin(event.get("user_id")):
                        text = "该命令仅管理员可用"
                        if event.get("message_type") == "group":
                            await bot.send_group_msg(event["group_id"], text)
                        else:
                            await bot.send_private_msg(event["user_id"], text)
                    else:
                        await func(bot, event, args)
                except Exception:
                    log.exception("命令 %s 处理出错", name)
                return

        # 事件订阅者：按优先级串行执行，返回 False 拦截后续
        for sub in self._subs:
            if sub.post_type and event.get("post_type") != sub.post_type:
                continue
            try:
                result = sub.func(bot, event)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is False:
                    return
            except Exception:
                log.exception("模块 %s 事件处理出错", sub.module)
