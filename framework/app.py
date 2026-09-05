"""App：整合所有模块，是框架的核心对象。"""
import asyncio
import json
import logging
import os
import time
import webbrowser
from collections import deque

import framework
from framework.ai import AIService
from framework.bot import BotAPI
from framework.onebot import OneBotServer
from framework.paths import DATA_STORE_DIR, MODULES_DIR, app_root
from framework.plugins import ModuleManager
from framework.process import QQProcessMonitor
from framework.web import WebServer

log = logging.getLogger("framework.app")


class App:
    VERSION = framework.__version__

    def __init__(self, config):
        self.config = config
        self.start_time = time.time()
        self.qq_info = None                 # QQ 进程快照（由 QQProcessMonitor 更新）
        self.recent_events = deque(maxlen=300)
        self.bot = None                     # 模块用的 API 封装
        self.ai = AIService(self)
        self.onebot = OneBotServer(self)
        self.web = WebServer(self)
        self.plugins = ModuleManager(self)
        self.monitor = QQProcessMonitor(self)
        self._shutdown: asyncio.Event | None = None
        self._inject_attempted = False
        self._bg_tasks: list[asyncio.Task] = []

    # ---------- 生命周期 ----------

    async def run(self):
        self._shutdown = asyncio.Event()
        self.bot = BotAPI(self)

        await self.web.start()              # 面板 + OneBot API 同端口
        self.plugins.load_all()

        self._bg_tasks.append(asyncio.create_task(self.monitor.loop()))
        self._bg_tasks.append(asyncio.create_task(self._modules_watcher()))
        if self.config["inject"].get("enabled"):
            self._bg_tasks.append(asyncio.create_task(self._inject_loop()))

        if self.config["web"].get("auto_open_browser", True):
            webbrowser.open(f"http://127.0.0.1:{self.config['server']['port']}/")

        log.info("核心 v%s 已启动（模块目录: %s）", self.VERSION, MODULES_DIR)
        await self._shutdown.wait()

        log.info("正在停止各模块...")
        for task in self._bg_tasks:
            task.cancel()
        await self.onebot.stop()
        await self.web.stop()
        log.info("框架已完全退出")

    def request_shutdown(self):
        """线程安全：托盘/Web 都通过它触发退出。"""
        if self._shutdown and not self._shutdown.is_set():
            self._shutdown.set()

    # ---------- 权限 ----------

    def is_admin(self, user_id) -> bool:
        """判断是否为管理员（config -> permissions.admins）。"""
        admins = self.config.get("permissions", {}).get("admins", [])
        return str(user_id) in [str(a).strip() for a in admins if str(a).strip()]

    # ---------- 事件流 ----------

    def push_event(self, event: dict):
        self.recent_events.append(event)
        if event.get("post_type") == "message":
            log.info("收到消息 [%s] %s: %s",
                     event.get("message_type", "?"),
                     event.get("sender", {}).get("nickname", event.get("user_id", "?")),
                     str(event.get("raw_message", ""))[:100])
        # 实时推送到 Web 面板
        payload = json.dumps({"type": "event", "data": event}, ensure_ascii=False)
        for ws in list(self.web.subscribers):
            asyncio.ensure_future(self._ws_send(ws, payload))

    async def _ws_send(self, ws, payload: str):
        try:
            await ws.send_str(payload)
        except Exception:
            self.web.subscribers.discard(ws)

    # ---------- 模块数据存取（存 QQBotData/data/，不回写模块文件） ----------

    def _module_data_path(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in "_-")
        return os.path.join(DATA_STORE_DIR, f"{safe}.json")

    def get_module_config(self, name: str) -> dict:
        path = self._module_data_path(name)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.exception("读取模块数据失败: %s", name)
            return {}

    def set_module_config(self, name: str, cfg: dict):
        path = self._module_data_path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log.info("模块数据已保存: %s", name)
        # 通知模块配置变更
        module = self.plugins.modules.get(name)
        if module and hasattr(module, "on_config"):
            try:
                module.on_config(self, cfg)
            except Exception:
                log.exception("模块 %s on_config 出错", name)

    # ---------- 模块文件夹监视（放入/删除模块自动重载） ----------

    def _module_files(self) -> set:
        try:
            return {f for f in os.listdir(MODULES_DIR) if f.endswith(".py")}
        except FileNotFoundError:
            return set()

    async def _modules_watcher(self):
        known = self._module_files()
        while True:
            await asyncio.sleep(3)
            try:
                current = self._module_files()
                if current != known:
                    added = current - known
                    removed = known - current
                    log.info("检测到模块文件变动（新增: %s，移除: %s），自动重载",
                             sorted(added), sorted(removed))
                    known = current
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.plugins.reload_all)
            except Exception:
                log.exception("模块监视出错")

    # ---------- QQ 进程事件 / 注入 ----------

    async def on_qq_found(self, info: dict):
        if self.config["inject"].get("enabled") and not self._inject_attempted:
            self._inject_attempted = True
            await self._do_inject(info["pid"])

    async def on_qq_lost(self, info: dict):
        self._inject_attempted = False

    async def _inject_loop(self):
        """注入配置开启但启动时 QQ 已在运行的情况下，首次扫描后立即注入。"""
        await asyncio.sleep(1)
        if not self._inject_attempted and self.qq_info:
            self._inject_attempted = True
            await self._do_inject(self.qq_info["pid"])

    async def _do_inject(self, pid: int):
        from framework.injector import inject_dll
        dll = self.config["inject"].get("dll_path", "")
        if not dll:
            log.warning("已开启注入但未配置 inject.dll_path，跳过")
            return
        if not os.path.isabs(dll):
            dll = os.path.join(app_root(), dll)
        if not os.path.exists(dll):
            log.warning("注入 DLL 不存在: %s，跳过（请把你的 hook DLL 放到该路径）", dll)
            return
        try:
            await asyncio.get_running_loop().run_in_executor(None, inject_dll, pid, dll)
        except Exception as e:
            log.error("注入失败: %s", e)
