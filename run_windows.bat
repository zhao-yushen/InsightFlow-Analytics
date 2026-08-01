@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"
echo [2/4] Installing InsightFlow...
python -m pip install --upgrade pip
python -m pip install -e .

if not exist "data\warehouse\insightflow.db" (
  echo [3/4] Preparing demo warehouse...
  insightflow bootstrap
) else (
  echo [3/4] Existing warehouse detected.
)

echo [4/4] Starting InsightFlow Pro v0.4.3.3...
insightflow run
endlocal
