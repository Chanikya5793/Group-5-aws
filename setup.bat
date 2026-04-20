@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || (
    echo [ERROR] Unable to switch to repository directory: %SCRIPT_DIR%
    exit /b 1
)

set "MARKER_FILE=.setup_complete"

if not exist "manage.py" (
    echo [ERROR] manage.py not found. Run this script from the project repository.
    exit /b 1
)

if exist "%MARKER_FILE%" (
    set /p SETUP_TIME=<"%MARKER_FILE%"
    echo [INFO] Setup already completed on !SETUP_TIME!
    echo [INFO] To start the app:
    echo        venv\Scripts\activate
    echo        python manage.py runserver
    exit /b 0
)

set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found. Install Python 3.9+ from https://www.python.org/
    exit /b 1
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 (
    for /f "delims=" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VERSION=%%v"
    echo [ERROR] Python 3.9+ is required. Found: !PY_VERSION!
    exit /b 1
)

for /f "delims=" %%v in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VERSION=%%v"
echo [INFO] Using !PY_VERSION!

if not exist "venv\Scripts\python.exe" (
    echo [STEP] Creating virtual environment
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

set "VENV_PY=venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment python not found at %VENV_PY%
    exit /b 1
)

echo [STEP] Upgrading pip tooling
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip tooling.
    exit /b 1
)

echo [STEP] Installing dependencies from requirements.txt
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] requirements install failed. Retrying without psycopg2-binary for local SQLite setup.
    > setup_requirements_windows.tmp.txt (
        for /f "usebackq delims=" %%L in ("requirements.txt") do (
            set "REQ_LINE=%%L"
            echo(!REQ_LINE!| findstr /I /B /C:"psycopg2-binary" >nul
            if errorlevel 1 echo(!REQ_LINE!
        )
    )
    "%VENV_PY%" -m pip install -r setup_requirements_windows.tmp.txt
    if errorlevel 1 (
        del /q setup_requirements_windows.tmp.txt >nul 2>&1
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
    del /q setup_requirements_windows.tmp.txt >nul 2>&1
)

echo [STEP] Applying database migrations
"%VENV_PY%" manage.py migrate --noinput
if errorlevel 1 (
    echo [ERROR] Django migration failed.
    exit /b 1
)

echo [STEP] Running Django startup checks
"%VENV_PY%" manage.py check
if errorlevel 1 (
    echo [ERROR] Django check failed.
    exit /b 1
)

set "SEED_MODE=none"
"%VENV_PY%" manage.py help load_sample_data >nul 2>&1
if not errorlevel 1 (
    set "SEED_MODE=legacy"
    echo [STEP] Loading demo users and sessions
    "%VENV_PY%" manage.py load_sample_data
    if errorlevel 1 echo [WARN] load_sample_data failed and was skipped.
 ) else (
    "%VENV_PY%" manage.py help seed_curated_demo_data >nul 2>&1
    if not errorlevel 1 (
        set "SEED_MODE=core_curated"
        echo [STEP] Seeding curated demo data
        "%VENV_PY%" manage.py seed_curated_demo_data
        if errorlevel 1 echo [WARN] seed_curated_demo_data failed and was skipped.
    ) else (
        "%VENV_PY%" manage.py help seed_mass_test_data >nul 2>&1
        if not errorlevel 1 (
            set "SEED_MODE=core_mass"
            echo [STEP] Seeding mass test data
            "%VENV_PY%" manage.py seed_mass_test_data
            if errorlevel 1 echo [WARN] seed_mass_test_data failed and was skipped.
        ) else (
            echo [WARN] No supported seed command was found.
        )
    )
)

"%VENV_PY%" manage.py help import_real_csv >nul 2>&1
if errorlevel 1 (
    echo [INFO] Real CSV import command is not available in this project configuration.
) else (
    if exist "sample_data\de0e9b2c_20251013.csv" (
        echo [STEP] Importing real hardware CSV
        "%VENV_PY%" manage.py import_real_csv --path sample_data\de0e9b2c_20251013.csv
        if errorlevel 1 echo [WARN] import_real_csv failed and was skipped.
    ) else (
        echo [WARN] Real CSV not found at sample_data\de0e9b2c_20251013.csv
    )
)

if exist "generate_sample_csvs.py" (
    echo [STEP] Generating extra sample CSV files
    "%VENV_PY%" generate_sample_csvs.py
    if errorlevel 1 echo [WARN] generate_sample_csvs.py failed and was skipped.
)

> "%MARKER_FILE%" echo %DATE% %TIME%

echo.
echo [OK] Setup complete.
echo [INFO] Start the app with:
echo        venv\Scripts\activate
echo        python manage.py runserver
echo [INFO] Open: http://127.0.0.1:8000
echo.
echo Login hints:
echo   Admin: admin / admin123
if /I "!SEED_MODE!"=="legacy" (
    echo   Clinician: dr_smith / clinic123
    echo   Patient: patient_001 / patient123
) else if /I "!SEED_MODE!"=="core_curated" (
    echo   Clinician: clinician1 / clinician123
    echo   Patient: patient1 / patient123
) else if /I "!SEED_MODE!"=="core_mass" (
    echo   Clinician: clinician1 / clinician123
    echo   Patient: patient1 / patient123
) else (
    echo   Seed users were not auto-created.
)

exit /b 0
