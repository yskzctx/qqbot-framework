# QQ 机器人框架 —— 第一阶段总结

> 存档日期：2026-09-05 · 状态：一阶段完成，已实测

## 一、项目定位

便携单文件 EXE（`QQBot.exe`，双击即用、无窗口、托盘常驻），部署在天翼云电脑上
7×24 运行。EXE 本体是**核心 + 启动器**：只负责 QQ 进程探测/注入、OneBot 11 API
服务、模块加载、Web 管理面板和 MCP 远控；一切具体功能通过模块扩展。

## 二、一阶段完成内容

### 1. 核心（QQBot.exe，~27MB，PyInstaller onefile）
- QQ 进程自动探测（psutil，可配进程名，实测识别 NTQQ）
- 通用 DLL 注入器（远线程 LoadLibraryW，64 位原型修正 + 绝对路径校验，
  **已在真机 QQ 进程内验证执行成功**，QQ 全程无异常）
- OneBot 11 服务端：正向 WS（QQ 侧连入）+ 反向 WS + HTTP 事件上报 + HTTP 动作
  入口，echo 关联请求响应，access_token 鉴权
- OneBot API 与 Web 面板共用 `0.0.0.0:2280` 单端口
- 默认端口避开 Windows 保留段（3001 在 Hyper-V/WSL 保留范围内会报 winerror 10013）

### 2. Web 管理面板（三页导航）
- **密码体系**：首次打开强制设置密码（SHA-256 加盐哈希存 config.json），
  之后每次进入都需登录；会话 token 仅存页面内存，不落浏览器
- **模块页**：二级导航自动列出已装模块，展示模块自带配置界面
- **AI 配置页**：OpenAI 兼容格式（API 地址/密钥/模型 ID），带测试对话；
  模块通过 `app.ai.chat(messages)` 调用
- **概览页**：QQ 进程状态、OneBot 连接、实时事件流（WS 推送）、动作测试、
  重载模块、关闭框架、MCP 状态与 token

### 3. 模块系统（重点规则，必须遵守）
- 模块目录：`QQBotData/modules/`，**一个 .py = 一个模块**，可带**同名 .html
  作为它在面板中的配置界面**（界面样式由模块自带）
- 元数据约定：模块内定义 `MODULE_INFO = {"name","description","version"}`
- 生命周期钩子：`register(app)`（加载时）、`on_event(bot, event)`（收到 QQ 事件）、
  `on_config(app, config)`（面板保存该模块配置时回调）
- **数据规则：模块产生的数据一律存 `QQBotData/data/<模块名>.json`，
  由核心自动读写，绝不回写模块文件**；模块内用 `app.get_module_config(<名>)` 读写
- 界面约定：HTML 的 JS 从 URL 参数取 `token`，调用
  `/api/modules/<文件名>/config` 读写自身数据（参考自动生成的 example_welcome）
- **热重载**：modules 文件夹有任何增删约 3 秒内自动检测并重载，无需重启；
  面板也可手动点「重载模块」
- 以下划线开头的 `.py` 不作为模块加载（可放工具代码）

### 4. MCP 远程控制服务（端口 2281）
- Streamable HTTP + Bearer token（首次运行自动生成随机 token，概览页可见）
- 10 个工具：run_command（PowerShell）/ screenshot / 鼠标单击右键双击 /
  type_text（Unicode 支持中文）/ press_key（组合键）/ list_dir / read_file / write_file
- 实测：initialize 握手、远程命令执行、截图返回图片均通过

### 5. 隧道助手（TunnelHelper.exe + cloudflared.exe）
- 黑窗口控制台：输入端口（默认 2281，记忆）→ 协议（默认 http2 稳定）→
  显示 trycloudflare.com 公网地址，窗口开着隧道一直有效，断线自动重连
- cloudflared 内核缺失自动下载（ghfast.top 等多镜像，带大小校验）

## 三、实测记录（全部通过）

- 真 QQ 进程注入实验：测试 DLL 在 QQ（PID 37200）内执行成功，QQ 无异常
- EXE 首启：QQBotData 自动生成、面板设置密码、QQ 自动检测
- 认证：设置/登录/错误密码 401/重启后密码哈希仍有效
- 模块：热重载（新增/删除自动感知）、配置持久化、UI 服务
- OneBot：同端口事件上报 → 面板实时收到；模拟客户端动作闭环
- MCP：工具调用与截图返回图片
- 关闭框架：各模块有序退出、零残留进程

## 四、已知问题与结论

1. **代理劫持 cloudflared**（已定位，非程序问题）：本机与云电脑若开代理
   （Clash TUN 等），cloudflared 与 `*.argotunnel.com` 的连接被拦截
   （`TLS handshake with edge error: EOF` / QUIC 超时），表现为隧道
   连上即断、反复重连。解决：代理给 cloudflared.exe 加 DIRECT 规则，
   或放行 `*.argotunnel.com`、`*.trycloudflare.com`，或跑隧道时关 TUN。
2. 托盘"打开管理面板"曾跑到 6099 端口：配置重构后托盘仍读旧字段，
   已修复（现读 `server.port`）并重建 EXE。
3. 本地浏览器访问隧道地址若打不开，多为本机代理劫持 DNS（fake-ip 198.18.x.x），
   换网络路径或调整代理规则即可，服务端本身正常。
4. 隧道断线重连后公网地址会变化，需把新地址告知调用方。

## 五、第二阶段候选事项

- 云电脑上跑通隧道 → ZCode 通过 MCP 接管云电脑（等隧道地址 + token）
- 实际机器人功能模块（自动回复/定时任务/AI 对话接 QQ 消息等）
- 模块在线安装/卸载界面、模块配置表单化（无 HTML 时的通用编辑器优化）
- QQ 侧 NapCat 的部署与对接实测（一阶段未做真机消息收发）
- 日志面板、模块数据查看器、开机自启的托盘提示优化
