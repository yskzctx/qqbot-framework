@echo off
rem 开机自启动（随云电脑登录自动运行 QQBot.exe），需以管理员身份运行本脚本一次
rem 若 exe 不在本脚本同目录，请修改下面的 EXE 路径
cd /d "%~dp0"
schtasks /Create /F /SC ONLOGON /TN "QQBotFramework" /TR "\"%~dp0QQBot.exe\""
if %errorlevel%==0 (
  echo 已设置开机自启动：任务名 QQBotFramework
) else (
  echo 设置失败，请右键"以管理员身份运行"本脚本
)
pause
