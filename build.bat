@echo off
setlocal
cd /d "%~dp0"

echo Gerando executavel...

".venv\Scripts\python.exe" -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name DataloggerDecoder ^
    --icon "assets\datalogger_decoder.ico" ^
    --add-data "assets\datalogger_decoder.ico;assets" ^
    "app.py"

if errorlevel 1 (
    echo.
    echo Falha ao gerar o executavel.
    pause
    exit /b 1
)

echo.
echo Build concluido.
echo Executavel em: dist\DataloggerDecoder.exe
pause