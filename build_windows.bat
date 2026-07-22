@echo off
chcp 65001 >nul
title 遵农商·抖音客服助手 - Windows 一键构建

echo ============================================
echo   遵农商·抖音客服助手 v1.2 一键构建
echo   调试版（需目标电脑安装 Chrome）
echo ============================================
echo.

cd /d "%~dp0"

:: ── 检查 Python ──
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [1/4] Python 已就绪

:: ── 下载 ChromeDriver（仅约10MB）──
echo [2/4] 检测 ChromeDriver...
if not exist "chromedriver.exe" (
    echo   正在下载 ChromeDriver（约10MB，仅首次）...
    python -c "import urllib.request,json,zipfile,os; v=json.loads(urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json').read())['channels']['Stable']['version']; urllib.request.urlretrieve(f'https://storage.googleapis.com/chrome-for-testing-public/{v}/win64/chromedriver-win64.zip','driver.zip'); zf=zipfile.ZipFile('driver.zip'); zf.extractall('.'); zf.close(); os.rename('chromedriver-win64\\chromedriver.exe','chromedriver.exe'); import shutil; shutil.rmtree('chromedriver-win64',ignore_errors=True); os.remove('driver.zip'); print('ChromeDriver 就绪')"
)
if exist "chromedriver.exe" (echo   ✓ ChromeDriver 就绪) else (echo   ! 首次运行时会自动下载)

:: ── 创建虚拟环境 ──
echo [3/4] 准备虚拟环境...
if not exist "_build_env" (
    python -m venv _build_env
)
call _build_env\Scripts\activate.bat

:: ── 安装依赖 ──
echo [4/4] 安装依赖 + 打包（约2-5分钟）...
pip install -q pyinstaller selenium PyQt5 pyperclip

:: ── 创建目录 ──
if not exist "dist" mkdir dist
if exist "dist\遵农商_抖音客服助手" rd /s /q "dist\遵农商_抖音客服助手"

pyinstaller --onedir --windowed --name="遵农商_抖音客服助手" ^
    --add-data "config.json;." ^
    --add-data "worker.py;." ^
    --add-data "chromedriver.exe;." ^
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
    --hidden-import selenium.webdriver.common.action_chains ^
    --hidden-import pyperclip ^
    --noconfirm main.py

if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

:: ── 使用说明 ──
(
echo ============================================================
echo     遵农商·抖音客服助手 v1.2
echo     遵义农商银行 出品
echo ============================================================
echo.
echo 【使用前请确保已安装 Chrome 浏览器】
echo   如未安装，请先下载: https://www.google.cn/chrome/
echo.
echo 【使用方法】
echo   1. 双击「遵农商_抖音客服助手.exe」启动程序
echo   2. 点击「新增账号」配置你的抖音账号
echo   3. 设置私信回复话术和评论回复话术
echo   4. 点击「全部启动」开始自动回复
echo.
echo 【功能】
echo   - 多账号抖音私信自动回复
echo   - 多账号抖音评论自动回复
echo.
) > "dist\遵农商_抖音客服助手\使用说明.txt"

:: ── 打包 ZIP ──
echo 打包 ZIP...
set ZIP_NAME=遵农商_抖音客服助手_v1.2_Windows.zip
if exist "dist\%ZIP_NAME%" del "dist\%ZIP_NAME%"
powershell -Command "Compress-Archive -Path 'dist\遵农商_抖音客服助手\*' -DestinationPath 'dist\%ZIP_NAME%'" -Force >nul

:: ── 大小 ──
for %%A in ("dist\%ZIP_NAME%") do set size=%%~zA
set /a sizeMB=%size%/1048576

echo.
echo ============================================
echo   🎉 构建完成！
echo   输出: dist\%ZIP_NAME% (~%sizeMB% MB)
echo.
echo   将此 ZIP 发给任何人，解压后双击 EXE 即可运行
echo   目标电脑需安装 Chrome 浏览器
echo ============================================
echo.
pause
