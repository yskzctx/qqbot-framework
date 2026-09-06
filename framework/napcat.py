"""NapCat 注入管理器：框架唯二的职责之一（另一个是 AI 配置）。

首次运行自动完成：
1. 把内嵌的 NapCat 核心释放到 QQBotData/NapCat/
2. 从注册表找到本机 QQ 安装路径
3. 写入 OneBot11 连接配置（指向本框架的 WS）
4. 关闭已运行的 QQ，带钩子注入启动 QQ（QQ 本体正常运行，NapCat 挂载其中）
5. QQ 侧快速登录配置的小号，OneBot WS 自动连回框架

用户唯一要做的一次性操作：首次注入时在小号上扫码/确认登录。
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import winreg

from framework.paths import DATA_DIR

log = logging.getLogger("napcat")

IS_FROZEN = getattr(sys, "frozen", False)


def _bundled_core() -> str:
    """EXE 内嵌的 NapCat 核心目录。"""
    if IS_FROZEN:
        return os.path.join(sys._MEIPASS, "NapCatCore")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "napcat_embed", "NapCatCore")


class NapCatManager:
    def __init__(self, app):
        self.app = app
        self.status = "未启动"
        self.last_error = ""

    # ---------- 路径 ----------

    @property
    def core_dir(self) -> str:
        return os.path.join(DATA_DIR, "NapCat")

    @property
    def cfg(self) -> dict:
        return self.app.config["napcat"]

    # ---------- 部署 ----------

    def embedded_version(self) -> str:
        try:
            with open(os.path.join(_bundled_core(), "qqnt.json"), encoding="utf-8-sig") as f:
                return json.load(f).get("version", "")
        except Exception:
            return ""

    def deployed_version(self) -> str:
        try:
            with open(os.path.join(self.core_dir, "qqnt.json"), encoding="utf-8-sig") as f:
                return json.load(f).get("version", "")
        except Exception:
            return ""

    def ensure_deployed(self) -> bool:
        """内嵌核心解压到 QQBotData/NapCat；版本变化自动更新。"""
        embedded = self.embedded_version()
        if not embedded:
            self.last_error = "EXE 内未找到内嵌 NapCat 核心"
            log.error(self.last_error)
            return False
        if self.deployed_version() == embedded and \
                os.path.exists(os.path.join(self.core_dir, "napcat", "napcat.mjs")):
            return True
        try:
            if os.path.exists(self.core_dir):
                shutil.rmtree(self.core_dir, ignore_errors=True)
            shutil.copytree(_bundled_core(), self.core_dir)
            log.info("NapCat 核心 %s 已部署到 %s", embedded, self.core_dir)
            return True
        except Exception as e:
            self.last_error = str(e)
            log.exception("NapCat 部署失败")
            return False

    # ---------- QQ 路径 ----------

    def find_qq(self) -> str:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\WOW6432Node\Microsoft\Windows"
                                 r"\CurrentVersion\Uninstall\QQ")
            uninstall, _ = winreg.QueryValueEx(key, "UninstallString")
            winreg.CloseKey(key)
            path = os.path.join(os.path.dirname(uninstall.strip('" ')), "QQ.exe")
            if os.path.exists(path):
                return path
        except Exception:
            pass
        for candidate in (r"C:\Program Files\Tencent\QQNT\QQ.exe", r"D:\0\QQ\QQ.exe"):
            if os.path.exists(candidate):
                return candidate
        return ""

    # ---------- 配置 ----------

    def write_onebot_config(self, account: str):
        """写入 NapCat 的 OneBot11 连接配置（指向本框架 WS）。"""
        token = self.app.config["onebot"].get("access_token", "")
        port = self.app.config["server"]["port"]
        cfg = {
            "network": {
                "websocketClients": [{
                    "name": "QQBot框架",
                    "enable": True,
                    "url": f"ws://127.0.0.1:{port}/onebot/v11/ws",
                    "messagePostFormat": "array",
                    "reportSelfMessage": False,
                    "token": token,
                    "debug": False,
                    "heartInterval": 30000,
                    "reConnectInterval": 5000,
                }]
            },
            "musicSignUrl": "",
            "enableLocalFile2Url": False,
            "parseMultMsg": False,
        }
        path = os.path.join(self.core_dir, "config", f"onebot11_{account}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log.info("OneBot 连接配置已写入: %s", path)

    # ---------- 启动注入 ----------

    # ---------- 兼容旧方式（重启 QQ 注入，一般不用） ----------

    def launch(self) -> tuple[bool, str]:
        """兼容旧方式：关闭 QQ 后带钩子重启（一般用免重启注入即可）。"""
        cfg = self.cfg
        account = str(cfg.get("account", "")).strip()
        if not account.isdigit():
            return False, "未配置机器人 QQ 号（小号）"
        if not self.ensure_deployed():
            return False, self.last_error
        qq_path = self.find_qq()
        if not qq_path:
            return False, "未找到本机 QQ 安装路径（QQNT）"
        self.write_onebot_config(account)

        if cfg.get("auto_close_qq", True):
            subprocess.run(["taskkill", "/IM", "QQ.exe", "/F"],
                           capture_output=True)
            import time
            time.sleep(2)
        main_path = os.path.join(core, "napcat", "napcat.mjs").replace("\\", "/")

        env = os.environ.copy()
        env["NAPCAT_PATCH_PACKAGE"] = os.path.join(core, "qqnt.json")
        env["NAPCAT_LOAD_PATH"] = os.path.join(core, "loadNapCat.js")
        env["NAPCAT_INJECT_PATH"] = os.path.join(core, "NapCatWinBootHook.dll")
        env["NAPCAT_MAIN_PATH"] = main_path

        args = [os.path.join(core, "NapCatWinBootMain.exe"), qq_path,
                os.path.join(core, "NapCatWinBootHook.dll")]
        if cfg.get("auto_login", True):
            args.append(account)

        # 启动并捕获 NapCat 输出（失败时用于诊断）
        import time as _time
        import psutil as _psutil
        log_path = os.path.join(core, "launch.log")
        before = set(p.pid for p in _psutil.process_iter(["name"])
                     if (p.info["name"] or "").lower() == "qq.exe")
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                proc = subprocess.Popen(args, env=env, cwd=core, stdout=lf,
                                        stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
            self.status = "注入中，等待 QQ 启动..."
            for _ in range(12):  # 最多等 24 秒
                _time.sleep(2)
                if proc.poll() is not None:
                    break
                now_count = len([p for p in _psutil.process_iter(["name"])
                                 if (p.info["name"] or "").lower() == "qq.exe"])
                if now_count > len(before):
                    break
            tail = open(log_path, "rb").read()[-800:].decode("gbk", "replace")
            if proc.poll() is not None:
                self.status = "注入启动失败"
                self.last_error = f"NapCat 启动器已退出。输出: {tail}"
                log.error("NapCat 启动器退出，输出: %s", tail)
                return False, f"注入失败，NapCat 输出: {tail}"
            new_qq = len([p for p in _psutil.process_iter(["name"])
                          if (p.info["name"] or "").lower() == "qq.exe"])
            if new_qq <= len(before):
                self.status = "注入启动失败"
                self.last_error = f"QQ 未能启动。NapCat 输出: {tail}"
                log.error("QQ 未能启动，NapCat 输出: %s", tail)
                return False, f"注入失败，QQ 未能启动。NapCat 输出: {tail}"
            self.status = "已注入启动"
            log.info("NapCat 注入启动完成: QQ=%s 小号=%s", qq_path, account)
            return True, "已注入启动，QQ 窗口即将出现（首次需登录一次小号）"
        except Exception as e:
            self.status = "启动失败"
            self.last_error = str(e)
            log.exception("NapCat 启动失败")
            return False, f"启动失败: {e}"

    # ---------- 状态 ----------

    def snapshot(self) -> dict:
        cfg = self.cfg
        return {
            "deployed": self.deployed_version() == self.embedded_version()
                        and self.embedded_version() != "",
            "version": self.embedded_version(),
            "account": str(cfg.get("account", "")),
            "auto_launch": cfg.get("auto_launch", True),
            "status": self.status,
            "last_error": self.last_error,
            "qq_found": bool(self.find_qq()),
        }
