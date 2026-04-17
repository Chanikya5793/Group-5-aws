"""
CSV upload handler for Sensore pressure mat data.

Supported formats
-----------------
Format A (standard — used by real Sensore hardware):
    32 consecutive rows × 32 columns = one frame.

Format B (compact):
    Each row = 1024 comma-separated values (one complete frame).

Scale handling
--------------
The system stores data in a 0-4095 internal scale.  Real hardware may output
a compressed range (e.g. 0-705).  The parser finds the global maximum across
the entire file and scales all frames consistently so relative pressures
between frames are preserved.

Filename convention (auto-parsed for session date):
    <sensor_id>_<YYYYMMDD>.csv   e.g.  de0e9b2c_20251013.csv
"""
import csv
import io
import json
import os
import re
from datetime import date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.models import UserProfile
from sensore.models import SensorFrame, SensorSession
from sensore.utils import (analyse_frame, generate_session_alerts,
                           normalise_frame, parse_frame_data)
from sensore.views import get_user_role

# ── FILENAME HINT PARSER ─────────────────────────────────────────────────────

def parse_filename_hints(filename):
    """
    Extract a sensor/patient ID and session date from the filename.
    Pattern recognised:  <id>_<YYYYMMDD>.csv
    Returns (id_hint: str|None, session_date: date)
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = re.match(r'^(.+)_(\d{8})$', stem)
    if m:
        try:
            return m.group(1), datetime.strptime(m.group(2), '%Y%m%d').date()
        except ValueError:
            pass
    return None, date.today()


# ── CSV PARSER ────────────────────────────────────────────────────────────────

def parse_sensore_csv(file_obj):
    """
    Parse a Sensore CSV and return a list of normalised frames.

    Each frame is a list of 1024 integers scaled to 0-4095 using the
    file's global maximum (so relative pressures across frames are preserved).
    """
    text = file_obj.read().decode('utf-8', errors='replace')
    reader = csv.reader(io.StringIO(text))

    rows = []
    for row in reader:
        if not row or row[0].strip().startswith('#'):
            continue
        try:
            vals = [int(float(v)) for v in row if v.strip()]
            if vals:
                rows.append(vals)
        except ValueError:
            continue   # skip header / non-numeric lines

    if not rows:
        return []

    # Assemble raw frames (before normalisation)
    frames_raw = []

    if len(rows[0]) >= 1024:
        # Format B: one frame per row
        for row in rows:
            frames_raw.append(row[:1024])
    elif len(rows[0]) == 32:
        # Format A: 32 rows per frame
        i = 0
        while i + 32 <= len(rows):
            flat = []
            for r in rows[i:i + 32]:
                flat.extend(r[:32])
            if len(flat) == 1024:
                frames_raw.append(flat)
            i += 32
    else:
        # Fallback: flatten everything and split into 1024-value chunks
        flat_all = [v for row in rows for v in row]
        for i in range(0, len(flat_all) - 1023, 1024):
            frames_raw.append(flat_all[i:i + 1024])

    if not frames_raw:
        return []

    # Find global maximum across the ENTIRE file so all frames share the
    # same scale — preserving relative pressures between frames.
    global_max = max(max(f) for f in frames_raw)

    return [normalise_frame(f, global_max=global_max) for f in frames_raw]


# ── VIEW ─────────────────────────────────────────────────────────────────────

@login_required
def upload_csv(request):
    """Handle CSV upload for a patient session."""
    user = request.user
    role = get_user_role(user)

    target_patient = user
    if role in ('clinician', 'admin') and request.method == 'POST':
        pid = request.POST.get('patient_id')
        if pid:
            try:
                target_patient = User.objects.get(id=int(pid))
            except (User.DoesNotExist, ValueError):
                pass

    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        session_date_str = request.POST.get('session_date', '')
        session_notes    = request.POST.get('notes', '')

        if not csv_file:
            messages.error(request, 'No file uploaded.')
            return redirect('upload_csv')

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, 'Please upload a .csv file.')
            return redirect('upload_csv')

        # Auto-detect date from filename
        pid_hint, auto_date = parse_filename_hints(csv_file.name)
        try:
            session_date = datetime.strptime(session_date_str, '%Y-%m-%d').date()
        except ValueError:
            session_date = auto_date

        # Parse + normalise
        try:
            frames_data = parse_sensore_csv(csv_file)
        except Exception as e:
            messages.error(request, f'Failed to parse CSV: {e}')
            return redirect('upload_csv')

        if not frames_data:
            messages.error(
                request,
                'No valid pressure frames found. '
                'Expected Format A (32 cols × multiple-of-32 rows) '
                'or Format B (1024 values per row).'
            )
            return redirect('upload_csv')

        # Create session
        start_dt = timezone.make_aware(
            datetime(session_date.year, session_date.month, session_date.day, 0, 0, 0)
        )
        notes = session_notes or f'Imported from {csv_file.name}'
        if pid_hint:
            notes += f' (sensor ID: {pid_hint})'

        session = SensorSession.objects.create(
            patient=target_patient,
            session_date=session_date,
            start_time=start_dt,
            notes=notes,
        )

        # Bulk-insert frames at 30 s intervals
        frame_objs = []
        from datetime import timedelta
        for idx, flat in enumerate(frames_data):
            frame_objs.append(SensorFrame(
                session=session,
                timestamp=start_dt + timedelta(seconds=idx * 30),
                frame_index=idx,
                data=json.dumps(flat),
            ))
        SensorFrame.objects.bulk_create(frame_objs)

        # Run pressure analysis with sequential context (movement + sustained load)
        analysed = 0
        sustained_streak = 0
        previous_matrix = None
        for frame in session.frames.order_by('frame_index'):
            try:
                metrics = analyse_frame(
                    frame,
                    previous_matrix=previous_matrix,
                    sustained_streak=sustained_streak,
                )
                analysed += 1

                previous_matrix = parse_frame_data(frame.data)
                if metrics.risk_score >= 60 or metrics.peak_pressure_index >= 2800:
                    sustained_streak += 1
                else:
                    sustained_streak = 0
            except Exception:
                previous_matrix = None
                pass

        alerts_created = generate_session_alerts(session, recreate_unacknowledged=True)

        messages.success(
            request,
            f'Imported {len(frames_data)} frames from "{csv_file.name}" '
            f'(date: {session_date}). Analysis complete for {analysed} frames. '
            f'Generated {alerts_created} active alert(s).'
        )
        return redirect('patient_dashboard')

    # GET — render upload form
    patients = []
    if role in ('clinician', 'admin'):
        try:
            patients = list(UserProfile.objects.filter(role='patient').select_related('user'))
        except Exception:
            pass

    return render(request, 'sensore/upload_csv.html', {
        'role':     role,
        'patients': patients,
        'today':    date.today().isoformat(),
    })
