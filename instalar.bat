@echo off
rem Instala todo lo necesario en una carpeta venv junto a este archivo.
cd /d "%~dp0"

where python >nul 2>nul || (echo Falta Python 3.11 o superior: https://www.python.org/downloads/ & pause & exit /b 1)

echo == Creando entorno de Python...
if not exist venv python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip -q
venv\Scripts\python.exe -m pip install -r requirements.txt -q || (echo Fallo la instalacion de paquetes & pause & exit /b 1)

echo == Descargando idiomas del traductor offline (checo-ingles, ingles-espanol)...
venv\Scripts\python.exe -c "import argostranslate.package as p; p.update_package_index(); [p.install_from_path(x.download()) for x in p.get_available_packages() if (x.from_code, x.to_code) in [('cs','en'), ('en','es')]]"

where ffmpeg >nul 2>nul || (echo == Instalando ffmpeg... & winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements)
if not exist "C:\Program Files\VideoLAN\VLC\vlc.exe" (echo == Instalando VLC... & winget install -e --id VideoLAN.VLC --silent --accept-package-agreements --accept-source-agreements)

echo.
echo Listo. Usa "subtitulos_en_vivo.bat" o arrastra un video sobre "subtitular.bat".
pause
