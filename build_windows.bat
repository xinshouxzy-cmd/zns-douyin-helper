@echo off
chcp 65001 >nul
title 遵农商·抖音客服助手 - Windows 构建脚本

echo ============================================
echo   遵农商·抖音客服助手 v1.0 一键构建
echo   适用: Windows 10/11 + Python 3.10+
echo ============================================
echo.

:: ── 检查 Python ──
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [1/5] Python 已就绪

:: ── 创建虚拟环境 ──
if not exist "_build_env" (
    echo [2/5] 创建虚拟环境...
    python -m venv _build_env
)
call _build_env\Scripts\activate.bat

:: ── 安装依赖 ──
echo [3/5] 安装依赖 (selenium + PyQt5)...
pip install -q pyinstaller selenium PyQt5 pyperclip

:: ── 检查/下载 chromedriver ──
echo [4/5] 检查 chromedriver...
if not exist "chromedriver.exe" (
    echo 正在下载 chromedriver.exe...
    powershell -Command "Invoke-WebRequest -Uri 'https://storage.googleapis.com/chrome-for-testing-public/last-known-good-version/chromedriver-win64.zip' -OutFile '%TEMP%\cd_win64.zip'" 2>nul
    if exist "%TEMP%\cd_win64.zip" (
        powershell -Command "Expand-Archive -Path '%TEMP%\cd_win64.zip' -DestinationPath '%TEMP%\cd_extract' -Force" 2>nul
        for /d %%d in ("%TEMP%\cd_extract\chromedriver-*") do (
            copy "%%d\chromedriver.exe" "chromedriver.exe" >nul 2>&1
        )
    )
    if not exist "chromedriver.exe" (
        echo [警告] chromedriver 下载失败，运行时会自动从 Selenium Manager 获取
    )
)

:: ── PyInstaller 构建 ──
echo [5/5] 打包中 (可能需要几分钟)...
pyinstaller --onedir --windowed --name="遵农商_抖音客服助手" ^
    --add-data "config.json;." ^
    --add-data "worker.py;." ^
    --add-data "replied_records;replied_records" ^
    --add-data "chrome_profiles;chrome_profiles" ^
    --add-data "comment_data;comment_data" ^
    --hidden-import PyQt5.QtCore ^
    --hidden-import PyQt5.QtGui ^
    --hidden-import PyQt5.QtWidgets ^
    --hidden-import selenium.webdriver.chrome.service ^
    --hidden-import selenium.webdriver.common.by ^
    --hidden-import selenium.webdriver.support.ui ^
    --hidden-import selenium.webdriver.support.expected_conditions ^
    --hidden-import selenium.common.exceptions ^
    --hidden-import pyperclip ^
    --noconfirm main.py

if %errorlevel% neq 0 (
    echo [错误] 打包失败，请检查错误信息
    pause
    exit /b 1
)

:: ── 复制 chromedriver 到打包目录 ──
if exist "chromedriver.exe" (
    copy "chromedriver.exe" "dist\遵农商_抖音客服助手\_internal\" >nul
    echo chromedriver.exe 已包含
)

:: ── 复制使用说明 ──
echo ============================================================ > "dist\遵农商_抖音客服助手\使用说明.txt"
echo     遵农商·抖音客服助手 v1.0 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo ============================================================ >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo. >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo 【使用方法】 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   1. 双击「遵农商_抖音客服助手.exe」启动程序 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   2. 点击「添加账号」配置你的抖音账号 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   3. 设置私信回复话术和评论回复话术 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   4. 点击「全部启动」开始挂机自动回复 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo. >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo 【功能】 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   - 多账号抖音私信自动回复 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   - 多账号抖音评论自动回复 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   - 每账号独立配置回复话术 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo. >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo 【注意】 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   - 首次使用需扫码登录抖音创作者平台 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   - 需安装 Google Chrome 浏览器 >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo. >> "dist\遵农商_抖音客服助手\使用说明.txt"
echo   遵义农商银行 出品 >> "dist\遵农商_抖音客服助手\使用说明.txt"

:: ── 打包 zip ──
echo 正在打包 zip...
set ZIP_NAME=遵农商_抖音客服助手_v1.0.0_Windows.zip
if exist "dist\%ZIP_NAME%" del "dist\%ZIP_NAME%"
powershell -Command "Compress-Archive -Path 'dist\遵农商_抖音客服助手\*' -DestinationPath 'dist\%ZIP_NAME%'" >nul

echo.
echo ============================================
echo   构建完成！
echo   输出文件: dist\%ZIP_NAME%
echo   解压后双击 .exe 即可运行
echo ============================================
echo.
pause
