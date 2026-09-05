"""Cloudflare 隧道助手（黑窗口控制台程序）。

双击运行：
1. 输入要暴露的本机端口（回车默认 2281，会记住）
2. 自动准备 cloudflared 内核（缺失时自动下载，支持国内镜像）
3. 建立 Cloudflare 免费隧道，窗口里显示公网地址
4. 只要本窗口开着隧道就一直有效；断线自动重连（重连后地址可能变化，窗口会提示）
5. 关闭窗口或 Ctrl+C 即断开
"""
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
CLOUDFLARED = os.path.join(BASE_DIR, "cloudflared.exe")
PORT_FILE = os.path.join(BASE_DIR, "port.txt")
URL_FILE = os.path.join(BASE_DIR, "tunnel_url.txt")

DOWNLOAD_SOURCES = [
    "https://ghfast.top/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://ghproxy.net/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    "https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
]

BANNER = r"""
==========================================================
          Cloudflare 隧道助手  (稳定版穿透)
----------------------------------------------------------
  1) 输入本机要暴露的端口 (回车 = 2281, 即 MCP 远控端口)
  2) 窗口会显示一个 https://xxxx.trycloudflare.com 公网地址
  3) 只要本窗口开着, 隧道就一直有效, 最小化即可
  4) 关闭窗口 / Ctrl+C = 断开隧道
==========================================================
"""


def log(msg: str):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def read_saved_port() -> str:
    try:
        with open(PORT_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def ask_port() -> int:
    env_port = os.environ.get("TUNNEL_PORT", "").strip()
    if env_port.isdigit():
        port = int(env_port)
    else:
        saved = read_saved_port()
        hint = f" (回车 = {saved})" if saved else " (回车 = 2281)"
        try:
            raw = input(f"请输入要暴露的本机端口{hint}: ").strip()
        except EOFError:
            raw = ""
        port = int(raw) if raw.isdigit() else int(saved or 2281)
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(port))
    return port


def download_cloudflared():
    if os.path.exists(CLOUDFLARED) and os.path.getsize(CLOUDFLARED) > 10_000_000:
        return
    log("首次运行: 正在下载 cloudflared 内核 (约 20MB)...")
    for url in DOWNLOAD_SOURCES:
        try:
            log(f"  尝试 {url.split('/')[2]} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as resp, \
                 open(CLOUDFLARED + ".part", "wb") as f:
                total = 0
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
                    print(f"\r  已下载 {total / 1048576:.1f} MB", end="", flush=True)
            print()
            os.replace(CLOUDFLARED + ".part", CLOUDFLARED)
            log("下载完成")
            return
        except Exception as e:
            log(f"  该源失败: {e}")
    log("所有下载源均失败！请手动下载 cloudflared-windows-amd64.exe 并放到本程序同目录。")
    input("按回车退出...")
    sys.exit(1)


def ask_protocol() -> str:
    """http2 = 走 TCP，兼容代理/防火墙，最稳（推荐）；quic = 走 UDP，略快但常被网络拦截。"""
    env = os.environ.get("TUNNEL_PROTOCOL", "").strip().lower()
    if env in ("http2", "quic"):
        return env
    try:
        raw = input("协议 http2/quic (回车 = http2, 稳定推荐): ").strip().lower()
    except EOFError:
        raw = ""
    return raw if raw in ("http2", "quic") else "http2"


def run_tunnel(port: int, protocol: str):
    """启动 cloudflared 并解析公网地址；进程退出则自动重连。"""
    attempt = 0
    while True:
        attempt += 1
        url_holder = {"url": None}
        log(f"正在建立隧道 (第 {attempt} 次, 本机端口 {port}, 协议 {protocol}) ...")
        proc = subprocess.Popen(
            [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{port}",
             "--protocol", protocol, "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW)

        def pump(stream=proc.stdout):
            pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
            for line in stream:
                m = pattern.search(line)
                if m and not url_holder["url"]:
                    url_holder["url"] = m.group(0)
                # 关键日志透出到窗口（错误 / 注册成功），其余静默
                if "ERR" in line or "Registered tunnel connection" in line:
                    log(line.strip()[:160])

        t = threading.Thread(target=pump, daemon=True)
        t.start()

        # 最多等 30 秒拿地址
        for _ in range(60):
            time.sleep(0.5)
            if url_holder["url"]:
                break
            if proc.poll() is not None:
                break

        if url_holder["url"]:
            url = url_holder["url"]
            with open(URL_FILE, "w", encoding="utf-8") as f:
                f.write(url)
            print("\n" + "=" * 58)
            print("  隧道已建立! 你的公网地址 (发给对方即可):")
            print()
            print(f"      {url}")
            print()
            print(f"  对应本机端口: {port}")
            print("  验证: 浏览器打开  " + url + "/mcp  应显示 unauthorized")
            print("=" * 58 + "\n", flush=True)
        else:
            log("未能获取公网地址, 将重试...")

        # 常驻: cloudflared 退出(断线)后自动重连
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            raise
        log("隧道连接断开, 3 秒后自动重连 (注意: 重连后公网地址可能变化)...")
        time.sleep(3)


def main():
    os.chdir(BASE_DIR)
    print(BANNER, flush=True)
    try:
        port = ask_port()
        protocol = ask_protocol()
        download_cloudflared()
        run_tunnel(port, protocol)
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(URL_FILE):
            os.remove(URL_FILE)
        print("\n隧道已断开, 再见。")


if __name__ == "__main__":
    main()
