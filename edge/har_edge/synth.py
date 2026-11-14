"""Sinh tín hiệu IMU + áp suất GIẢ LẬP cho từng hoạt động.

Chỉ dùng để thử toàn tuyến (fake_device.py) và kiểm tra code huấn luyện
(ml/make_synthetic.py). KHÔNG dùng số liệu từ dữ liệu giả lập trong báo cáo.

Hệ trục: đeo hông phải, Y chỉ xuống đất -> đứng thẳng đọc ay ≈ -1 g.
"""
import numpy as np

from .units import PA_PER_METER

FS = 50


def _rot_x(deg: float) -> np.ndarray:
    r = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])


def _gravity(posture: str, rng: np.random.Generator) -> np.ndarray:
    up = np.array([0.0, -1.0, 0.0])
    if posture == "stand":
        return _rot_x(rng.normal(0, 4)) @ up
    if posture == "sit":
        return _rot_x(rng.uniform(30, 55)) @ up
    if posture == "lie":
        variants = [np.array([0.0, 0.05, 1.0]), np.array([1.0, 0.1, 0.1]), np.array([-1.0, 0.1, 0.1])]
        g = variants[rng.integers(len(variants))] + rng.normal(0, 0.05, 3)
        return g / np.linalg.norm(g)
    return up


def _gait(n: int, f: float, amp: float, gyro_amp: float, rng: np.random.Generator):
    t = np.arange(n) / FS
    ph = rng.uniform(0, 2 * np.pi)
    w = 2 * np.pi * f
    acc = np.zeros((n, 3))
    acc[:, 1] = -1 + amp * np.sin(w * t + ph) + 0.3 * amp * np.sin(2 * w * t + ph)
    acc[:, 2] = 0.6 * amp * np.sin(w * t + ph + 1.2)
    acc[:, 0] = 0.4 * amp * np.sin(0.5 * w * t + ph)
    gyr = np.zeros((n, 3))
    gyr[:, 0] = gyro_amp * np.sin(w * t + ph + 0.5)
    gyr[:, 1] = 0.7 * gyro_amp * np.sin(0.5 * w * t + ph)
    gyr[:, 2] = 0.5 * gyro_amp * np.sin(w * t + ph + 2.0)
    return acc, gyr


def generate(activity: str, duration_s: float, rng: np.random.Generator | None = None,
             p0: float = 100_800.0, subject_scale: float = 1.0):
    """Trả (acc (n,3) g, gyr (n,3) °/s, pressure (n,) Pa) ở 50 Hz."""
    rng = rng or np.random.default_rng()
    n = int(duration_s * FS)
    s = subject_scale
    climb = 0.0  # m/s
    if activity in ("stand", "sit", "lie"):
        g = _gravity(activity, rng)
        acc = np.tile(g, (n, 1)) + rng.normal(0, 0.012, (n, 3))
        gyr = rng.normal(0, 0.8, (n, 3))
    elif activity == "walk":
        acc, gyr = _gait(n, rng.uniform(1.7, 2.0) * s, rng.uniform(0.22, 0.32), 25, rng)
    elif activity == "run":
        acc, gyr = _gait(n, rng.uniform(2.6, 3.0) * s, rng.uniform(0.8, 1.1), 70, rng)
    elif activity == "stairs_up":
        acc, gyr = _gait(n, rng.uniform(1.4, 1.7) * s, rng.uniform(0.25, 0.35), 30, rng)
        climb = rng.uniform(0.15, 0.25)
    elif activity == "stairs_down":
        acc, gyr = _gait(n, rng.uniform(1.8, 2.1) * s, rng.uniform(0.3, 0.42), 30, rng)
        climb = -rng.uniform(0.15, 0.25)
    elif activity == "fall":
        return fall(duration_s, rng, p0)
    else:
        raise ValueError(activity)
    acc = acc + rng.normal(0, 0.02, acc.shape)
    gyr = gyr + rng.normal(0, 1.5, gyr.shape)
    t = np.arange(n) / FS
    pressure = p0 - climb * t * PA_PER_METER + rng.normal(0, 1.0, n)
    return acc, gyr, pressure


def fall(duration_s: float = 6.0, rng: np.random.Generator | None = None, p0: float = 100_800.0):
    """1 s đứng → 0,3 s rơi tự do → va chạm 3–5 g → nằm yên. Đỉnh SVM ở khoảng 1,35 s."""
    rng = rng or np.random.default_rng()
    n = int(duration_s * FS)
    acc = np.zeros((n, 3))
    gyr = rng.normal(0, 1.0, (n, 3))
    i_ff, i_imp = int(1.0 * FS), int(1.3 * FS)
    acc[:i_ff] = _gravity("stand", rng)
    ff = np.linspace(0, 1, i_imp - i_ff)[:, None]
    acc[i_ff:i_imp] = (1 - ff) * acc[i_ff - 1] * 0.5 + rng.normal(0, 0.05, (i_imp - i_ff, 3)) + 0.1
    peak = rng.uniform(3.0, 5.0)
    k = 4
    direction = rng.normal(0, 1, 3)
    direction /= np.linalg.norm(direction)
    for j in range(k):
        acc[i_imp + j] = direction * peak * (1 - j / k) + rng.normal(0, 0.2, 3)
    gyr[i_ff:i_imp + k] += rng.normal(0, 150, (i_imp + k - i_ff, 3))
    g_lie = _gravity("lie", rng)
    acc[i_imp + k:] = g_lie + rng.normal(0, 0.01, (n - i_imp - k, 3))
    pressure = p0 + np.where(np.arange(n) > i_imp, 0.8 * PA_PER_METER, 0) + rng.normal(0, 1.0, n)
    return acc, gyr, pressure
