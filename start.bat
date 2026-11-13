@echo off
REM ===========================================================================
REM AgentGuard launcher for Windows.
REM
REM Starts the backend API, dashboard, and database.
REM
REM Usage:
REM   start.bat                     Start stack with Docker Compose (SQLite)
REM   start.bat --build             Rebuild Docker images first
REM   start.bat --postgres          Use PostgreSQL profile (Docker)
REM   start.bat --build --postgres  Rebuild with PostgreSQL
REM   start.bat --stop              Stop Docker stack
REM   start.bat --clean             Stop Docker stack and remove volumes
REM   start.bat --local             Start backend + frontend locally (no Docker)
REM   start.bat --help              Show this help
REM
REM Environment overrides: BACKEND_PORT (8000), FRONTEND_PORT (8080/5173 local)
REM ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- Configuration ---------------------------------------------------------
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8000"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=8080"

set "COMPOSE=docker compose"
set "BUILD_FLAG="
set "PROFILE_FLAG="
set "MODE=docker"

REM --- Argument parsing (all args) -------------------------------------------
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--help"    goto :show_help
if /i "%~1"=="-h"        goto :show_help
if /i "%~1"=="--stop"    set "MODE=stop"
if /i "%~1"=="--clean"   set "MODE=clean"
if /i "%~1"=="--local"   set "MODE=local"
if /i "%~1"=="--build"   set "BUILD_FLAG=--build"
if /i "%~1"=="--postgres" set "PROFILE_FLAG=--profile postgres"
shift
goto :parse_args
:args_done

if "%MODE%"=="stop"  goto :stop
if "%MODE%"=="clean" goto :clean
if "%MODE%"=="local" goto :local

if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=8080"
set "DASHBOARD_URL=http://localhost:%FRONTEND_PORT%"
set "HEALTH_URL=http://localhost:%BACKEND_PORT%/api/v1/health"

echo.
echo ============================================================
echo   AgentGuard (Docker)
echo ============================================================
echo   Backend:   http://localhost:%BACKEND_PORT%
echo   Dashboard: %DASHBOARD_URL%
echo ============================================================
echo.

REM --- Preflight checks ------------------------------------------------------
call :check_docker
if errorlevel 1 goto :fail

REM --- Start the stack -------------------------------------------------------
echo [1/4] Starting the AgentGuard stack...
echo.
%COMPOSE% %PROFILE_FLAG% up -d %BUILD_FLAG%
if errorlevel 1 (
    echo.
    echo ERROR: Docker Compose failed to start the stack.
    echo.
    echo Check that docker-compose.yml exists and ports are free:
    echo   netstat -ano ^| findstr ":%BACKEND_PORT% :%FRONTEND_PORT%"
    echo.
    echo Tip: run "start.bat --local" to start without Docker.
    echo.
    goto :fail
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
echo   Local:  start.bat --local
echo.
start "" "%DASHBOARD_URL%"
goto :eof

REM ===========================================================================
:show_help
echo.
echo AgentGuard launcher
echo.
echo   start.bat                     Start stack with Docker Compose (SQLite)
echo   start.bat --build             Rebuild Docker images first
echo   start.bat --postgres          Use PostgreSQL profile (Docker)
echo   start.bat --build --postgres  Rebuild with PostgreSQL
echo   start.bat --stop              Stop Docker stack
echo   start.bat --clean             Stop Docker stack and remove volumes
echo   start.bat --local             Start backend + frontend locally (no Docker)
echo   start.bat --help              Show this help
echo.
echo Environment:
echo   BACKEND_PORT   Backend port (default 8000)
echo   FRONTEND_PORT  Frontend/dashboard port (Docker default 8080, local 5173)
echo.
goto :eof

REM ===========================================================================
:check_docker
where docker >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not installed or not on PATH.
    echo Install Docker Desktop: https://www.docker.com/products/docker-desktop/
    echo.
    echo To run without Docker, use: start.bat --local
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is installed but the daemon is not running.
    echo Start Docker Desktop and try again.
    echo.
    echo To run without Docker, use: start.bat --local
    exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
    echo ERROR: The Docker Compose plugin is not available.
    echo Install Docker Desktop or the Compose plugin and try again.
    echo.
    echo To run without Docker, use: start.bat --local
    exit /b 1
)
if not exist "docker-compose.yml" if not exist "docker-compose.yaml" if not exist "compose.yml" if not exist "compose.yaml" (
    echo ERROR: No docker-compose.yml found in %CD%.
    echo To run without Docker, use: start.bat --local
    exit /b 1
)
exit /b 0

