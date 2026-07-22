@echo off
chcp 65001 >nul
title 遵农商·抖音客服助手 - Windows 一键构建

echo ============================================
echo   遵农商·抖音客服助手 v1.1 一键构建
echo   内置 Chrome 便携版，目标电脑无需安装任何东西
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
echo [1/6] Python 已就绪

:: ── 下载 Chrome 便携版 + ChromeDriver ──
echo [2/6] 检测内置浏览器...
if not exist "runtime\chrome\chrome.exe" (
    echo   正在下载 Chrome for Testing（约150MB，仅首次）...
    python -c "import urllib.request,json,zipfile,os,shutil; v=json.loads(urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json').read())['channels']['Stable']['version']; print(f'版本: {v}'); os.makedirs('runtime',exist_ok=True); urllib.request.urlretrieve(f'https://storage.googleapis.com/chrome-for-testing-public/{v}/win64/chrome-win64.zip','runtime\\chrome.zip'); zf=zipfile.ZipFile('runtime\\chrome.zip'); zf.extractall('runtime'); zf.close(); os.rename('runtime\\chrome-win64','runtime\\chrome'); os.remove('runtime\\chrome.zip'); print('Chrome 就绪')"
    if %errorlevel% neq 0 (echo [警告] Chrome 下载失败，将使用系统Chrome)
)
if not exist "runtime\chromedriver.exe" (
    echo   正在下载 ChromeDriver...
    python -c "import urllib.request,json,zipfile,os; v=json.loads(urllib.request.urlopen('https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json').read())['channels']['Stable']['version']; urllib.request.urlretrieve(f'https://storage.googleapis.com/chrome-for-testing-public/{v}/win64/chromedriver-win64.zip','runtime\\driver.zip'); zf=zipfile.ZipFile('runtime\\driver.zip'); zf.extractall('runtime'); zf.close(); os.rename('runtime\\chromedriver-win64\\chromedriver.exe','runtime\\chromedriver.exe'); import shutil; shutil.rmtree('runtime\\chromedriver-win64',ignore_errors=True); os.remove('runtime\\driver.zip'); print('ChromeDriver 就绪')"
)
if exist "runtime\chrome\chrome.exe" (
    echo   ✓ 内置 Chrome 就绪
) else (
    echo   ! 将使用系统 Chrome（需目标电脑预装）
)
if exist "runtime\chromedriver.exe" (
    echo   ✓ ChromeDriver 就绪
)

:: ── 创建虚拟环境 ──
echo [3/6] 准备虚拟环境...
if not exist "_build_env" (
    python -m venv _build_env
)
call _build_env\Scripts\activate.bat

:: ── 安装依赖 ──
echo [4/6] 安装依赖...
pip install -q pyinstaller selenium PyQt5 pyperclip

:: ── 更新 worker.py 使其识别内置 Chrome ──
echo [5/6] 配置内置浏览器路径...
python -c "
import re, os
wp = 'worker.py'
with open(wp, 'r', encoding='utf-8') as f:
    code = f.read()
# 确保 _start_browser 使用内置 Chrome
if 'runtime' not in code[:2000]:
    patch = '''
def _get_chrome_path():
    rt = os.path.join(BASE_DIR, \"runtime\", \"chrome\", \"chrome.exe\")
    if os.path.exists(rt): return rt
    return None

def _get_driver_path():
    rt = os.path.join(BASE_DIR, \"runtime\", \"chromedriver.exe\")
    if os.path.exists(rt): return rt
    return None
'''
    # 简单处理：在 find_chromedriver 之前插入
    code = code.replace('def find_chromedriver():', patch + '\ndef find_chromedriver():')
    with open(wp, 'w', encoding='utf-8') as f:
        f.write(code)
    print('已注入内置浏览器检测')
else:
    print('内置浏览器检测已存在')
"

:: ── PyInstaller 打包 ──
echo [6/6] 打包中（约3-8分钟）...

:: 创建目录
if not exist "dist" mkdir dist
if exist "dist\遵农商_抖音客服助手" rd /s /q "dist\遵农商_抖音客服助手"

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
    --hidden-import selenium.webdriver.common.action_chains ^
    --hidden-import pyperclip ^
    --noconfirm main.py

if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

:: ── 复制内置浏览器 ──
if exist "runtime" (
    echo 复制内置浏览器...
    mkdir "dist\遵农商_抖音客服助手\runtime" 2>nul
    xcopy "runtime" "dist\遵农商_抖音客服助手\runtime\" /E /I /Q /Y >nul
    echo   ✓ 内置浏览器已包含
)

:: ── 复制使用说明 ──
(
echo ============================================================
echo     遵农商·抖音客服助手 v1.1
echo     遵义农商银行 出品
echo ============================================================
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
echo   - 每账号独立配置回复话术
echo   - 内置 Chrome 浏览器（无需额外安装）
echo.
echo 【注意】
echo   - 首次使用需扫码登录抖音创作者平台
echo   - 不要删除 runtime 文件夹
echo.
) > "dist\遵农商_抖音客服助手\使用说明.txt"

:: ── 打包 ZIP ──
echo 打包 ZIP...
set ZIP_NAME=遵农商_抖音客服助手_v1.1_Windows.zip
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
echo   目标电脑无需安装 Python、Chrome 或任何依赖
echo ============================================
echo.
pause
