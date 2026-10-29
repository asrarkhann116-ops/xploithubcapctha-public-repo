"""
Xploit Unblocker — Human Biometrics & Bezier Trajectory Engine
Generates human-like cursor movements, smooth velocity curves,
sub-pixel micro-tremors, and natural slider drag trajectories to bypass
behavioral bot detection (DataDome, Cloudflare, GeeTest).
"""

import math
import random
import time
from typing import List, Tuple, Dict, Any

def _binomial(n: int, k: int) -> float:
    """Calculate binomial coefficient C(n, k)."""
    return math.factorial(n) / (math.factorial(k) * math.factorial(n - k))

def _bezier_point(points: List[Tuple[float, float]], t: float) -> Tuple[float, float]:
    """Calculate point on an n-degree Bezier curve at parameter t in [0, 1]."""
    n = len(points) - 1
    x = 0.0
    y = 0.0
    for i, (px, py) in enumerate(points):
        coeff = _binomial(n, i) * ((1.0 - t) ** (n - i)) * (t ** i)
        x += coeff * px
        y += coeff * py
    return (x, y)

def generate_bezier_trajectory(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int = 30,
    deviation_scale: float = 0.25,
    add_jitter: bool = True
) -> List[Tuple[float, float]]:
    """
    Generate natural human cursor trajectory between two points using
    cubic Bezier interpolation with randomized physiological control points.
    """
    x0, y0 = start
    x3, y3 = end
    dist = math.hypot(x3 - x0, y3 - y0)

    if dist < 1.0:
        return [end]

    # Deviation perpendicular to the direct vector
    angle = math.atan2(y3 - y0, x3 - x0)
    perp_angle = angle + (math.pi / 2.0) * random.choice([1, -1])
    offset = dist * deviation_scale * random.uniform(0.4, 1.2)

    # First control point (accelerating from origin)
    p1_dist = dist * random.uniform(0.2, 0.45)
    x1 = x0 + math.cos(angle) * p1_dist + math.cos(perp_angle) * offset * random.uniform(0.5, 1.0)
    y1 = y0 + math.sin(angle) * p1_dist + math.sin(perp_angle) * offset * random.uniform(0.5, 1.0)

    # Second control point (decelerating toward target with slight overshoot damping)
    p2_dist = dist * random.uniform(0.55, 0.85)
    x2 = x0 + math.cos(angle) * p2_dist + math.cos(perp_angle) * offset * random.uniform(0.1, 0.5)
    y2 = y0 + math.sin(angle) * p2_dist + math.sin(perp_angle) * offset * random.uniform(0.1, 0.5)

    control_points = [(x0, y0), (x1, y1), (x2, y2), (x3, y3)]

    # Generate points with non-linear ease-in-ease-out time parameter
    trajectory: List[Tuple[float, float]] = []
    for step in range(steps + 1):
        progress = step / float(steps)
        # Smooth step (Hermite ease-in-out)
        t = progress * progress * (3.0 - 2.0 * progress)

        px, py = _bezier_point(control_points, t)

        # Physiological hand jitter (0.2 - 0.7 pixels)
        if add_jitter and 0 < step < steps:
            px += random.gauss(0, 0.35)
            py += random.gauss(0, 0.35)

        trajectory.append((round(px, 2), round(py, 2)))

    return trajectory

def apply_human_mouse_move(sb, target_x: float, target_y: float, steps: int = 25):
    """
    Simulate natural cursor travel to target coordinates using CDP Input domain.
    """
    try:
        # Default start from current viewport center or random upper-left area
        start_x = random.uniform(150, 300)
        start_y = random.uniform(100, 250)

        path = generate_bezier_trajectory((start_x, start_y), (target_x, target_y), steps=steps)

        for px, py in path:
            try:
                # Use SeleniumBase native CDP mouse dispatch if available
                sb.cdp.mouse.move(px, py)
            except Exception:
                pass
            time.sleep(random.uniform(0.005, 0.015))

    except Exception:
        pass

def human_drag_slider(sb, slider_selector: str, distance_px: int = 260):
    """
    Solves horizontal slider challenges (e.g., GeeTest, DataDome)
    by simulating human wrist acceleration, deceleration, and micro-wiggles.
    """
    try:
        elem = sb.find_element(slider_selector)
        if not elem:
            return False

        rect = elem.rect
        start_x = rect['x'] + (rect['width'] / 2.0)
        start_y = rect['y'] + (rect['height'] / 2.0)

        # 1. Move to slider knob naturally
        apply_human_mouse_move(sb, start_x, start_y, steps=18)
        time.sleep(random.uniform(0.1, 0.25))

        # 2. Mouse down (press)
        try:
            sb.cdp.mouse.down()
        except Exception:
            return False

        time.sleep(random.uniform(0.08, 0.16))

        # 3. Simulate variable-speed drag with overshoot and correction
        traveled = 0
        target = distance_px
        overshoot = target + random.randint(3, 8)

        # Phase A: Fast acceleration towards target
        while traveled < overshoot:
            remaining = overshoot - traveled
            step = random.uniform(remaining * 0.15, remaining * 0.35) + random.uniform(2, 6)
            traveled += step
            current_x = start_x + min(traveled, overshoot)
            current_y = start_y + random.gauss(0, 0.4) # slight vertical drift
            try:
                sb.cdp.mouse.move(current_x, current_y)
            except Exception:
                pass
            time.sleep(random.uniform(0.01, 0.03))

        time.sleep(random.uniform(0.05, 0.12))

        # Phase B: Micro-correction (pulling back to exact notch)
        while traveled > target:
            step = random.uniform(1, 2.5)
            traveled -= step
            current_x = start_x + max(traveled, target)
            current_y = start_y + random.gauss(0, 0.2)
            try:
                sb.cdp.mouse.move(current_x, current_y)
            except Exception:
                pass
            time.sleep(random.uniform(0.015, 0.035))

        time.sleep(random.uniform(0.1, 0.2))

        # 4. Mouse up (release)
        try:
            sb.cdp.mouse.up()
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"[HUMAN_ENGINE] Slider drag error: {e}")
        return False
