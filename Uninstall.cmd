@echo off
py -3 "%~dp0mystj.py" uninstall --target "%~dp0." --gui
if errorlevel 1 pause
