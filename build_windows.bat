@echo off
chcp 65001 >nul
REM بناء ملف التثبيت على جهاز ويندوز (يتطلب Python 3.11 و Inno Setup 6)
python -m pip install -r requirements-dev.txt || goto :err
python -m pytest -q || goto :err
pyinstaller --noconfirm baqala.spec || goto :err
for /f %%v in ('python -c "import baqala; print(baqala.__version__)"') do set VER=%%v
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=%VER% installer\BaqalaPOS.iss || goto :err
echo.
echo تم: Output\BaqalaPOS-Setup-%VER%.exe
exit /b 0
:err
echo فشل البناء
exit /b 1
