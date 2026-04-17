"""
Sensore pressure analysis utilities.

Internal scale: all stored frame data uses 0-4095 where:
    0    = no contact (pixel below sensor threshold)
    4095 = maximum recorded pressure (saturation)

Real hardware data arriving in compressed ranges (for example 0-705) is
normalised during import using the file's global maximum so relative pressures
between frames are preserved.
"""
import json

import numpy as np

try:
    from scipy import ndimage
except ImportError:  # pragma: no cover - optional runtime dependency
    ndimage = None


# Thresholds calibrated for the 0-4095 sensor scale.
LOWER_THRESHOLD = 100
UPPER_THRESHOLD = 2800
CRITICAL_THRESHOLD = 3500
MIN_ZONE_PIXELS = 10


def normalise_frame(flat_values, global_max=None):
    """Normalise one frame of raw sensor values to the 0-4095 internal scale."""
    arr = [max(0, int(v)) for v in flat_values]
    if not arr:
        return [0] * 1024

    ref_max = global_max if global_max and global_max > 0 else max(arr)
    if ref_max == 0:
        return [0] * 1024

    if ref_max <= 4095:
        scale = 4095.0 / ref_max
        return [min(4095, int(v * scale)) for v in arr]

    return [min(4095, max(0, v)) for v in arr]


def parse_frame_data(data_json):
    """Parse stored JSON frame data into a resilient 32x32 numpy array."""
    try:
        flat = json.loads(data_json)
        if not isinstance(flat, list):
            flat = []
    except Exception:
        flat = []

    normalised = []
    for value in flat:
        try:
            normalised.append(float(value))
        except Exception:
            normalised.append(0.0)

    if len(normalised) < 1024:
        normalised.extend([0.0] * (1024 - len(normalised)))
    elif len(normalised) > 1024:
        normalised = normalised[:1024]

    return np.array(normalised, dtype=np.float32).reshape(32, 32)


def calculate_peak_pressure_index(matrix):
    """Highest pressure excluding very small connected-contact zones."""
    above = (matrix > LOWER_THRESHOLD).astype(np.uint8)

    if ndimage is not None:
        labeled, num_features = ndimage.label(above)
        max_pressure = 0.0
        for label_id in range(1, num_features + 1):
            component = labeled == label_id
            if np.sum(component) >= MIN_ZONE_PIXELS:
                region_max = float(np.max(matrix[component]))
                if region_max > max_pressure:
                    max_pressure = region_max
        if max_pressure > 0:
            return max_pressure

    in_contact = matrix[matrix > LOWER_THRESHOLD]
    return float(np.max(in_contact)) if len(in_contact) >= MIN_ZONE_PIXELS else 0.0


def calculate_contact_area(matrix):
    """Contact area percent: pixels above lower threshold over total pixels."""
    contact_pixels = int(np.sum(matrix > LOWER_THRESHOLD))
    return round((contact_pixels / 1024.0) * 100.0, 1)


def calculate_asymmetry_score(matrix):
    """Left/right asymmetry score in percent (0-100)."""
    left = matrix[:, :16]
    right = matrix[:, 16:]
    left_sum = float(np.sum(left[left > LOWER_THRESHOLD]))
    right_sum = float(np.sum(right[right > LOWER_THRESHOLD]))
    total = left_sum + right_sum
    if total == 0:
        return 0.0
    return round(abs(left_sum - right_sum) / total * 100.0, 1)


def calculate_pressure_variability(matrix):
    """Pressure variability as coefficient-of-variation (%) in contact regions."""
    in_contact = matrix[matrix > LOWER_THRESHOLD]
    if len(in_contact) < 2:
        return 0.0

    mean_val = float(np.mean(in_contact))
    if mean_val <= 0:
        return 0.0

    std_val = float(np.std(in_contact))
    return round(min(100.0, (std_val / mean_val) * 100.0), 1)


def calculate_pressure_concentration(matrix):
    """Localized-load index (0-100) based on top-5% vs mean in-contact pressure."""
    in_contact = matrix[matrix > LOWER_THRESHOLD]
    if len(in_contact) == 0:
        return 0.0

    mean_val = float(np.mean(in_contact))
    if mean_val <= 0:
        return 0.0

    sorted_vals = np.sort(in_contact)
    top_n = max(1, int(len(sorted_vals) * 0.05))
    top_mean = float(np.mean(sorted_vals[-top_n:]))
    ratio = top_mean / mean_val

    concentration = (ratio - 1.0) * 40.0
    return round(min(100.0, max(0.0, concentration)), 1)