REM ===========================================================================
:local
if "%FRONTEND_PORT%"=="8080" set "FRONTEND_PORT=5173"
set "DASHBOARD_URL=http://localhost:%FRONTEND_PORT%"
set "HEALTH_URL=http://localhost:%BACKEND_PORT%/api/v1/health"
echo.
echo ============================================================
echo   AgentGuard (Local dev)
echo ============================================================
echo   Backend:   http://localhost:%BACKEND_PORT%
echo   Dashboard: %DASHBOARD_URL%
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Install Python 3.10+ and try again.
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm is not installed or not on PATH.
    echo Install Node.js (includes npm) and try again.
    goto :fail
)

if not exist "backend\app\main.py" (
    echo ERROR: backend\app\main.py not found. Run from the repository root.
    goto :fail
)
if not exist "frontend\package.json" (
    echo ERROR: frontend\package.json not found. Run from the repository root.
    goto :fail
)

set "PYTHON_EXE=python"
if exist "backend\.venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\backend\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if not exist "frontend\node_modules" (
    echo [1/4] Installing frontend dependencies...
    pushd frontend
    call npm install
    if errorlevel 1 (
        popd
        echo ERROR: npm install failed.
        goto :fail
    )
    popd
) else (
    echo [1/4] Frontend dependencies already installed.
)

echo [2/4] Starting backend (uvicorn)...
start "AgentGuard Backend" cmd /k "cd /d "%CD%\backend" && set PYTHONPATH=%CD%\backend && "%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

echo [3/4] Starting frontend (Vite dev server)...
start "AgentGuard Frontend" cmd /k "cd /d "%CD%\frontend" && set VITE_USE_MOCK=false && npm run dev -- --port %FRONTEND_PORT%"

echo [4/4] Waiting for backend health...
call :wait_for_health
if errorlevel 1 (
    echo.
    echo Warning: backend did not become healthy yet. Check the "AgentGuard Backend" window.
) else (
    echo   Backend is healthy.
)

echo.
echo   Backend API:   http://localhost:%BACKEND_PORT%/api/docs
echo   Dashboard:     %DASHBOARD_URL%
echo   Health:        %HEALTH_URL%
echo.
echo   Backend and frontend are running in separate windows.
echo   Close those windows or press Ctrl+C in them to stop.
echo.
start "" "http://localhost:%BACKEND_PORT%/api/docs"
ping -n 3 127.0.0.1 >nul 2>&1
start "" "%DASHBOARD_URL%"
goto :eof

REM ===========================================================================
:wait_for_health
set /a attempts=0
:health_loop
set /a attempts+=1
if !attempts! gtr 90 (
    echo.
    echo ERROR: the backend did not become healthy in time.
    where curl >nul 2>&1
    if not errorlevel 1 (
        echo Last response:
        curl -s "%HEALTH_URL%"
        echo.
    )
    echo Try: docker compose logs backend  (Docker) or check the backend window (local).
    exit /b 1
)

where curl >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 2).StatusCode } catch { 0 }" > "%TEMP%\ag_health.txt" 2>nul
) else (
    curl -s -o nul -w "%%{http_code}" "%HEALTH_URL%" > "%TEMP%\ag_health.txt" 2>nul
)
set /p status=<"%TEMP%\ag_health.txt"
del "%TEMP%\ag_health.txt" >nul 2>&1

if "!status!"=="200" exit /b 0
ping -n 2 127.0.0.1 >nul 2>&1
goto :health_loop

:health_failed
echo.
echo The stack is running but the health check failed.
echo Inspect: docker compose logs backend
echo Tip: run "start.bat --local" to start without Docker.
goto :fail

REM ===========================================================================
:wait_for_url
set /a attempts=0
:url_loop
set /a attempts+=1
if !attempts! gtr 30 exit /b 1
where curl >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri '%~1' -TimeoutSec 2).StatusCode } catch { 0 }" > "%TEMP%\ag_url.txt" 2>nul
) else (
    curl -s -o nul -w "%%{http_code}" "%~1" > "%TEMP%\ag_url.txt" 2>nul
)
set /p status=<"%TEMP%\ag_url.txt"
del "%TEMP%\ag_url.txt" >nul 2>&1
if "!status!"=="200" exit /b 0
ping -n 2 127.0.0.1 >nul 2>&1
goto :url_loop

REM ===========================================================================
:stop
echo Stopping the AgentGuard stack...
call :check_docker >nul 2>&1
%COMPOSE% stop
echo Done.
goto :eof

:clean
echo Stopping the stack and removing volumes...
call :check_docker >nul 2>&1
%COMPOSE% down -v
echo Done.
goto :eof

:fail
echo.
echo Start did not complete. Fix the issue above and try again.
echo If double-clicked, this window will pause so you can read the message.
pause
exit /b 1
