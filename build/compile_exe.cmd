@echo off
rem Build the app entry exe (WashingText.exe) with MinGW-w64.
rem Edit GCC below if your toolchain lives elsewhere.
setlocal
if "%~1"=="" (set "GCC=D:\Toolchains\x86_64\current\bin") else (set "GCC=%~1")

if not exist "%GCC%\gcc.exe" (
  echo [ERROR] gcc not found: %GCC%\gcc.exe
  echo         usage: compile_exe.cmd [path-to-mingw-bin]
  exit /b 1
)

cd /d "%~dp0"

"%GCC%\windres.exe" --codepage 65001 exe_launcher.rc -O coff -o exe_launcher.res
if errorlevel 1 goto fail

"%GCC%\gcc.exe" -municode -mwindows -O2 -o WashingText.exe exe_launcher.c exe_launcher.res -static
if errorlevel 1 goto fail

echo [OK] built: %cd%\WashingText.exe
exit /b 0

:fail
echo [ERROR] build failed
exit /b 1
