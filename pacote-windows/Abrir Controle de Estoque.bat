@echo off
title Controle de Estoque - Almoxarifado
cd /d "%~dp0app"
"%~dp0python\python.exe" -E -s -X utf8 abrir.py
if errorlevel 1 pause
