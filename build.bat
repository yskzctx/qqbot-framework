@echo off
chcp 65001 >nul
REM QQ 机器人框架 一键构建脚本：从源码重新打包 QQBot.exe
REM 前提：本机已安装 Python 3.10+ 和 Git Bash/镜像网络（下载 NapCat 内核用）

cd /d "%~dp0"

echo [1/3] 安装依赖...
python -m pip install -q aiohttp psutil pystray Pillow pyinstaller

echo [2/3] 准备 NapCat 内核...
if not exist napcat_core\qqnt.json (
    echo   首次构建：下载 NapCat 核心（约 30MB）...
    mkdir napcat_core 2>nul
    for %%u in ("https://gh.llkk.cc/" "https://ghfast.top/" "") do (
        curl -sL -m 300 -o napcat_core_tmp.zip "%%~uhttps://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.zip" && (
            for /f %%s in ('powershell -Command "(Get-Item napcat_core_tmp.zip).Length"') do set SZ=%%s
        )
        if defined SZ if !SZ! GTR 5000000 (
            powershell -NoProfile -Command "Expand-Archive -Path napcat_core_tmp.zip -DestinationPath napcat_core -Force"
            echo   下载成功
            goto :core_ok
        )
        del napcat_core_tmp.zip 2>nul
    )
    echo   全部下载源失败！请手动下载 NapCat.Shell.zip 解压到 napcat_core\ 文件夹
    pause
    exit /b 1
)
:core_ok
echo   NapCat 内核就绪

echo [3/3] 打包 EXE...
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name QQBot ^
    --icon app.ico ^
    --add-data "static;static" ^
    --add-data "napcat_core;NapCatCore" ^
    main.py
if exist dist\QQBot.exe (
    copy /y dist\QQBot.exe QQBot.exe >nul
    echo.
    echo 构建成功！QQBot.exe 已生成在本目录
) else (
    echo 构建失败，请检查上方错误信息
)
pause
