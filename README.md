# QQ 机器人核心（便携 EXE）

单文件便携 EXE，双击即用：自动对接**已登录的原版 QQ**，无窗口、托盘常驻、自动打开浏览器。
EXE 本体只是**核心 + 启动器**：面板 / OneBot API 同机部署，功能全部通过 modules 模块扩展。

## 使用

```
1. 把 QQBot.exe 放到任意目录，双击运行
2. 无窗口，托盘出现绿色 Q 图标，浏览器自动打开管理面板
3. 首次打开面板会要求【设置密码】；之后每次打开面板都需要输入密码
   （会话只保存在页面内存中，不写入浏览器，刷新/重开都要重新登录）
4. EXE 同目录自动生成：

   QQBotData\
   ├── config.json            配置（API 密钥等，填好后重启 EXE）
   ├── logs\framework.log     运行日志
   ├── data\                  模块产生的数据（每个模块一个 .json，不回写模块文件）
   └── modules\               ★ 模块文件夹：随时放入 .py（可带同名 .html 界面）
       ├── example_welcome.py     （自动生成的示例模块）
       └── example_welcome.html   （示例模块的配置界面）
```

## 管理面板（http://<ip>:2280/）

导航栏三项：

| 页面 | 内容 |
|---|---|
| **模块** | 二级导航列出所有已安装模块；选中模块显示它**自带的配置界面**。把模块放进 modules 文件夹后约 3 秒自动出现（自动热重载），无需重启 |
| **AI 配置** | OpenAI 兼容格式：API 地址 + API 密钥 + 模型 ID，可一键测试对话。模块通过 `app.ai.chat(messages)` 调用 |
| **概览** | QQ 进程状态、OneBot 连接、实时事件流、动作测试、重载模块、关闭框架 |

托盘右键：打开管理面板 / 打开模块文件夹 / 退出框架。

## 写模块

`QQBotData\modules\` 下一个 `.py` = 一个模块，可选同名 `.html` 作为配置界面：

```python
MODULE_INFO = {"name": "显示名", "description": "描述", "version": "0.1"}

async def on_event(bot, event):        # 收到 QQ 消息/通知
    if event.get("raw_message") == "/签到":
        await bot.send_group_msg(event["group_id"], "签到成功！")

def on_config(app, config):            # 可选：面板保存该模块配置时回调
    ...

# 模块里读写自己的数据（存 QQBotData/data/<模块>.json）：
cfg = app.get_module_config("my_module")
reply = await app.ai.chat([{"role": "user", "content": "你好"}])   # 调用 AI
```

`.html` 界面约定：JS 从 URL 参数取 `token`，调用 `/api/modules/<文件名>/config` 读写数据（参考 example_welcome.html）。
以下划线开头的 `.py` 不会被当作模块加载。

## config.json

| 键 | 说明 |
|---|---|
| `server.host / port` | 面板 + OneBot API 共用端口，默认 0.0.0.0:2280 |
| `web.password` | 面板密码哈希（首次在网页上设置，不用手改） |
| `onebot.access_token` | **QQ 侧 API 密钥**，QQ 侧连入/调用 OneBot API 必须携带 |
| `ai.*` | API 地址 / 密钥 / 模型 ID（OpenAI 兼容格式，面板里填更方便） |
| `inject.enabled / dll_path` | 自动注入 hook DLL（默认关） |

## 对接 QQ（二选一）

**方式 A：NapCat 连入（推荐）**——NapCat 负责 hook 原版 QQ：
- NapCat 配 WebSocket 客户端 → `ws://127.0.0.1:2280/onebot/v11/ws`，token 填 `onebot.access_token`
- 面板概览「OneBot 连接」变绿即成功

**方式 B：DLL 注入**——核心内置注入器（已在真机 QQ 验证）：把 64 位 hook DLL 放 modules\，`inject.enabled` 设 true。`bridge\` 有测试源码。

## OneBot 11 HTTP API（外部调用）

```
GET  http://<ip>:2280/onebot/v11/status?access_token=xxx
POST http://<ip>:2280/onebot/v11/send_private_msg?access_token=xxx
     body: {"user_id": 123456, "message": "hello"}
```

## 远程访问面板（隧道穿透）

云电脑没有公网 IP 时，用配套的 **隧道助手 TunnelHelper.exe**（黑窗口，基于
Cloudflare Tunnel，免费不用注册，比 localtunnel 稳定，窗口开着就一直有效）把
管理面板端口暴露出去，在任何浏览器远程打开面板：

1. 把 `TunnelHelper.exe` 和 `cloudflared.exe` 放同一目录，双击运行
2. 输入要暴露的本机端口（回车默认 2280），协议回车默认 http2
3. 窗口显示 `https://xxxx.trycloudflare.com` 公网地址，最小化窗口保持隧道
4. 任何设备浏览器打开该地址，输入面板密码即可远程管理

注意：断线自动重连，但重连后公网地址会变（窗口会显示新地址）。

#### 隧道连上就断 / 一直握手失败？（重要）

如果机器上**开着代理软件**（Clash / v2rayN TUN 模式等），代理会拦截 cloudflared
与 Cloudflare 边缘节点的专用连接（`*.argotunnel.com`，日志表现为
`TLS handshake with edge error: EOF` / QUIC 超时 / x509 证书错误），导致隧道
永远握不上手。解决办法（任选其一）：

1. 代理软件里给 **cloudflared.exe 进程加 DIRECT（直连）规则**（推荐）
2. 或在代理里放行域名 `*.argotunnel.com` 和 `*.trycloudflare.com`
3. 或跑隧道时临时退出代理 / 关闭 TUN 模式（浏览器走代理不受影响，可开回系统代理）
4. 若报 `x509: certificate has expired or is not yet valid`，先检查**系统时间**是否准确（云桌面虚机常见时钟漂移），不准先同步时间

同理，其他装了代理的机器上用隧道助手也会遇到此问题，处理方式相同。

## 24 小时常驻（天翼云电脑）

1. 管理员运行 `install_autostart.bat`，随云电脑登录自启
2. 云电脑设置关闭「自动休眠 / 自动断开」
3. 在本地电脑浏览器打开 `http://云电脑IP:2280/` 远程管理

## 排错

- `winerror 10013`：端口落在 Windows 保留段（Hyper-V/WSL 常见），改 `server.port`
- `10048`：端口被占用，多半核心已在运行（看托盘）
- 其他看 `QQBotData\logs\framework.log`