def calculate_center_of_pressure(matrix):
    """Center-of-pressure coordinate in sensor grid space (x, y), each 0-31."""
    contact_weights = np.clip(matrix - LOWER_THRESHOLD, 0, None)
    total_weight = float(np.sum(contact_weights))
    if total_weight <= 0:
        return None, None

    ys, xs = np.indices(matrix.shape)
    cop_x = float(np.sum(xs * contact_weights) / total_weight)
    cop_y = float(np.sum(ys * contact_weights) / total_weight)
    return round(cop_x, 2), round(cop_y, 2)


def calculate_movement_index(current_matrix, previous_matrix=None):
    """Frame-to-frame movement intensity index (0-100)."""
    if previous_matrix is None:
        return 0.0

    prev = np.asarray(previous_matrix, dtype=np.float32)
    curr = np.asarray(current_matrix, dtype=np.float32)
    if prev.shape != curr.shape:
        return 0.0

    union_mask = (curr > LOWER_THRESHOLD) | (prev > LOWER_THRESHOLD)
    if not np.any(union_mask):
        return 0.0

    mean_delta = float(np.mean(np.abs(curr[union_mask] - prev[union_mask])))
    return round(min(100.0, (mean_delta / 4095.0) * 100.0), 1)


def calculate_sustained_load_index(streak_frames):
    """Convert sustained high-load streak length to a 0-100 persistence index."""
    streak = max(0, int(streak_frames))
    return round(min(100.0, streak * 12.5), 1)


