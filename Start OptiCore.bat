@echo off
rem Double-click to start OptiCore Studio: starts the engine and the user
rem interface and opens the browser. Close this window to stop the program.
title OptiCore Studio
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -Open
