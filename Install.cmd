@echo off
py -3 "%~dp0mystj.py" install --gui
if errorlevel 1 pause
