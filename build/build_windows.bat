@echo off
setlocal
cd /d "%~dp0.."

echo [1/4] 安装依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt || goto :error

echo [2/4] 运行单元测试...
python -m unittest discover -s tests -t . || goto :error

echo [3/4] 打包...
python -m PyInstaller build\pyinstaller.spec --noconfirm --clean || goto :error

echo [4/4] 完成
echo 产物目录: %cd%\dist\ShoppingPlatImgCatcher\
echo 双击 ShoppingPlatImgCatcher.exe 运行，首次启动会自动下载浏览器内核。
exit /b 0

:error
echo 构建失败，请检查上面的错误信息。
exit /b 1
