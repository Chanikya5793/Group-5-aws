import csv
import io
import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserProfile

from .models import (Comment, PressureAlert, PressureMetrics, Report,
                     SensorFrame, SensorSession)
from .utils import analyse_frame, generate_session_report_data, get_risk_level


def get_user_role(user):
    try:
        return user.profile.role
    except UserProfile.DoesNotExist:
        if user.is_superuser or user.is_staff:
            return 'admin'
        return 'patient'
    except Exception:
        return 'patient'


def user_can_access_patient(user, patient):
    """Role-aware access check for patient-linked resources."""
    role = get_user_role(user)

    if role == 'admin':
        return True

    if role == 'patient':
        return patient.id == user.id

    if role == 'clinician':
        try:
            return patient.profile.assigned_clinician_id == user.id
        except Exception:
            return False

    return False


def patient_access_error(user, patient):
    if user_can_access_patient(user, patient):
        return None
    return JsonResponse({'error': 'Forbidden'}, status=403)


def _parse_iso_date(date_str):
    """Parse YYYY-MM-DD date strings safely; return None on invalid values."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None


def _serialize_frame_payload(frame):
    payload = {
        'id': frame.id,
        'frame_index': frame.frame_index,
        'timestamp': frame.timestamp.isoformat(),
        'data': json.loads(frame.data),
    }

    if hasattr(frame, 'metrics'):
        m = frame.metrics
        payload['metrics'] = {
            'ppi': m.peak_pressure_index,
            'contact_area': m.contact_area_percent,
            'avg_pressure': m.average_pressure,
            'asymmetry': m.asymmetry_score,
            'pressure_variability': m.pressure_variability,
            'pressure_concentration': m.pressure_concentration,
            'movement_index': m.movement_index,
            'sustained_load_index': m.sustained_load_index,
            'center_of_pressure_x': m.center_of_pressure_x,
            'center_of_pressure_y': m.center_of_pressure_y,
            'risk_score': m.risk_score,
            'risk_level': m.risk_level,
            'hot_zones': m.get_hot_zones(),
            'plain_english': m.plain_english,
        }

    return payload


@login_required
def dashboard(request):
    role = get_user_role(request.user)
    if role == 'clinician' or role == 'admin':
        return redirect('clinician_dashboard')
    return redirect('patient_dashboard')


# ─── PATIENT VIEWS ────────────────────────────────────────────────────────────

@login_required
def patient_dashboard(request):
    """Main patient dashboard with heatmap, metrics, and comments."""
    user = request.user

    sessions = SensorSession.objects.filter(patient=user).order_by('-session_date', '-start_time')
    latest_session = sessions.first()

    selected_session_id = request.GET.get('session_id')
    if selected_session_id:
        selected_session = get_object_or_404(SensorSession, id=selected_session_id, patient=user)
    else:
        selected_session = latest_session

    alerts = PressureAlert.objects.filter(session__patient=user, acknowledged=False).order_by('-created_at')[:5]

    context = {
        'sessions': sessions[:10],
        'selected_session': selected_session,
        'alerts': alerts,
        'role': 'patient',
    }
    return render(request, 'sensore/patient_dashboard.html', context)


@login_required
def clinician_dashboard(request):
    """Clinician dashboard showing all patient data and risk summaries."""
    role = get_user_role(request.user)
    if role not in ('clinician', 'admin'):
        return redirect('patient_dashboard')

    if role == 'admin':
        patient_users = User.objects.filter(profile__role='patient').order_by('username')
    else:
        patient_users = User.objects.filter(
            profile__role='patient',
            profile__assigned_clinician=request.user,
        ).order_by('username')

    patient_summaries = []
    for patient in patient_users:
        latest_session = SensorSession.objects.filter(patient=patient).order_by('-start_time').first()
        unack_alerts = PressureAlert.objects.filter(session__patient=patient, acknowledged=False).count()
        latest_risk = 'unknown'
        latest_risk_score = 0.0
        latest_high_risk_ratio = 0.0
        latest_session_trend = 'stable'
        if latest_session:
            latest_frame = latest_session.frames.order_by('-timestamp').first()
            if latest_frame and hasattr(latest_frame, 'metrics'):
                latest_risk = latest_frame.metrics.risk_level
                latest_risk_score = latest_frame.metrics.risk_score

            latest_session_data = generate_session_report_data(latest_session)
            if latest_session_data:
                latest_high_risk_ratio = latest_session_data.get('high_risk_ratio', 0.0)
                latest_session_trend = latest_session_data.get('risk_trend', 'stable')

        patient_summaries.append({
            'user': patient,
            'latest_session': latest_session,
            'unack_alerts': unack_alerts,
            'latest_risk': latest_risk,
            'latest_risk_score': latest_risk_score,
            'latest_high_risk_ratio': latest_high_risk_ratio,
            'latest_session_trend': latest_session_trend,
        })

    patient_summaries.sort(
        key=lambda item: (item.get('latest_risk_score', 0.0), item.get('unack_alerts', 0)),
        reverse=True,
    )

    all_alerts_qs = PressureAlert.objects.filter(acknowledged=False)
    if role == 'clinician':
        all_alerts_qs = all_alerts_qs.filter(
            session__patient__profile__assigned_clinician=request.user
        )
    all_alerts = all_alerts_qs.order_by('-created_at')[:10]

    context = {
        'patient_summaries': patient_summaries,
        'all_alerts': all_alerts,
        'role': role,
    }
    return render(request, 'sensore/clinician_dashboard.html', context)


# ─── API ENDPOINTS ─────────────────────────────────────────────────────────────

@login_required
@require_GET
def api_session_frames(request, session_id):
    """Return a session frame window with metrics.

    Query parameters:
      - limit=<int>: return the latest N frames (default: 1200, max: 5000)
      - limit=all: return the full session
    """
    session = get_object_or_404(SensorSession, id=session_id)

    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    total_frames = session.frames.count()
    default_limit = 1200
    max_limit = 5000

    limit_param = (request.GET.get('limit') or '').strip().lower()
    if limit_param in {'all', 'full'}:
        start_index = 0
        end_index = total_frames
    else:
        try:
            requested_limit = int(limit_param) if limit_param else default_limit
        except ValueError:
            requested_limit = default_limit
        requested_limit = max(1, min(requested_limit, max_limit))
        start_index = max(0, total_frames - requested_limit)
        end_index = total_frames

    frames_data = []
    frames_qs = (
        session.frames
        .select_related('metrics')
        .order_by('frame_index')[start_index:end_index]
    )

    for frame in frames_qs:
        frames_data.append(_serialize_frame_payload(frame))

    first_frame_index = frames_data[0]['frame_index'] if frames_data else None
    last_frame_index = frames_data[-1]['frame_index'] if frames_data else None

    return JsonResponse({
        'frames': frames_data,
        'session_id': session_id,
        'total_frames': total_frames,
        'returned_frames': len(frames_data),
        'first_frame_index': first_frame_index,
        'last_frame_index': last_frame_index,
        'truncated': start_index > 0,
    })


@login_required
@require_GET
def api_latest_frame(request, session_id):
    """Return the latest frame with full metrics."""
    session = get_object_or_404(SensorSession, id=session_id)
    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    frame = session.frames.order_by('-frame_index').first()
    if not frame:
        return JsonResponse({'error': 'No frames'}, status=404)

    data = _serialize_frame_payload(frame)
    return JsonResponse(data)


@login_required
@require_GET
def api_frame_detail(request, frame_id):
    """Return a specific frame with full metrics."""
    frame = get_object_or_404(SensorFrame, id=frame_id)
    session = frame.session

    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    data = _serialize_frame_payload(frame)
    return JsonResponse(data)


@login_required
@require_GET
def api_session_metrics_timeline(request, session_id):
    """Return timeline of metrics for charts."""
    session = get_object_or_404(SensorSession, id=session_id)
    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    report_data = generate_session_report_data(session)
    return JsonResponse(report_data)


@login_required
def api_add_comment(request, session_id):
    """Add a comment to a session at a specific timestamp."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    session = get_object_or_404(SensorSession, id=session_id)

    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        body = request.POST

    text = body.get('text', '').strip()
    frame_id = body.get('frame_id')
    timestamp_str = body.get('timestamp')

    if not text:
        return JsonResponse({'error': 'Comment text required'}, status=400)

    frame = None
    if frame_id:
        try:
            frame = SensorFrame.objects.get(id=frame_id, session=session)
        except SensorFrame.DoesNotExist:
            pass

    ref_time = timezone.now()
    if timestamp_str:
        try:
            ref_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if timezone.is_naive(ref_time):
                ref_time = timezone.make_aware(ref_time, timezone.get_current_timezone())
        except Exception:
            pass
    elif frame:
        ref_time = frame.timestamp

    role = get_user_role(request.user)
    comment = Comment.objects.create(
        session=session,
        author=request.user,
        author_type=role if role in ('patient', 'clinician') else 'clinician',
        frame=frame,
        timestamp_reference=ref_time,
        text=text,
    )

    return JsonResponse({
        'id': comment.id,
        'author': request.user.get_full_name() or request.user.username,
        'author_type': comment.author_type,
        'text': comment.text,
        'timestamp': comment.timestamp_reference.isoformat(),
        'created_at': comment.created_at.isoformat(),
        'frame_id': comment.frame_id,
        'frame_index': comment.frame.frame_index if comment.frame else None,
    })


