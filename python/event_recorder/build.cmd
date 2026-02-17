@echo off
REM Build script for Event Recorder Docker image (Windows)
REM Must be run from event_recorder directory

setlocal enabledelayedexpansion

set IMAGE_NAME=sfewings32/emon_event_recorder
set VERSION=0.1.0

echo ================================
echo Event Recorder - Docker Build
echo ================================
echo.

REM Save current directory
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

REM Parse argument
set BUILD_TYPE=%1
if "%BUILD_TYPE%"=="" set BUILD_TYPE=local

if "%BUILD_TYPE%"=="local" (
    echo Building for local platform...
    echo Context: %SCRIPT_DIR%\..
    echo Dockerfile: event_recorder\Dockerfile
    echo.

    REM Change to python directory (parent of event_recorder)
    pushd "%SCRIPT_DIR%\.."

    docker build ^
        --tag "%IMAGE_NAME%:latest" ^
        --tag "%IMAGE_NAME%:%VERSION%" ^
        --file event_recorder\Dockerfile ^
        .

    set BUILD_RESULT=%ERRORLEVEL%
    popd

    if !BUILD_RESULT! neq 0 (
        echo.
        echo Build failed!
        exit /b 1
    )

    echo.
    echo Build complete!
    echo Image: %IMAGE_NAME%:latest
    goto :done
)

if "%BUILD_TYPE%"=="test" (
    echo Building test image...
    echo Context: %SCRIPT_DIR%\..
    echo Dockerfile: event_recorder\Dockerfile
    echo.

    REM Change to python directory
    pushd "%SCRIPT_DIR%\.."

    docker build ^
        --tag "%IMAGE_NAME%:test" ^
        --file event_recorder\Dockerfile ^
        .

    set BUILD_RESULT=%ERRORLEVEL%
    popd

    if !BUILD_RESULT! neq 0 (
        echo.
        echo Build failed!
        exit /b 1
    )

    echo.
    echo Running test container...
    docker run --rm -it ^
        -e MQTT_BROKER=mqtt ^
        -v "%SCRIPT_DIR%\config_examples:/config:ro" ^
        -v "%SCRIPT_DIR%\test_data:/data" ^
        -p 5001:5000 ^
        "%IMAGE_NAME%:test"

    goto :done
)

echo Unknown build type: %BUILD_TYPE%
echo.
echo Usage: build.cmd [local^|test]
echo.
echo   local  - Build for current platform only (default)
echo   test   - Build and run test container
echo.
echo Note: Multi-platform builds require Linux or WSL2
echo       Use build.sh for multi-platform builds
exit /b 1

:done
echo.
echo ================================
echo Done!
echo ================================