def find_hot_zones(matrix, top_n=5):
    """Return the top hot zones as {x, y, value, size, mean} entries."""
    hot_zones = []
    high_mask = (matrix >= UPPER_THRESHOLD).astype(np.uint8)

    if ndimage is not None and np.any(high_mask):
        labeled, num_features = ndimage.label(high_mask)
        for label_id in range(1, num_features + 1):
            component = labeled == label_id
            size = int(np.sum(component))
            if size < 4:
                continue

            component_values = matrix[component]
            peak = float(np.max(component_values))
            mean_val = float(np.mean(component_values))

            ys, xs = np.where(component)
            cx = float(np.mean(xs))
            cy = float(np.mean(ys))
            hot_zones.append({
                'x': round(cx, 2),
                'y': round(cy, 2),
                'value': round(peak, 1),
                'size': size,
                'mean': round(mean_val, 1),
            })

    if not hot_zones:
        flat_indices = np.argsort(matrix.flatten())[-top_n:][::-1]
        for idx in flat_indices:
            row = int(idx // 32)
            col = int(idx % 32)
            val = float(matrix[row, col])
            if val > LOWER_THRESHOLD:
                hot_zones.append({
                    'x': float(col),
                    'y': float(row),
                    'value': round(val, 1),
                    'size': 1,
                    'mean': round(val, 1),
                })

    hot_zones.sort(key=lambda zone: zone['value'], reverse=True)
    return hot_zones[:top_n]


def calculate_risk_components(ppi, contact_area, asymmetry, concentration, sustained_load, movement_index=0.0):
    """Return (risk_score, component_breakdown)."""
    if ppi <= LOWER_THRESHOLD:
        ppi_score = 0.0
    elif ppi < UPPER_THRESHOLD:
        ppi_score = ((ppi - LOWER_THRESHOLD) / (UPPER_THRESHOLD - LOWER_THRESHOLD)) * 28.0
    else:
        ppi_score = 28.0 + ((min(ppi, 4095.0) - UPPER_THRESHOLD) / (4095.0 - UPPER_THRESHOLD)) * 32.0
    ppi_score = min(60.0, max(0.0, ppi_score))

    asymmetry_score = min(12.0, (asymmetry / 100.0) * 12.0)
    concentration_score = min(12.0, (concentration / 100.0) * 12.0)

    if contact_area < 12:
        area_score = 12.0
    elif contact_area < 25:
        area_score = 8.0
    elif contact_area <= 65:
        area_score = 4.0
    elif contact_area <= 82:
        area_score = 7.0
    else:
        area_score = 10.0

    sustained_score = min(16.0, (sustained_load / 100.0) * 16.0)

    # Movement can be protective when pressure is not yet severe.
    movement_modifier = -2.0 if movement_index >= 12.0 and ppi < UPPER_THRESHOLD else 0.0

    total = ppi_score + asymmetry_score + concentration_score + area_score + sustained_score + movement_modifier
    total = round(min(100.0, max(0.0, total)), 1)

    return total, {
        'ppi': round(ppi_score, 1),
        'asymmetry': round(asymmetry_score, 1),
        'concentration': round(concentration_score, 1),
        'contact_area': round(area_score, 1),
        'sustained': round(sustained_score, 1),
        'movement_modifier': round(movement_modifier, 1),
    }


def calculate_risk_score(ppi, contact_area, asymmetry, concentration=0.0, sustained_load=0.0, movement_index=0.0):
    """Backward-compatible risk score helper returning only the score value."""
    score, _ = calculate_risk_components(
        ppi=ppi,
        contact_area=contact_area,
        asymmetry=asymmetry,
        concentration=concentration,
        sustained_load=sustained_load,
        movement_index=movement_index,
    )
    return score


def get_risk_level(risk_score):
    if risk_score < 30:
        return 'low'
    if risk_score < 55:
        return 'moderate'
    if risk_score < 78:
        return 'high'
    return 'critical'


def _describe_center_of_pressure(cop_x, cop_y):
    if cop_x is None or cop_y is None:
        return "Contact is very limited, so center-of-pressure position is not reliable for this frame."

    if cop_x < 13:
        horizontal = "left"
    elif cop_x > 19:
        horizontal = "right"
    else:
        horizontal = "center"

    if cop_y < 11:
        vertical = "front"
    elif cop_y > 21:
        vertical = "rear"
    else:
        vertical = "middle"

    if horizontal == "center" and vertical == "middle":
        return "Your center of pressure is near the middle of the seat, indicating a balanced posture."

    return (
        f"Your center of pressure is shifted toward the {vertical}-{horizontal} area, "
        "which indicates uneven loading in that direction."
    )


def generate_plain_english(
    ppi,
    contact_area,
    asymmetry,
    risk_level,
    risk_score,
    pressure_variability=0.0,
    movement_index=0.0,
    concentration=0.0,
    sustained_load=0.0,
    center_of_pressure=None,
):
    """Patient-friendly explanation of a single pressure frame."""
    ppi_pct = round((ppi / 4095.0) * 100.0, 0)

    if ppi_pct < 30:
        pressure_msg = "Peak pressure is low, which suggests gentle and broadly distributed contact."
    elif ppi_pct < 60:
        pressure_msg = (
            f"Peak pressure is moderate ({ppi_pct:.0f}% of maximum). "
            "Some zones are carrying more load than others."
        )
    elif ppi_pct < 80:
        pressure_msg = (
            f"Peak pressure is high ({ppi_pct:.0f}% of maximum). "
            "Maintaining this load for long periods may reduce tissue tolerance."
        )
    else:
        pressure_msg = (
            f"Peak pressure is very high ({ppi_pct:.0f}% of maximum). "
            "Repositioning is recommended as soon as possible."
        )

    if contact_area < 15:
        area_msg = "Contact area is small, meaning pressure is concentrated in limited zones."
    elif contact_area < 40:
        area_msg = f"Contact area is moderate at {contact_area:.1f}% of the mat surface."
    else:
        area_msg = f"Contact area is broad at {contact_area:.1f}%, which usually helps pressure distribution."

    if asymmetry < 20:
        asym_msg = "Left-right distribution is balanced."
    elif asymmetry < 40:
        asym_msg = f"There is mild side-to-side imbalance ({asymmetry:.1f}%)."
    else:
        asym_msg = f"There is notable side-to-side imbalance ({asymmetry:.1f}%), which increases localized risk."

    if movement_index < 4:
        movement_msg = "Movement is minimal, suggesting a static posture in this time window."
    elif movement_index < 12:
        movement_msg = "Movement is moderate, indicating regular posture adjustments."
    else:
        movement_msg = "Movement is high, indicating active repositioning behavior."

    concentration_msg = (
        "Pressure concentration is low."
        if concentration < 25
        else "Pressure concentration is elevated, with load focused in smaller high-pressure zones."
    )

    sustained_msg = (
        "No sustained high-load pattern is currently detected."
        if sustained_load < 25
        else "Sustained high-load exposure is building and should be monitored closely."
    )

    cop_x, cop_y = (center_of_pressure or (None, None))
    cop_msg = _describe_center_of_pressure(cop_x, cop_y)

    recommendations = {
        'low': "Overall: low immediate risk. Continue periodic posture changes.",
        'moderate': "Overall: moderate risk. A small shift every few minutes can improve distribution.",
        'high': "Overall: high risk. Reposition soon and monitor for recurring hotspots.",
        'critical': "Overall: critical risk. Reposition immediately and contact your clinician if this pattern persists.",
    }

    return (
        f"Current risk score: {risk_score:.0f}/100 ({risk_level}).\n\n"
        f"{pressure_msg}\n"
        f"{area_msg}\n"
        f"{asym_msg}\n"
        f"{movement_msg}\n"
        f"{concentration_msg}\n"
        f"{sustained_msg}\n"
        f"{cop_msg}\n\n"
        f"{recommendations.get(risk_level, '')}"
    )


def analyse_frame(frame_obj, previous_matrix=None, sustained_streak=0):
    """Run full per-frame analysis and persist metrics."""
    from .models import PressureMetrics

    matrix_raw = parse_frame_data(frame_obj.data)
    if ndimage is not None:
        matrix = ndimage.gaussian_filter(matrix_raw, sigma=0.6)
    else:
        matrix = matrix_raw

    ppi = calculate_peak_pressure_index(matrix)
    contact_area = calculate_contact_area(matrix)
    in_contact = matrix[matrix > LOWER_THRESHOLD]
    avg_pressure = float(np.mean(in_contact)) if len(in_contact) > 0 else 0.0
    asymmetry = calculate_asymmetry_score(matrix)
    variability = calculate_pressure_variability(matrix)
    concentration = calculate_pressure_concentration(matrix)
    cop_x, cop_y = calculate_center_of_pressure(matrix)
    movement_index = calculate_movement_index(matrix, previous_matrix=previous_matrix)
    sustained_load = calculate_sustained_load_index(sustained_streak)
    hot_zones = find_hot_zones(matrix_raw)

    risk_score, _ = calculate_risk_components(
        ppi=ppi,
        contact_area=contact_area,
        asymmetry=asymmetry,
        concentration=concentration,
        sustained_load=sustained_load,
        movement_index=movement_index,
    )
    risk_level = get_risk_level(risk_score)

    explanation = generate_plain_english(
        ppi=ppi,
        contact_area=contact_area,
        asymmetry=asymmetry,
        risk_level=risk_level,
        risk_score=risk_score,
        pressure_variability=variability,
        movement_index=movement_index,
        concentration=concentration,
        sustained_load=sustained_load,
        center_of_pressure=(cop_x, cop_y),
    )

    metrics, _ = PressureMetrics.objects.update_or_create(
        frame=frame_obj,
        defaults={
            'peak_pressure_index': round(ppi, 1),
            'contact_area_percent': contact_area,
            'average_pressure': round(avg_pressure, 1),
            'asymmetry_score': asymmetry,
            'pressure_variability': variability,
            'pressure_concentration': concentration,
            'movement_index': movement_index,
            'sustained_load_index': sustained_load,
            'center_of_pressure_x': cop_x,
            'center_of_pressure_y': cop_y,
            'risk_level': risk_level,
            'risk_score': risk_score,
            'hot_zones': json.dumps(hot_zones),
            'plain_english': explanation,
        },
    )
    return metrics


def _risk_trend_label(risks):
    if len(risks) < 6:
        return 'stable'

    segment = max(3, len(risks) // 5)
    start_avg = float(np.mean(risks[:segment]))
    end_avg = float(np.mean(risks[-segment:]))
    delta = end_avg - start_avg

    if delta >= 8:
        return 'worsening'
    if delta <= -8:
        return 'improving'
    return 'stable'


def generate_session_report_data(session):
    """Aggregate metrics across all frames in a session."""
    frames = session.frames.select_related('metrics').order_by('frame_index')
    metrics_list = []

    for frame in frames:
        if not hasattr(frame, 'metrics'):
            continue

        m = frame.metrics
        metrics_list.append({
            'timestamp': frame.timestamp.isoformat(),
            'frame_index': frame.frame_index,
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
        })

    if not metrics_list:
        return {}

    ppis = [m['ppi'] for m in metrics_list]
    risks = [m['risk_score'] for m in metrics_list]
    areas = [m['contact_area'] for m in metrics_list]
    movements = [m['movement_index'] for m in metrics_list]
    variabilities = [m['pressure_variability'] for m in metrics_list]
    sustained = [m['sustained_load_index'] for m in metrics_list]

    risk_counts = {'low': 0, 'moderate': 0, 'high': 0, 'critical': 0}
    for m in metrics_list:
        level = m['risk_level']
        if level in risk_counts:
            risk_counts[level] += 1

    peak_risk = max(metrics_list, key=lambda item: item['risk_score'])['risk_level']
    high_risk_events = risk_counts['high'] + risk_counts['critical']
    high_risk_ratio = round((high_risk_events / len(metrics_list)) * 100.0, 1)

    return {
        'frame_count': len(metrics_list),
        'avg_ppi': round(float(np.mean(ppis)), 1),
        'max_ppi': round(float(max(ppis)), 1),
        'avg_contact_area': round(float(np.mean(areas)), 1),
        'avg_risk_score': round(float(np.mean(risks)), 1),
        'avg_movement_index': round(float(np.mean(movements)), 1),
        'avg_pressure_variability': round(float(np.mean(variabilities)), 1),
        'max_sustained_load': round(float(max(sustained)), 1),
        'high_risk_events': high_risk_events,
        'high_risk_ratio': high_risk_ratio,
        'risk_trend': _risk_trend_label(risks),
        'peak_risk_level': peak_risk,
        'risk_distribution': risk_counts,
        'timeline': metrics_list,
    }


def _create_alert_if_missing(session, frame, alert_type, message, risk_score):
    from .models import PressureAlert

    exists = PressureAlert.objects.filter(
        session=session,
        frame=frame,
        alert_type=alert_type,
        acknowledged=False,
    ).exists()
    if exists:
        return False

    PressureAlert.objects.create(
        session=session,
        frame=frame,
        alert_type=alert_type,
        message=message,
        risk_score=risk_score,
    )
    return True


def generate_session_alerts(session, recreate_unacknowledged=False):
    """Generate clinician-facing alerts from analysed frame metrics."""
    from .models import PressureAlert

    if recreate_unacknowledged:
        PressureAlert.objects.filter(session=session, acknowledged=False).delete()

    created = 0
    critical_seen = False
    sustained_streak = 0
    last_sustained_frame_index = -99999

    for frame in session.frames.select_related('metrics').order_by('frame_index'):
        if not hasattr(frame, 'metrics'):
            continue

        m = frame.metrics

        if m.risk_score >= 80 or m.peak_pressure_index >= CRITICAL_THRESHOLD:
            critical_seen = True
            if _create_alert_if_missing(
                session=session,
                frame=frame,
                alert_type='critical',
                message=(
                    f"Critical pressure detected (risk {m.risk_score:.0f}/100, "
                    f"PPI {m.peak_pressure_index:.0f}). Immediate repositioning advised."
                ),
                risk_score=m.risk_score,
            ):
                created += 1
        elif m.risk_score >= 62 or m.peak_pressure_index >= UPPER_THRESHOLD:
            if _create_alert_if_missing(
                session=session,
                frame=frame,
                alert_type='high_ppi',
                message=(
                    f"High pressure event detected (risk {m.risk_score:.0f}/100, "
                    f"PPI {m.peak_pressure_index:.0f})."
                ),
                risk_score=m.risk_score,
            ):
                created += 1

        if m.asymmetry_score >= 48 and m.risk_score >= 45:
            if m.center_of_pressure_x is not None and m.center_of_pressure_x < 15.5:
                side = "left"
            elif m.center_of_pressure_x is not None and m.center_of_pressure_x >= 15.5:
                side = "right"
            else:
                side = "one"

            if _create_alert_if_missing(
                session=session,
                frame=frame,
                alert_type='asymmetry',
                message=(
                    f"Significant {side}-sided loading asymmetry detected "
                    f"({m.asymmetry_score:.1f}% imbalance)."
                ),
                risk_score=m.risk_score,
            ):
                created += 1

        if m.risk_score >= 60 or m.sustained_load_index >= 45:
            sustained_streak += 1
        else:
            sustained_streak = 0

        if sustained_streak >= 6 and (frame.frame_index - last_sustained_frame_index) >= 6:
            if _create_alert_if_missing(
                session=session,
                frame=frame,
                alert_type='sustained',
                message=(
                    f"Sustained elevated pressure pattern over {sustained_streak} consecutive frames."
                ),
                risk_score=m.risk_score,
            ):
                created += 1
            last_sustained_frame_index = frame.frame_index

    if critical_seen and not session.flagged_for_review:
        session.flagged_for_review = True
        session.save(update_fields=['flagged_for_review'])

    return created
