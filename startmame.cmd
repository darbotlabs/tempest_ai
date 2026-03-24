@echo off
set GAME=%TEMPEST_MAME_GAME%
if "%GAME%"=="" set GAME=tempest1
set ROMPATH=%TEMPEST_MAME_ROMPATH%
if "%ROMPATH%"=="" set ROMPATH=%USERPROFILE%\mame\roms
set USE_LUA=%TEMPEST_MAME_USE_LUA%
if "%USE_LUA%"=="" set USE_LUA=auto
set AUTOBOOT=
if "%USE_LUA%"=="1" set AUTOBOOT=-autoboot_script c:\users\dave\source\repos\tempest_ai\Scripts\main.lua
if "%USE_LUA%"=="auto" if /I "%GAME%"=="tempest1" set AUTOBOOT=-autoboot_script c:\users\dave\source\repos\tempest_ai\Scripts\main.lua
for /l %%x in (1,1,16) do (
    start /b mame %GAME% -skip_gameinfo %AUTOBOOT% -nothrottle -sound none -window -frameskip 9 -rompath "%ROMPATH%" >nul
)