@login_required
@require_GET
def api_session_comments(request, session_id):
    """Return all comments for a session."""
    session = get_object_or_404(SensorSession, id=session_id)
    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    comments = Comment.objects.filter(session=session, is_reply=False).order_by('created_at')
    data = []
    for c in comments:
        replies = Comment.objects.filter(reply_to=c).order_by('created_at')
        data.append({
            'id': c.id,
            'author': c.author.get_full_name() or c.author.username,
            'author_type': c.author_type,
            'text': c.text,
            'timestamp': c.timestamp_reference.isoformat(),
            'created_at': c.created_at.isoformat(),
            'frame_id': c.frame_id,
            'frame_index': c.frame.frame_index if c.frame else None,
            'replies': [{
                'id': r.id,
                'author': r.author.get_full_name() or r.author.username,
                'author_type': r.author_type,
                'text': r.text,
                'created_at': r.created_at.isoformat(),
            } for r in replies],
        })
    return JsonResponse({'comments': data})


@login_required
def api_acknowledge_alert(request, alert_id):
    """Mark an alert as acknowledged."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    alert = get_object_or_404(PressureAlert, id=alert_id)
    access_error = patient_access_error(request.user, alert.session.patient)
    if access_error:
        return access_error

    alert.acknowledged = True
    alert.acknowledged_by = request.user
    alert.save()
    return JsonResponse({'status': 'acknowledged'})


@login_required
def patient_report(request, patient_id=None):
    """View and generate a downloadable medical history report."""
    if patient_id:
        patient = get_object_or_404(User, id=patient_id)
    else:
        patient = request.user

    if not user_can_access_patient(request.user, patient):
        return HttpResponseForbidden('Forbidden')

    sessions = SensorSession.objects.filter(patient=patient).order_by('-session_date', '-start_time')

    start_date = _parse_iso_date(request.GET.get('start_date'))
    end_date = _parse_iso_date(request.GET.get('end_date'))
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    if start_date:
        sessions = sessions.filter(session_date__gte=start_date)
    if end_date:
        sessions = sessions.filter(session_date__lte=end_date)

    # Build per-session summaries
    session_summaries = []
    weighted_sum_ppi = 0.0
    weighted_sum_risk = 0.0
    weighted_sum_area = 0.0
    weighted_sum_movement = 0.0
    weighted_sum_variability = 0.0
    total_frames = 0
    total_high_risk = 0
    trend_counts = {'improving': 0, 'worsening': 0, 'stable': 0}

    for session in sessions:
        report_data = generate_session_report_data(session)
        if report_data:
            session_summaries.append({
                'session': session,
                'data': report_data,
            })

            frame_count = report_data.get('frame_count', 0)
            total_frames += frame_count
            weighted_sum_ppi += report_data.get('avg_ppi', 0.0) * frame_count
            weighted_sum_risk += report_data.get('avg_risk_score', 0.0) * frame_count
            weighted_sum_area += report_data.get('avg_contact_area', 0.0) * frame_count
            weighted_sum_movement += report_data.get('avg_movement_index', 0.0) * frame_count
            weighted_sum_variability += report_data.get('avg_pressure_variability', 0.0) * frame_count

            total_high_risk += report_data.get('high_risk_events', 0)

            trend = report_data.get('risk_trend', 'stable')
            if trend in trend_counts:
                trend_counts[trend] += 1

    avg_ppi = round(weighted_sum_ppi / total_frames, 1) if total_frames else 0
    avg_risk = round(weighted_sum_risk / total_frames, 1) if total_frames else 0
    avg_area = round(weighted_sum_area / total_frames, 1) if total_frames else 0
    avg_movement = round(weighted_sum_movement / total_frames, 1) if total_frames else 0
    avg_variability = round(weighted_sum_variability / total_frames, 1) if total_frames else 0

    overall_trend = max(trend_counts, key=trend_counts.get) if session_summaries else 'stable'

    download_mode = (request.GET.get('download') or '').strip().lower()
    format_mode = (request.GET.get('format') or '').strip().lower()

    context = {
        'patient': patient,
        'session_summaries': session_summaries,
        'avg_ppi': avg_ppi,
        'avg_risk': avg_risk,
        'avg_area': avg_area,
        'avg_movement': avg_movement,
        'avg_variability': avg_variability,
        'total_high_risk': total_high_risk,
        'overall_risk_level': get_risk_level(avg_risk),
        'overall_trend': overall_trend,
        'total_frames': total_frames,
        'total_sessions': len(session_summaries),
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': timezone.now(),
    }

    if download_mode in {'1', 'pdf', 'true'}:
        return generate_pdf_report(context)

    if download_mode == 'csv' or format_mode == 'csv':
        return generate_csv_report(context)

    return render(request, 'sensore/report.html', context)


def generate_pdf_report(context):
    """Generate a PDF report using reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm, mm
        from reportlab.platypus import (HRFlowable, Paragraph,
                                        SimpleDocTemplate, Spacer, Table,
                                        TableStyle)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                                leftMargin=2*cm, rightMargin=2*cm)

        patient = context['patient']
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle('Title', fontName='Helvetica-Bold', fontSize=20,
                                     spaceAfter=6, textColor=colors.HexColor('#0a1628'))
        subtitle_style = ParagraphStyle('Subtitle', fontName='Helvetica', fontSize=11,
                                        spaceAfter=3, textColor=colors.HexColor('#5a7a9a'))
        body_style = ParagraphStyle('Body', fontName='Helvetica', fontSize=10, spaceAfter=4)
        heading_style = ParagraphStyle('Heading', fontName='Helvetica-Bold', fontSize=13,
                                       spaceBefore=12, spaceAfter=6, textColor=colors.HexColor('#1a3a5c'))

        story.append(Paragraph("SENSORE — Pressure Mapping Report", title_style))
        story.append(Paragraph(f"Graphene Trace Medical Platform", subtitle_style))
        story.append(Paragraph(f"Generated: {context['generated_at'].strftime('%d %B %Y, %H:%M UTC')}", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#00d4c8')))
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("Patient Information", heading_style))
        patient_data = [
            ['Name:', patient.get_full_name() or patient.username],
            ['Username:', patient.username],
            ['Email:', patient.email or 'N/A'],
        ]
        try:
            profile = patient.profile
            if profile.patient_id:
                patient_data.append(['Patient ID:', profile.patient_id])
            if profile.date_of_birth:
                patient_data.append(['Date of Birth:', str(profile.date_of_birth)])
        except Exception:
            pass
        pt = Table(patient_data, colWidths=[4*cm, 12*cm])
        pt.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1a3a5c')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(pt)
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("Summary Metrics", heading_style))
        risk_color = {'low': '#22c55e', 'moderate': '#f59e0b', 'high': '#ef4444', 'critical': '#7c3aed'}
        rl = context['overall_risk_level']
        summary_data = [
            ['Metric', 'Value'],
            ['Average Peak Pressure Index', f"{context['avg_ppi']} / 4095"],
            ['Average Contact Area', f"{context['avg_area']}%"],
            ['Average Risk Score', f"{context['avg_risk']} / 100"],
            ['Average Movement Index', f"{context['avg_movement']} / 100"],
            ['Average Variability', f"{context['avg_variability']}%"],
            ['Total High/Critical Risk Events', str(context['total_high_risk'])],
            ['Overall Risk Level', rl.upper()],
            ['Overall Trend', context['overall_trend'].upper()],
        ]
        st = Table(summary_data, colWidths=[10*cm, 6*cm])
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f0f4f8'), colors.white]),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0dce8')),
        ]))
        story.append(st)
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("Session History", heading_style))
        if context['session_summaries']:
            session_header = ['Date', 'Frames', 'Avg PPI', 'Contact Area', 'Risk Score', 'Peak Risk']
            session_rows = [session_header]
            for ss in context['session_summaries']:
                s = ss['session']
                d = ss['data']
                session_rows.append([
                    str(s.session_date),
                    str(d.get('frame_count', 0)),
                    str(d.get('avg_ppi', 0)),
                    f"{d.get('avg_contact_area', 0)}%",
                    str(d.get('avg_risk_score', 0)),
                    d.get('peak_risk_level', 'N/A').upper(),
                ])
            sst = Table(session_rows, colWidths=[3*cm, 2.5*cm, 3*cm, 3*cm, 3*cm, 2.5*cm])
            sst.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f2744')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f0f4f8'), colors.white]),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0dce8')),
            ]))
            story.append(sst)
        else:
            story.append(Paragraph("No session data available.", body_style))

        story.append(Spacer(1, 0.6*cm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#d0dce8')))
        footer = ParagraphStyle('Footer', fontName='Helvetica', fontSize=8,
                                textColor=colors.HexColor('#8a9ab0'), alignment=TA_CENTER)
        story.append(Paragraph(
            "This report is generated automatically by the Sensore platform (Graphene Trace). "
            "For clinical decisions, consult your assigned clinician.", footer))

        doc.build(story)
        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type='application/pdf')
        patient_name = (patient.get_full_name() or patient.username).replace(' ', '_')
        response['Content-Disposition'] = f'attachment; filename="Sensore_Report_{patient_name}.pdf"'
        return response

    except ImportError:
        return HttpResponse("PDF generation requires reportlab. Install it with: pip install reportlab",
                            content_type='text/plain', status=500)


def generate_csv_report(context):
    """Generate a structured CSV report for offline records."""
    patient = context['patient']

    response = HttpResponse(content_type='text/csv')
    patient_name = (patient.get_full_name() or patient.username).replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="Sensore_Report_{patient_name}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Sensore Medical History Export'])
    writer.writerow(['Generated At', context['generated_at'].isoformat()])
    writer.writerow(['Patient Username', patient.username])
    writer.writerow(['Patient Name', patient.get_full_name() or patient.username])
    writer.writerow(['Overall Risk Level', context['overall_risk_level']])
    writer.writerow(['Overall Trend', context['overall_trend']])
    writer.writerow(['Average PPI', context['avg_ppi']])
    writer.writerow(['Average Contact Area (%)', context['avg_area']])
    writer.writerow(['Average Risk Score', context['avg_risk']])
    writer.writerow(['Average Movement Index', context['avg_movement']])
    writer.writerow(['Average Variability (%)', context['avg_variability']])
    writer.writerow(['Total High/Critical Events', context['total_high_risk']])
    writer.writerow([])

    writer.writerow([
        'Session Date',
        'Start Time',
        'Frame Count',
        'Avg PPI',
        'Avg Contact Area (%)',
        'Avg Risk Score',
        'Avg Movement Index',
        'Avg Variability (%)',
        'High-Risk Events',
        'High-Risk Ratio (%)',
        'Peak Risk Level',
        'Risk Trend',
        'Flagged For Review',
    ])

    for item in context['session_summaries']:
        session = item['session']
        data = item['data']
        writer.writerow([
            session.session_date,
            session.start_time.isoformat() if session.start_time else '',
            data.get('frame_count', 0),
            data.get('avg_ppi', 0),
            data.get('avg_contact_area', 0),
            data.get('avg_risk_score', 0),
            data.get('avg_movement_index', 0),
            data.get('avg_pressure_variability', 0),
            data.get('high_risk_events', 0),
            data.get('high_risk_ratio', 0),
            data.get('peak_risk_level', ''),
            data.get('risk_trend', 'stable'),
            'yes' if session.flagged_for_review else 'no',
        ])

    return response


@login_required
@require_GET
def api_patient_sessions(request, patient_id):
    """Return sessions for a patient (clinician use)."""
    patient = get_object_or_404(User, id=patient_id)
    access_error = patient_access_error(request.user, patient)
    if access_error:
        return access_error

    sessions = SensorSession.objects.filter(patient=patient).order_by('-session_date', '-start_time')[:20]
    data = []
    for s in sessions:
        summary = generate_session_report_data(s)
        data.append({
            'id': s.id,
            'date': str(s.session_date),
            'start_time': s.start_time.isoformat(),
            'frame_count': s.frame_count,
            'flagged': s.flagged_for_review,
            'avg_risk_score': summary.get('avg_risk_score', 0),
            'high_risk_events': summary.get('high_risk_events', 0),
            'high_risk_ratio': summary.get('high_risk_ratio', 0),
            'risk_trend': summary.get('risk_trend', 'stable'),
        })
    return JsonResponse({'sessions': data})

@login_required
def api_reply_comment(request, comment_id):
    """Clinician replies to a patient comment."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    role = get_user_role(request.user)
    if role not in ('clinician', 'admin'):
        return JsonResponse({'error': 'Only clinicians can reply'}, status=403)

    parent = get_object_or_404(Comment, id=comment_id)
    access_error = patient_access_error(request.user, parent.session.patient)
    if access_error:
        return access_error

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        body = request.POST

    text = body.get('text', '').strip()
    if not text:
        return JsonResponse({'error': 'Reply text required'}, status=400)

    reply = Comment.objects.create(
        session=parent.session,
        author=request.user,
        author_type='clinician',
        frame=parent.frame,
        timestamp_reference=parent.timestamp_reference,
        text=text,
        is_reply=True,
        reply_to=parent,
    )
    return JsonResponse({
        'id': reply.id,
        'author': request.user.get_full_name() or request.user.username,
        'author_type': 'clinician',
        'text': reply.text,
        'created_at': reply.created_at.isoformat(),
    })


@login_required
def api_flag_session(request, session_id):
    """Clinician flags a session for review."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    if get_user_role(request.user) not in ('clinician', 'admin'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    session = get_object_or_404(SensorSession, id=session_id)
    access_error = patient_access_error(request.user, session.patient)
    if access_error:
        return access_error

    session.flagged_for_review = not session.flagged_for_review
    session.save()
    return JsonResponse({'flagged': session.flagged_for_review})
