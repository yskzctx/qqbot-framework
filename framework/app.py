"""QQ 机器人框架核心。

职责（也仅有这些）：
1. 管理 NapCat 注入与 QQ 本体的启动
2. 运行 OneBot 11 服务端：QQ 事件 → 模块，模块动作 → QQ（纯透传）
3. 提供面板（AI 配置 / 联系人分组 / 消息数据库 / 模块管理）
4. 消息入库与自动清理

铁律：事件循环内不允许任何阻塞操作（sqlite/文件/子进程/网络一律进线程池）。
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime

import framework
from framework.ai import AIService
from framework.bot import BotAPI
from framework.msgdb import MessageDB
from framework.napcat import NapCatManager
from framework.onebot import OneBotServer
from framework.paths import DATA_DIR, DATA_STORE_DIR, MODULES_DIR
from framework.plugins import ModuleManager
from framework.process import QQProcessMonitor
from framework.web import WebServer

log = logging.getLogger("framework.app")


class App:
    VERSION = framework.__version__

    def __init__(self, config):
        self.config = config
        self.log = log
        self.start_time = time.time()

        # 组件（顺序重要：onebot 先于 bot/napcat/web 创建）
        self.onebot = OneBotServer(self)
        self.msgdb = MessageDB()
        self.ai = AIService(self)
        self.napcat = NapCatManager(self)
        self.plugins = ModuleManager(self)
        self.monitor = QQProcessMonitor(self)
        self.web = WebServer(self)
        self.bot = BotAPI(self)

        # 运行状态
        self.qq_info = None
        self.recent_events = deque(maxlen=300)
        self.contacts = {"friends": [], "groups": [], "updated": 0}
        self._stop = None
        self._tasks = []
        self._migrate_ai_config()

    # ---------- 配置快捷方式 ----------

    def _contact_tags(self) -> dict:
        return self.config.setdefault("contact_tags", {"group": {}, "friend": {}})

    def module_data_dir(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in "_-")
        path = os.path.join(DATA_STORE_DIR, safe)
        os.makedirs(path, exist_ok=True)
        return path

    # ---------- AI 旧配置迁移 ----------

    def _migrate_ai_config(self):
        ai = self.config.get("ai", {})
        if ai.get("api_base") and not ai.get("profiles"):
            ai["profiles"] = {"默认": {"api_base": ai.get("api_base", ""),
                                       "api_key": ai.get("api_key", ""),
                                       "model": ai.get("model", "")}}
            ai["active"] = "默认"
            for k in ("api_base", "api_key", "model"):
                ai.pop(k, None)
            self.config.save()

    # ---------- 生命周期 ----------

    async def run(self):
        self._stop = asyncio.Event()

        await self.web.start()          # 面板 + OneBot API（含 NapCat 状态）
        self.plugins.load_all()
        self.napcat.start()             # 需要时后台注入启动 QQ

        self._spawn(self.monitor.loop())
        self._spawn(self._modules_watcher())
        self._spawn(self._msgdb_cleanup_loop())
        if self.config["inject"].get("enabled"):
            self._spawn(self._inject_loop())

        if self.config["web"].get("auto_open_browser", True):
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.config['server']['port']}/")

        log.info("核心 v%s 已启动（模块目录: %s）", self.VERSION, MODULES_DIR)
        await self._stop.wait()

        log.info("正在停止各模块...")
        for task in self._tasks:
            task.cancel()
        await self.onebot.stop()
        await self.web.stop()
        log.info("框架已完全退出")

    def _spawn(self, coro):
        self._tasks.append(asyncio.create_task(coro))

    def request_shutdown(self):
        if self._stop and not self._stop.is_set():
            self._stop.set()

    # ---------- 事件总线（纯透传：QQ -> 模块 -> QQ） ----------

    def push_event(self, event: dict):
        """NapCat 上报事件：存库、广播给模块和面板。"""
        event.setdefault("_received_at", time.time())
        self.recent_events.append(event)
        if event.get("post_type") == "message":
            asyncio.get_running_loop().run_in_executor(
                None, self.msgdb.add, dict(event))
        self.plugins.dispatch(event)
        self._broadcast_web({"type": "event", "data": event})

    def _broadcast_web(self, payload: dict):
        text = json.dumps(payload, ensure_ascii=False)
        for ws in list(self.web.subscribers):
            self._spawn(self._ws_send(ws, text))

    async def _ws_send(self, ws, text: str):
        try:
            await ws.send_str(text)
        except Exception:
            self.web.subscribers.discard(ws)

    # ---------- 模块热重载监视 ----------

    def _module_state(self) -> dict:
        try:
            return {f: os.stat(os.path.join(MODULES_DIR, f)).st_mtime
                    for f in os.listdir(MODULES_DIR) if f.endswith(".py")}
        except FileNotFoundError:
            return {}

    async def _modules_watcher(self):
        known = self._module_state()
        while True:
            await asyncio.sleep(3)
            current = self._module_state()
            if current == known:
                continue
            added = sorted(set(current) - set(known))
            removed = sorted(set(known) - set(current))
            modified = sorted(f for f in set(known) & set(current)
                              if current[f] != known[f])
            log.info("模块变动（新增 %s 移除 %s 修改 %s），自动重载",
                     added, removed, modified)
            known = current
            await asyncio.get_running_loop().run_in_executor(
                None, self.plugins.reload_all)

    # ---------- 消息库自动清理 ----------

    async def _msgdb_cleanup_loop(self):
        last_retention_check = 0.0
        last_daily = ""
        while True:
            await asyncio.sleep(60)
            cfg = self.config.get("message_db", {})
            now = datetime.now()

            days = int(cfg.get("retention_days", 0) or 0)
            if days > 0 and time.time() - last_retention_check >= 3600:
                last_retention_check = time.time()
                deleted = await asyncio.get_running_loop().run_in_executor(
                    None, self.msgdb.clear_before, days)
                if deleted:
                    log.info("消息库保留期清理: 删除 %d 条（保留 %d 天）", deleted, days)

            t = str(cfg.get("daily_clear_time", "") or "").strip()
            if len(t) == 5 and t == now.strftime("%H:%M"):
                today = now.strftime("%Y-%m-%d")
                if last_daily != today:
                    last_daily = today
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.msgdb.clear_all)
                    log.info("每日定时清空消息库完成（%s）", t)

    # ---------- QQ 进程注入（旧接口，模块一般不用） ----------

    async def _inject_loop(self):
        await asyncio.sleep(3)
        if self.qq_info:
            await self._do_inject(self.qq_info["pid"])

    async def _do_inject(self, pid: int):
        from framework.injector import inject_dll
        dll = self.config["inject"].get("dll_path", "")
        if not dll:
            return
        if not os.path.isabs(dll):
            dll = os.path.join(os.path.dirname(DATA_DIR), dll)
        if not os.path.exists(dll):
            log.warning("注入 DLL 不存在: %s", dll)
            return
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, inject_dll, pid, dll)
        except Exception as e:
            log.error("注入失败: %s", e)

    # ---------- 联系人（好友/群 + 标签分组） ----------

    def _contact_tags(self) -> dict:
        return self.config.setdefault("contact_tags", {"group": {}, "friend": {}})

    async def refresh_contacts(self):
        friends_resp = await self.onebot.call_action("get_friend_list", {})
        groups_resp = await self.onebot.call_action("get_group_list", {})
        self.contacts = {"friends": friends_resp.get("data") or [],
                         "groups": groups_resp.get("data") or [],
                         "updated": time.time()}
        log.info("联系人已刷新: 好友 %d, 群 %d", len(self.contacts["friends"]),
                 len(self.contacts["groups"]))

    def on_onebot_connected(self):
        self._spawn(self._safe_refresh_contacts())

    async def _safe_refresh_contacts(self):
        try:
            await self.refresh_contacts()
        except Exception as e:
            log.warning("自动刷新联系人失败: %s", e)

    def get_contacts(self) -> dict:
        return {"friends": self.contacts.get("friends", []),
                "groups": self.contacts.get("groups", []),
                "updated": self.contacts.get("updated", 0),
                "tags": self.contact_tags_view()}

    def contact_tags_view(self) -> dict:
        raw = self._contact_tags()
        view = {"group": {}, "friend": {}}
        for ctype in ("group", "friend"):
            for cid, tlist in raw[ctype].items():
                for t in tlist:
                    view[ctype].setdefault(t, []).append(cid)
        return view

    def set_contact_tags(self, ctype: str, cid: str, tag_list: list) -> dict:
        raw = self._contact_tags()
        raw[ctype][str(cid)] = [str(t).strip() for t in tag_list if str(t).strip()]
        self.config.save()
        return self.contact_tags_view()

    def get_groups_by_tag(self, tag: str) -> list:
        ids = [str(i) for i in self.contact_tags_view()["group"].get(tag, [])]
        return [g for g in self.contacts.get("groups", [])
                if str(g.get("group_id")) in ids]

    def get_friends_by_tag(self, tag: str) -> list:
        ids = [str(i) for i in self.contact_tags_view()["friend"].get(tag, [])]
        return [f for f in self.contacts.get("friends", [])
                if str(f.get("user_id")) in ids]

    # ---------- 权限 ----------

    def is_admin(self, user_id) -> bool:
        admins = self.config.get("permissions", {}).get("admins", [])
        return str(user_id) in [str(a).strip() for a in admins if str(a).strip()]

    # ---------- 模块数据读写（供 bot 透传） ----------

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
        with open(self._module_data_path(name), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log.info("模块数据已保存: %s", name)
        module = self.plugins.modules.get(name)
        if module and hasattr(module, "on_config"):
            try:
                module.on_config(self, cfg)
            except Exception:
                log.exception("模块 %s on_config 出错", name)
