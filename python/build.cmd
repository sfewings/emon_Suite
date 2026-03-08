@echo off
REM emon Docker Build Script (Windows)
REM Builds one or many Docker images with flexible platform and mode options
REM
REM Usage: build.cmd [OPTIONS]
REM   -m, --mode MODE         local | push | test  (default: local)
REM   -c, --containers LIST   comma-separated names or 'all'  (default: all)
REM   -p, --platforms PLAT    local | amd64 | arm64 | arm32 | all  (default: local or all)
REM   -h, --help
REM
REM Note: For comma-separated platform combinations (e.g. arm64,arm32) use build.sh via WSL.

setlocal enabledelayedexpansion

REM ============================================================
REM Container Definitions
REM Edit image names and versions here
REM ============================================================
set ALL_CONTAINERS=event_recorder settings_web serial_to_mqtt mqtt_to_influx mqtt_to_log gpsd_to_mqtt query_bom

set DOCKERFILE_event_recorder=event_recorder\Dockerfile
set IMAGE_event_recorder=sfewings32/emon_event_recorder
set VERSION_event_recorder=0.1.0

set DOCKERFILE_settings_web=emon_settings_web\Dockerfile
set IMAGE_settings_web=sfewings32/emon_settings_web
set VERSION_settings_web=0.1.0

set DOCKERFILE_serial_to_mqtt=serialToMQTT.Dockerfile
set IMAGE_serial_to_mqtt=sfewings32/emon_serial_to_mqtt
set VERSION_serial_to_mqtt=latest

set DOCKERFILE_mqtt_to_influx=MQTTToInflux.Dockerfile
set IMAGE_mqtt_to_influx=sfewings32/emon_mqtt_to_influx
set VERSION_mqtt_to_influx=latest

set DOCKERFILE_mqtt_to_log=MQTTToLog.Dockerfile
set IMAGE_mqtt_to_log=sfewings32/emon_mqtt_to_log
set VERSION_mqtt_to_log=latest

set DOCKERFILE_gpsd_to_mqtt=GPSDToMQTT.Dockerfile
set IMAGE_gpsd_to_mqtt=sfewings32/emon_gpsd_to_mqtt
set VERSION_gpsd_to_mqtt=latest

set DOCKERFILE_query_bom=queryBOM.Dockerfile
set IMAGE_query_bom=sfewings32/emon_query_bom
set VERSION_query_bom=latest

REM Script directory (build context root)
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

set BUILDER_NAME=emon_builder

REM ============================================================
REM Defaults
REM ============================================================
set MODE=local
set BUILD_CONTAINERS=all
set PLATFORMS_ARG=

REM ============================================================
REM Parse arguments
REM ============================================================
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="-m"            ( set MODE=%~2&             shift & shift & goto :parse_args )
if /i "%~1"=="--mode"        ( set MODE=%~2&             shift & shift & goto :parse_args )
if /i "%~1"=="-c"            ( set BUILD_CONTAINERS=%~2& shift & shift & goto :parse_args )
if /i "%~1"=="--containers"  ( set BUILD_CONTAINERS=%~2& shift & shift & goto :parse_args )
if /i "%~1"=="-p"            ( set PLATFORMS_ARG=%~2&    shift & shift & goto :parse_args )
if /i "%~1"=="--platforms"   ( set PLATFORMS_ARG=%~2&    shift & shift & goto :parse_args )
if /i "%~1"=="-h"            goto :usage
if /i "%~1"=="--help"        goto :usage
echo Unknown argument: %~1
goto :usage_exit
:args_done

REM Validate mode
if /i "%MODE%"=="local" goto :mode_ok
if /i "%MODE%"=="push"  goto :mode_ok
if /i "%MODE%"=="test"  goto :mode_ok
echo Invalid mode: %MODE%  (valid: local, push, test)
goto :usage_exit
:mode_ok

REM Default platforms based on mode
if "%PLATFORMS_ARG%"=="" (
    if /i "%MODE%"=="push" (
        set PLATFORMS_ARG=all
    ) else (
        set PLATFORMS_ARG=local
    )
)

REM Resolve platform
call :resolve_platform "%PLATFORMS_ARG%"
if errorlevel 1 exit /b 1

REM Validate: all platforms only valid for push
if /i "%MODE%"=="local" (
    if "%RESOLVED_PLATFORMS%"=="linux/amd64,linux/arm64,linux/arm/v7" (
        echo Error: platform 'all' is only valid with push mode.
        echo Use -m push, or specify a single platform for local/test.
        exit /b 1
    )
)
if /i "%MODE%"=="test" (
    if "%RESOLVED_PLATFORMS%"=="linux/amd64,linux/arm64,linux/arm/v7" (
        echo Error: platform 'all' is only valid with push mode.
        exit /b 1
    )
)

