@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Khong tim thay Python. Cai Python 3.10 tro len va danh dau Add Python to PATH.
        pause
        exit /b 1
    )
    set "PYTHON=python"
) else (
    set "PYTHON=py -3"
)

if not exist ".venv\Scripts\python.exe" (
    echo Dang tao moi truong Python rieng...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo Dang cai dat thu vien can thiet...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo.
echo Nhip Tre dang chay tai http://127.0.0.1:5000
echo Nhan Ctrl+C de dung ung dung.
echo.
".venv\Scripts\python.exe" app.py
pause
exit /b 0

:error
echo Khong the chuan bi moi truong chay. Kiem tra Python va ket noi mang de tai Flask.
pause
exit /b 1
