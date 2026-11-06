@echo off
title Installazione Dettami
if not exist "%~dp0setup\installa.ps1" (
    echo.
    echo  Prima estrai lo zip: tasto destro sul file zip, poi "Estrai tutto".
    echo  Poi apri la cartella estratta e fai doppio clic su Installa.bat
    echo.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\installa.ps1"
