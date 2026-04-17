# Sensore (Group-5-aws)

Sensore is a Django-based pressure monitoring platform for patients and clinicians.
It provides live heatmaps, automatic pressure-risk scoring, timestamped notes, and downloadable PDF medical history reports.

## Implemented User Flows

1. Patient live sitting heatmap with timeline scrubber
2. Patient plain-English explanation of pressure data
3. Patient timestamped comments linked to frame/time
4. Patient and clinician report view plus PDF download
5. Clinician automatic risk overview and alert handling

## Technology

- Django 4.2
- SQLite by default (PostgreSQL via environment variables)
- NumPy/SciPy for pressure analytics
- ReportLab for PDF generation
- Chart.js for timeline visualization

## Project Layout

```text
manage.py
sensore_project/
  settings.py
  urls.py
  wsgi.py
accounts/
  models.py
  views.py
  urls.py
sensore/
  models.py
  views.py
  urls.py
  csv_upload.py
  utils.py
  management/commands/
templates/
  accounts/login.html
  sensore/*.html
```

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies.
3. Run migrations.
4. Load sample data.
5. Start the server.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_sample_data
python manage.py runserver
```

If you explicitly set `DJANGO_DEBUG`, use `DJANGO_DEBUG=True` for local HTTP development mode.

By default, `python manage.py runserver` now runs in local debug mode when
`DJANGO_DEBUG` is not set, so it works with `http://127.0.0.1:8000` out of the box.
Set `DJANGO_DEBUG=False` only when you intentionally want production-style security behavior.

Windows:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_sample_data
python manage.py runserver
```

## Demo Credentials

- Admin: admin / admin123
- Clinician: dr_smith / clinic123
- Patient: patient_001 / patient123

## Main Routes

- Login: /accounts/login/
- Patient dashboard: /patient/
- Clinician dashboard: /clinician/
- Upload CSV: /upload/
- Report: /report/

## Management Commands

- Load synthetic demo data:
  - python manage.py load_sample_data
- Import bundled real CSV session:
  - python manage.py import_real_csv --path sample_data/de0e9b2c_20251013.csv

## Validation Commands

Run these before pushing:

```bash
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py test -v 2
python docs/validate_hasitha_tasks.py
python test_auth.py
python test_login.py
```

## Production Configuration

The active settings module is sensore_project.settings.

Important environment variables:

- DJANGO_SECRET_KEY
- DJANGO_DEBUG (set False in production)
- DJANGO_ALLOWED_HOSTS (comma-separated)
- DJANGO_CSRF_TRUSTED_ORIGINS (comma-separated https origins)

Optional PostgreSQL variables:

- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- POSTGRES_HOST
- POSTGRES_PORT

Security defaults are production-safe when DJANGO_DEBUG=False, including HSTS, HTTPS redirect, and secure cookies.
