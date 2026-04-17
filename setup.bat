@echo off
setlocal enabledelayedexpansion
echo.
echo   ====================================================
echo    SENSORE - Graphene Trace  ^|  Setup
echo   ====================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)

echo [1/7] Creating virtual environment...
if not exist venv python -m venv venv
call venv\Scripts\activate.bat

echo [2/7] Installing dependencies from requirements.txt...
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo [3/7] Applying database migrations...
python manage.py makemigrations --check --dry-run
python manage.py migrate --no-input

echo [4/7] Loading synthetic demo data (5 patients)...
python manage.py load_sample_data

echo [5/7] Importing real Sensore CSV...
if exist sample_data\de0e9b2c_20251013.csv (
    python manage.py import_real_csv --path sample_data\de0e9b2c_20251013.csv
) else (
    echo WARNING: sample_data\de0e9b2c_20251013.csv not found.
    echo Copy the file there and run: python manage.py import_real_csv
)

echo [6/7] Generating synthetic CSV test files...
python generate_sample_csvs.py

echo [7/7] Done!
echo.
echo   Start the server:
echo     venv\Scripts\activate
echo     python manage.py runserver
echo.
echo   Open http://127.0.0.1:8000
echo.
echo   Real data:  de0e9b2c / patient123
echo   Clinician:  dr_smith  / clinic123
echo   Admin:      admin     / admin123
echo.
pause
