
#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Sensore — Graphene Trace  ·  Setup Script
#  Run once after cloning to create the environment and seed data.
# ═══════════════════════════════════════════════════════════════
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗"
echo -e "  ║          SENSORE — Graphene Trace                    ║"
echo -e "  ║      Pressure Ulcer Prevention Platform              ║"
echo -e "  ╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# 1. Python check
if ! python3 --version &>/dev/null; then
  echo -e "${RED}ERROR: Python 3 is required.${NC}"
  echo "  Install from https://python.org (3.10+ recommended)"
  exit 1
fi
echo -e "${GREEN}✓${NC} $(python3 --version)"

# 2. Virtual environment
if [ ! -d "venv" ]; then
  echo "→ Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate
echo -e "${GREEN}✓${NC} Virtual environment active"

# 3. Install dependencies
echo "→ Installing dependencies from requirements.txt..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓${NC} Dependencies installed"

# 4. Apply migrations
echo "→ Applying database migrations..."
python manage.py makemigrations --check --dry-run >/dev/null
python manage.py migrate --no-input
echo -e "${GREEN}✓${NC} Database ready"

# 5. Load synthetic demo data (5 patients, 3 sessions each)
echo "→ Loading synthetic demo data..."
python manage.py load_sample_data
echo -e "${GREEN}✓${NC} Demo data loaded"

# 6. Import real Sensore CSV (de0e9b2c_20251013.csv)
REAL_CSV="sample_data/de0e9b2c_20251013.csv"
REAL_LOGIN_AVAILABLE=0
if [ -f "$REAL_CSV" ]; then
  echo "→ Importing real Sensore hardware CSV (4,190 frames — this takes ~60 s)..."
  python manage.py import_real_csv --path "$REAL_CSV"
  echo -e "${GREEN}✓${NC} Real session imported"
  REAL_LOGIN_AVAILABLE=1
else
  echo -e "${YELLOW}⚠  Real CSV not found at $REAL_CSV${NC}"
  echo "   Copy de0e9b2c_20251013.csv into sample_data/ and run:"
  echo "   python manage.py import_real_csv"
fi

# 7. Generate synthetic CSV test files
echo "→ Generating synthetic CSV test files..."
python generate_sample_csvs.py 2>/dev/null || true
echo -e "${GREEN}✓${NC} Sample CSVs written to ./sample_data/"

# 8. Guarantee login credentials (idempotent)
echo "→ Ensuring all demo login credentials are valid..."
python manage.py ensure_demo_logins
echo -e "${GREEN}✓${NC} Login credentials synced"

echo ""
echo -e "${CYAN}  ┌────────────────────────────────────────────────────┐"
echo -e "  │  ✅  Setup complete!  Start the server:             │"
echo -e "  │                                                    │"
echo -e "  │    source venv/bin/activate                        │"
echo -e "  │    python manage.py runserver                      │"
echo -e "  │                                                    │"
echo -e "  │  Then open:  http://127.0.0.1:8000                 │"
echo -e "  │                                                    │"
if [ "$REAL_LOGIN_AVAILABLE" -eq 1 ]; then
  echo -e "  │  Real data login (CSV imported):                    │"
  echo -e "  │    Patient:   de0e9b2c / patient123                │"
  echo -e "  │                                                    │"
else
  echo -e "  │  Real account login (CSV not imported yet):        │"
  echo -e "  │    Patient:   de0e9b2c / patient123                │"
  echo -e "  │                                                    │"
fi
echo -e "  │  Demo logins:                                      │"
echo -e "  │    Patient:   patient_001 / patient123             │"
echo -e "  │    Clinician: dr_smith    / clinic123              │"
echo -e "  │    Admin:     admin       / admin123               │"
echo -e "  └────────────────────────────────────────────────────┘${NC}"
echo ""