REM Resolve container list
if /i "%BUILD_CONTAINERS%"=="all" (
    set CONTAINER_LIST=%ALL_CONTAINERS%
) else (
    REM Replace commas with spaces so for-loop can iterate
    set CONTAINER_LIST=%BUILD_CONTAINERS:,= %
)

REM Setup buildx builder if needed
set NEEDS_BUILDX=0
if /i "%MODE%"=="push" set NEEDS_BUILDX=1
if not /i "%RESOLVED_PLATFORMS%"=="local" set NEEDS_BUILDX=1

if "%NEEDS_BUILDX%"=="1" (
    docker buildx version >nul 2>&1
    if errorlevel 1 (
        echo Error: docker buildx is not available.
        exit /b 1
    )
    docker buildx inspect %BUILDER_NAME% >nul 2>&1
    if errorlevel 1 (
        echo Creating buildx builder: %BUILDER_NAME%
        docker buildx create --name %BUILDER_NAME% --use
    ) else (
        docker buildx use %BUILDER_NAME% >nul 2>&1
    )
)

REM ============================================================
REM Banner
REM ============================================================
echo.
echo ================================
echo   emon Docker Build
echo ================================
echo   Mode:       %MODE%
echo   Containers: %BUILD_CONTAINERS%
echo   Platforms:  %PLATFORMS_ARG%  -^>  %RESOLVED_PLATFORMS%
echo ================================
echo.

REM ============================================================
REM Build loop
REM ============================================================
set PASS_LIST=
set FAIL_LIST=
set BUILD_FAILED=0

for %%i in (%CONTAINER_LIST%) do (
    set BUILD_RESULT=0
    call :build_container %%i
    if !BUILD_RESULT! equ 0 (
        set PASS_LIST=!PASS_LIST! %%i
        echo [OK] %%i
    ) else (
        set FAIL_LIST=!FAIL_LIST! %%i
        set BUILD_FAILED=1
        echo [FAILED] %%i
    )
    echo.
)

REM ============================================================
REM Summary
REM ============================================================
echo ================================
echo   Build Summary
echo ================================
if not "%PASS_LIST%"=="" echo   Passed: %PASS_LIST%
if not "%FAIL_LIST%"=="" echo   Failed: %FAIL_LIST%
echo ================================
echo.

if "%BUILD_FAILED%"=="1" (
    echo One or more builds failed.
    exit /b 1
)

echo All done!
exit /b 0

REM ============================================================
REM Subroutines
REM ============================================================

:build_container
set NAME=%~1
set DOCKERFILE=!DOCKERFILE_%NAME%!
set IMAGE=!IMAGE_%NAME%!
set VERSION=!VERSION_%NAME%!
set BUILD_RESULT=0

if "%DOCKERFILE%"=="" (
    echo Unknown container: %NAME%
    echo Available: %ALL_CONTAINERS%
    set BUILD_RESULT=1
    goto :eof
)

echo --- %NAME% ---
echo   Dockerfile: %DOCKERFILE%
echo   Image:      %IMAGE%:latest
if not "%VERSION%"=="latest" echo   Also:       %IMAGE%:%VERSION%
echo.

if /i "%MODE%"=="local" goto :bc_local
if /i "%MODE%"=="push"  goto :bc_push
if /i "%MODE%"=="test"  goto :bc_test
goto :eof

:bc_local
if /i "%RESOLVED_PLATFORMS%"=="local" (
    docker build ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:latest" ^
        "%SCRIPT_DIR%"
    set BUILD_RESULT=!ERRORLEVEL!
) else (
    docker buildx build ^
        --platform "%RESOLVED_PLATFORMS%" ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:latest" ^
        --load ^
        "%SCRIPT_DIR%"
    set BUILD_RESULT=!ERRORLEVEL!
)
if !BUILD_RESULT! equ 0 (
    if not "%VERSION%"=="latest" (
        docker tag "%IMAGE%:latest" "%IMAGE%:%VERSION%"
    )
    echo.
    echo %NAME% built successfully.
)
goto :eof

