@echo off
REM Build de idiAuto para Windows (binario unico en dist\idiauto.exe)
setlocal
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install playwright textual keyring html2text pyinstaller
playwright install chromium

pyinstaller idiauto.spec --noconfirm

echo.
echo ============================================
echo  Binario listo: dist\idiauto.exe
echo  Ejecuta con: dist\idiauto.exe
echo ============================================
pause
