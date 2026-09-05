"""QQ 进程自动探测：扫描本机已登录/正在运行的 QQ 进程。"""
import asyncio
import logging
import time

import psutil

log = logging.getLogger("qq.process")


class QQProcessMonitor:
    def __init__(self, app):
        self.app = app
        self.names = [n.lower() for n in app.config["qq"]["process_names"]]
        self.interval = app.config["qq"].get("poll_interval", 5)
        self.info = None  # 当前 QQ 进程信息快照
        self._seen_pids = set()

    def find(self) -> dict | None:
        """返回信息量最大的 QQ 进程（通常为主进程），找不到返回 None。"""
        best = None
        for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "create_time"]):
            try:
                name = (proc.info["name"] or "").lower()
                if name not in self.names:
                    continue
                mem = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
                if best is None or mem > best["memory_mb"] * 1024 * 1024:
                    best = {
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "exe": proc.info["exe"] or "",
                        "memory_mb": round(mem / 1024 / 1024, 1),
                        "create_time": proc.info["create_time"],
                        "uptime_s": int(time.time() - (proc.info["create_time"] or time.time())),
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return best

    async def loop(self):
        log.info("QQ 进程监控已启动，每 %d 秒扫描一次，目标进程: %s", self.interval, self.names)
        while True:
            try:
                found = self.find()
                if found and found["pid"] not in self._seen_pids:
                    self._seen_pids.add(found["pid"])
                    log.info("检测到 QQ 进程: PID=%s 内存=%.1fMB 路径=%s",
                             found["pid"], found["memory_mb"], found["exe"] or "未知")
                    await self.app.on_qq_found(found)
                elif not found and self.info:
                    log.warning("QQ 进程已退出")
                    self._seen_pids.clear()
                    await self.app.on_qq_lost(self.info)
                self.info = found
                self.app.qq_info = found
            except Exception:
                log.exception("QQ 进程扫描出错")
            await asyncio.sleep(self.interval)
