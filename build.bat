@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name "NVIDIA AI Studio" --collect-all keyring --hidden-import keyring.backends.Windows main.py
echo.
echo Build complete: dist\NVIDIA AI Studio.exe
pause
