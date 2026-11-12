@echo off
REM ===========================================================================
REM AgentGuard stack launcher for Windows.
REM
REM Starts the backend API, dashboard, and database with Docker Compose,
REM waits for the backend health check, and opens the dashboard.
REM
REM Usage:  start.bat                 (normal start, SQLite)
REM         start.bat --build         (rebuild images first)
REM         start.bat --postgres      (use PostgreSQL instead of SQLite)
REM         start.bat --build --postgres
REM         start.bat --stop          (stop the stack)
REM         start.bat --clean         (stop and remove volumes)
REM ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- Configuration (override with environment variables) -------------------
if "%BACKEND_PORT%"=="" set BACKEND_PORT=8000
if "%FRONTEND_PORT%"=="" set FRONTEND_PORT=8080

set "COMPOSE=docker compose"
set "DASHBOARD_URL=http://localhost:%FRONTEND_PORT%"
set "HEALTH_URL=http://localhost:%BACKEND_PORT%/api/v1/health"

REM --- Argument handling -----------------------------------------------------
if /i "%~1"=="--stop"  goto :stop
if /i "%~1"=="--clean" goto :clean
set "BUILD_FLAG="
set "PROFILE_FLAG="
if /i "%~1"=="--build" set "BUILD_FLAG=--build"
if /i "%~1"=="--postgres" set "PROFILE_FLAG=--profile postgres"

echo.
echo ============================================================
echo   AgentGuard
echo ============================================================
echo   Backend:   http://localhost:%BACKEND_PORT%
echo   Dashboard: %DASHBOARD_URL%
echo ============================================================
echo.

REM --- Preflight checks ------------------------------------------------------
call :check_docker
if errorlevel 1 goto :eof

REM --- Start the stack -------------------------------------------------------
echo [1/4] Starting the AgentGuard stack...
echo.

%COMPOSE%%PROFILE_FLAG% up -d %BUILD_FLAG%
if errorlevel 1 (
    echo.
    echo ERROR: Docker Compose failed to start the stack.
    echo.
    echo Check that the ports are free:
    echo   netstat -ano ^| findstr ":%BACKEND_PORT% :%FRONTEND_PORT%"
    echo.
    goto :eof
)

echo [2/4] Waiting for the backend to become healthy...
call :wait_for_health
if errorlevel 1 goto :health_failed

echo [3/4] Waiting for the dashboard...
call :wait_for_url "%DASHBOARD_URL%"
if errorlevel 1 (
    echo   Warning: the dashboard did not respond yet. It may still be starting.
)

echo [4/4] Opening the dashboard...
echo.
echo   Backend API:   http://localhost:%BACKEND_PORT%/api/docs
echo   Dashboard:     %DASHBOARD_URL%
echo   Health:        %HEALTH_URL%
echo.
echo   Logs:   docker compose logs -f
echo   Stop:   start.bat --stop
echo.

start "" "%DASHBOARD_URL%"
goto :eof

REM ===========================================================================
:check_docker
where docker >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not installed or not on PATH.
    echo Install Docker Desktop from https://www.docker.com/products/docker-desktop/
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is installed but the daemon is not running.
    echo Start Docker Desktop and try again.
    exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
    echo ERROR: The Docker Compose plugin is not available.
    echo Install Docker Desktop or the Compose plugin and try again.
    exit /b 1
)
exit /b 0

REM ===========================================================================
:wait_for_health
REM Poll the backend health endpoint for up to ~90 seconds.
set /a attempts=0
:health_loop
set /a attempts+=1
if !attempts! gtr 90 (
    echo.
    echo ERROR: the backend did not become healthy in time.
    echo Last response:
    curl -s "%HEALTH_URL%"
    echo.
    echo Try: docker compose logs backend
    exit /b 1
)

curl -s -o nul -w "%%{http_code}" "%HEALTH_URL%" > "%TEMP%\ag_health.txt" 2>nul
set /p status=<"%TEMP%\ag_health.txt"
del "%TEMP%\ag_health.txt" >nul 2>&1

if "!status!"=="200" (
    echo   Backend is healthy.
    exit /b 0
)
if !attempts! lss 3 (
    REM Don't spam the console on every poll.
    <nul set /p "=   ."
)
REM 'timeout /t' is a cmd builtin; under an MSYS shell it resolves to the Unix
REM timeout, so prefer ping which behaves the same in both.
ping -n 2 127.0.0.1 >nul 2>&1
goto :health_loop

:health_failed
echo.
echo The stack is running but the health check failed.
echo Inspect: docker compose logs backend
exit /b 1

REM ===========================================================================
:wait_for_url
set /a attempts=0
:url_loop
set /a attempts+=1
if !attempts! gtr 30 exit /b 1
curl -s -o nul -w "%%{http_code}" "%~1" > "%TEMP%\ag_url.txt" 2>nul
set /p status=<"%TEMP%\ag_url.txt"
del "%TEMP%\ag_url.txt" >nul 2>&1
if "!status!"=="200" exit /b 0
ping -n 2 127.0.0.1 >nul 2>&1
goto :url_loop

REM ===========================================================================
:stop
echo Stopping the AgentGuard stack...
%COMPOSE% stop
echo Done.
goto :eof

:clean
echo Stopping the stack and removing volumes...
%COMPOSE% down -v
echo Done.
goto :eof