:bc_push
if "%VERSION%"=="latest" (
    docker buildx build ^
        --platform "%RESOLVED_PLATFORMS%" ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:latest" ^
        --push ^
        "%SCRIPT_DIR%"
) else (
    docker buildx build ^
        --platform "%RESOLVED_PLATFORMS%" ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:latest" ^
        --tag "%IMAGE%:%VERSION%" ^
        --push ^
        "%SCRIPT_DIR%"
)
set BUILD_RESULT=!ERRORLEVEL!
if !BUILD_RESULT! equ 0 (
    echo.
    echo %NAME% pushed successfully.
)
goto :eof

:bc_test
if /i "%RESOLVED_PLATFORMS%"=="local" (
    docker build ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:test" ^
        "%SCRIPT_DIR%"
) else (
    docker buildx build ^
        --platform "%RESOLVED_PLATFORMS%" ^
        --file "%SCRIPT_DIR%\%DOCKERFILE%" ^
        --tag "%IMAGE%:test" ^
        --load ^
        "%SCRIPT_DIR%"
)
set BUILD_RESULT=!ERRORLEVEL!
if !BUILD_RESULT! neq 0 goto :eof
echo.
echo Running: %NAME%
call :run_test_container %NAME%
set BUILD_RESULT=!ERRORLEVEL!
goto :eof

:run_test_container
set RUN_NAME=%~1
if /i "%RUN_NAME%"=="event_recorder" (
    docker run --rm -it ^
        -e MQTT_BROKER=mqtt ^
        -v "%SCRIPT_DIR%\event_recorder\config_examples:/config:ro" ^
        -v "%SCRIPT_DIR%\event_recorder\test_data:/data" ^
        -p 5001:5000 ^
        "!IMAGE_event_recorder!:test"
    goto :eof
)
if /i "%RUN_NAME%"=="settings_web" (
    docker run --rm -it ^
        -p 5002:5000 ^
        "!IMAGE_settings_web!:test"
    goto :eof
)
echo No specific test run configured for %RUN_NAME%. Starting with default entrypoint...
docker run --rm "!IMAGE_%RUN_NAME%!:test" || echo (no default entrypoint)
goto :eof

:resolve_platform
set PLATFORMS_ARG_IN=%~1
set RESOLVED_PLATFORMS=
if /i "%PLATFORMS_ARG_IN%"=="local"  ( set RESOLVED_PLATFORMS=local                               & goto :eof )
if /i "%PLATFORMS_ARG_IN%"=="amd64"  ( set RESOLVED_PLATFORMS=linux/amd64                         & goto :eof )
if /i "%PLATFORMS_ARG_IN%"=="arm64"  ( set RESOLVED_PLATFORMS=linux/arm64                         & goto :eof )
if /i "%PLATFORMS_ARG_IN%"=="arm32"  ( set RESOLVED_PLATFORMS=linux/arm/v7                        & goto :eof )
if /i "%PLATFORMS_ARG_IN%"=="all"    ( set RESOLVED_PLATFORMS=linux/amd64,linux/arm64,linux/arm/v7 & goto :eof )
echo Unknown platform: %PLATFORMS_ARG_IN%
echo Valid values: local, amd64, arm64, arm32, all
echo Note: For combined platforms (e.g. arm64,arm32) use build.sh via WSL.
exit /b 1

:usage
echo.
echo emon Docker Build Script (Windows)
echo.
echo Usage: build.cmd [OPTIONS]
echo.
echo Options:
echo   -m, --mode MODE         Build mode (default: local)
echo                             local  - build for current/specified platform
echo                             push   - build multi-platform and push to Docker Hub
echo                             test   - build locally then run the container
echo   -c, --containers LIST   Comma-separated container names or 'all' (default: all)
echo   -p, --platforms PLAT    Platform to target (default: local for local/test, all for push)
echo                             local, amd64, arm64, arm32, all
echo   -h, --help              Show this help
echo.
echo Available containers:
echo   event_recorder  settings_web     serial_to_mqtt  mqtt_to_influx
echo   mqtt_to_log     gpsd_to_mqtt     query_bom
echo.
echo Examples:
echo   build.cmd                                    # Build all containers locally
echo   build.cmd -m push                            # Build all and push multi-platform
echo   build.cmd -m push -c event_recorder          # Push event_recorder only
echo   build.cmd -m local -c settings_web,gpsd_to_mqtt
echo   build.cmd -m push -p arm64 -c serial_to_mqtt
echo   build.cmd -m test -c event_recorder
echo.
echo Note: For combined platforms (e.g. -p arm64,arm32) use build.sh via WSL.
goto :eof

:usage_exit
echo.
call :usage
exit /b 1
