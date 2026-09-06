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

## 官方模块与开发文档

模块合集与**完整模块开发指南**见：https://github.com/yskzctx/qqbot-modules

## 对接 QQ（已内置，全自动）

NapCat 已内嵌在 EXE 里，**无需手动安装**：

1. 面板「概览」页 → NapCat 注入 → 填入**机器人小号 QQ 号** → 点「保存小号并注入启动」
2. 框架自动：部署 NapCat 核心 → 找到本机 QQ → 注入启动 → 弹出登录窗口
3. 首次登录一次小号（扫码/快速登录），之后每次自动快速登录
4. 面板「OneBot 连接」变绿即成功，机器人上线

说明：注入式运行依赖本机已安装的 QQ 本体（QQ 窗口会被 NapCat 接管运行）；
同一小号只能在一台电脑登录，手机不受影响。建议机器人使用独立小号。

<details><summary>高级：手动 DLL 注入（一般用不到）</summary>

把 64 位 hook DLL 放 modules\，`inject.enabled` 设 true，框架检测到 QQ 进程后自动注入。`bridge\` 有测试源码。

</details>

## OneBot 11 HTTP API（外部调用）

```
GET  http://<ip>:2280/onebot/v11/status?access_token=xxx
POST http://<ip>:2280/onebot/v11/send_private_msg?access_token=xxx
     body: {"user_id": 123456, "message": "hello"}
```

## 24 小时常驻（天翼云电脑）

1. 管理员运行 `install_autostart.bat`，随云电脑登录自启
2. 云电脑设置关闭「自动休眠 / 自动断开」
3. 在云电脑本机浏览器打开 `http://127.0.0.1:2280/` 管理面板

## 排错

- `winerror 10013`：端口落在 Windows 保留段（Hyper-V/WSL 常见），改 `server.port`
- `10048`：端口被占用，多半核心已在运行（看托盘）
- 其他看 `QQBotData\logs\framework.log`
