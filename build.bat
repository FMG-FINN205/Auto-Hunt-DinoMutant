@echo off
chcp 65001 >nul
echo ============================================
echo   BUILD AutoHunt Dino Mutant: T-Rex .EXE
echo ============================================
echo.

:: Cài PyInstaller nếu chưa có (dùng python -m pip)
python -m pip install pyinstaller >nul 2>&1

:: Xoá build cũ
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist AutoHunt.spec del AutoHunt.spec

echo [1/2] Dang build .exe...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --icon=icon.ico ^
    --name=FINN ^
    --hidden-import=cv2 ^
    --hidden-import=PIL ^
    --hidden-import=numpy ^
    entry.py

echo.
if exist dist\FINN.exe (
    echo [2/2] Build THANH CONG!
    echo.
    echo === CAU TRUC THU MUC GUI NGUOI DUNG ===
    echo AutoHuntDino\
    echo   FINN.exe       ^<-- copy tu dist\
    echo   setting.json       ^<-- copy file nay
    echo   ADB\
    echo     adb.exe          ^<-- copy tu Android Platform Tools
    echo   templates\
    echo     Dino1.png  Dino2.png  X.png
    echo     Hunt1.png  Home.png
    echo     Claim.png  Claimall.png  Reset.png
    echo.
    echo File .exe: dist\FINN.exe
) else (
    echo [2/2] Build THAT BAI. Xem log o tren.
)
pause