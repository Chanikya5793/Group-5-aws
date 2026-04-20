#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
MARKER_FILE="$PROJECT_DIR/.setup_complete"
VENV_DIR="$PROJECT_DIR/venv"

log() {
  printf '%s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  die "Python was not found. Install Python 3.9+ and re-run setup.sh"
}

run_required() {
  local description="$1"
  shift
  log "[STEP] $description"
  "$@"
}

run_optional() {
  local description="$1"
  shift
  log "[STEP] $description"
  if ! "$@"; then
    warn "$description failed and was skipped."
  fi
}

cd "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/manage.py" ]; then
  die "manage.py was not found. Run this script from the project repository."
fi

if [ -f "$MARKER_FILE" ]; then
  log "[INFO] Setup already completed on $(cat "$MARKER_FILE")"
  log "[INFO] To start the app:"
  log "       source venv/bin/activate"
  log "       python manage.py runserver"
  exit 0
fi

PYTHON_BIN="$(pick_python)"

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
then
  die "Python 3.9+ is required. Found: $($PYTHON_BIN --version 2>&1)"
fi

log "[INFO] Using $($PYTHON_BIN --version 2>&1)"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  run_required "Creating virtual environment" "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"

run_required "Upgrading pip tooling" "$VENV_PY" -m pip install --upgrade pip setuptools wheel

log "[STEP] Installing dependencies from requirements.txt"
if ! "$VENV_PY" -m pip install -r "$PROJECT_DIR/requirements.txt"; then
  warn "requirements install failed. Retrying without psycopg2-binary for local SQLite setup."
  TMP_REQ="$(mktemp "${TMPDIR:-/tmp}/sensore-req.XXXXXX")"
  grep -Evi '^\s*psycopg2-binary' "$PROJECT_DIR/requirements.txt" > "$TMP_REQ"
  "$VENV_PY" -m pip install -r "$TMP_REQ"
  rm -f "$TMP_REQ"
fi

run_required "Applying database migrations" "$VENV_PY" "$PROJECT_DIR/manage.py" migrate --noinput
run_required "Running Django startup checks" "$VENV_PY" "$PROJECT_DIR/manage.py" check

SEED_MODE="none"
if "$VENV_PY" "$PROJECT_DIR/manage.py" help load_sample_data >/dev/null 2>&1; then
  SEED_MODE="legacy"
  run_optional "Loading demo users and sessions" "$VENV_PY" "$PROJECT_DIR/manage.py" load_sample_data
elif "$VENV_PY" "$PROJECT_DIR/manage.py" help seed_curated_demo_data >/dev/null 2>&1; then
  SEED_MODE="core_curated"
  run_optional "Seeding curated demo data" "$VENV_PY" "$PROJECT_DIR/manage.py" seed_curated_demo_data
elif "$VENV_PY" "$PROJECT_DIR/manage.py" help seed_mass_test_data >/dev/null 2>&1; then
  SEED_MODE="core_mass"
  run_optional "Seeding mass test data" "$VENV_PY" "$PROJECT_DIR/manage.py" seed_mass_test_data
else
  warn "No supported seed command was found."
fi

REAL_CSV="$PROJECT_DIR/sample_data/de0e9b2c_20251013.csv"
if "$VENV_PY" "$PROJECT_DIR/manage.py" help import_real_csv >/dev/null 2>&1; then
  if [ -f "$REAL_CSV" ]; then
    run_optional "Importing real hardware CSV" "$VENV_PY" "$PROJECT_DIR/manage.py" import_real_csv --path "$REAL_CSV"
  else
    warn "Real CSV not found at sample_data/de0e9b2c_20251013.csv."
  fi
else
  log "[INFO] Real CSV import command is not available in this project configuration."
fi

if [ -f "$PROJECT_DIR/generate_sample_csvs.py" ]; then
  run_optional "Generating extra sample CSV files" "$VENV_PY" "$PROJECT_DIR/generate_sample_csvs.py"
fi

date '+%Y-%m-%d %H:%M:%S %Z' > "$MARKER_FILE"

log ""
log "[OK] Setup complete."
log "[INFO] Start the app with:"
log "       source venv/bin/activate"
log "       python manage.py runserver"
log "[INFO] Open: http://127.0.0.1:8000"
log ""
log "Login hints:"
log "  Admin: admin / admin123"
if [ "$SEED_MODE" = "legacy" ]; then
  log "  Clinician: dr_smith / clinic123"
  log "  Patient: patient_001 / patient123"
elif [ "$SEED_MODE" = "core_curated" ]; then
  log "  Clinician: clinician1 / clinician123"
  log "  Patient: patient1 / patient123"
elif [ "$SEED_MODE" = "core_mass" ]; then
  log "  Clinician: clinician1 / clinician123"
  log "  Patient: patient1 / patient123"
else
  log "  Seed users were not auto-created."
fi
