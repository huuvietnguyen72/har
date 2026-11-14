"""Đặc trưng cửa sổ — DÙNG CHUNG cho huấn luyện (ml/) và suy luận trên Pi.

Đổi bất cứ thứ gì ở đây thì phải huấn luyện lại model.

Quy ước đeo: hông phải, mũi tên Y của MPU6050 chỉ xuống đất. Khi đứng thẳng,
gia tốc kế đọc ay ≈ -1 g, nên hướng "đứng thẳng" trong hệ trục cảm biến là UPRIGHT.
"""
import numpy as np

from .units import PA_PER_METER

FS = 50
UPRIGHT = np.array([0.0, -1.0, 0.0])

_CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz", "svm", "gmag"]
_STATS = ["mean", "std", "min", "max", "rms", "skew", "kurt"]

FEATURE_NAMES_IMU: list[str] = (
    [f"{c}_{s}" for c in _CHANNELS for s in _STATS]
    + ["corr_ax_ay", "corr_ax_az", "corr_ay_az", "corr_gx_gy", "corr_gx_gz", "corr_gy_gz"]
    + ["svm_dom_freq", "svm_e_0_3hz", "svm_e_3_6hz", "svm_e_6_12hz", "svm_e_total"]
    + ["tilt_deg", "tilt_std_deg", "svm_jerk", "svm_p2p"]
)
FEATURE_NAMES_BARO: list[str] = ["p_slope_pa_s", "alt_change_m", "p_resid_std"]


def feature_names(use_baro: bool) -> list[str]:
    return FEATURE_NAMES_IMU + (FEATURE_NAMES_BARO if use_baro else [])


def _stats(x: np.ndarray) -> list[float]:
    m = x.mean()
    s = x.std()
    if s < 1e-9:
        skew = kurt = 0.0
    else:
        z = (x - m) / s
        skew = float((z**3).mean())
        kurt = float((z**4).mean() - 3.0)
    return [float(m), float(s), float(x.min()), float(x.max()), float(np.sqrt((x**2).mean())), skew, kurt]


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() < 1e-9 or b.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def tilt_deg(acc: np.ndarray) -> np.ndarray:
    """Góc (độ) giữa vector gia tốc từng mẫu và hướng đứng thẳng."""
    norm = np.linalg.norm(acc, axis=1)
    norm[norm < 1e-6] = 1e-6
    cos = (acc @ UPRIGHT) / norm
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def extract_features(acc: np.ndarray, gyr: np.ndarray, pressure: np.ndarray | None = None, fs: int = FS) -> np.ndarray:
    """acc (n,3) g, gyr (n,3) °/s, pressure (n,) Pa đã nội suy về fs hoặc None."""
    acc = np.asarray(acc, dtype=np.float64)
    gyr = np.asarray(gyr, dtype=np.float64)
    svm = np.linalg.norm(acc, axis=1)
    gmag = np.linalg.norm(gyr, axis=1)
    chans = [acc[:, 0], acc[:, 1], acc[:, 2], gyr[:, 0], gyr[:, 1], gyr[:, 2], svm, gmag]

    f: list[float] = []
    for c in chans:
        f += _stats(c)
    f += [_corr(acc[:, 0], acc[:, 1]), _corr(acc[:, 0], acc[:, 2]), _corr(acc[:, 1], acc[:, 2])]
    f += [_corr(gyr[:, 0], gyr[:, 1]), _corr(gyr[:, 0], gyr[:, 2]), _corr(gyr[:, 1], gyr[:, 2])]

    # Phổ của SVM (bỏ thành phần DC)
    x = svm - svm.mean()
    spec = np.abs(np.fft.rfft(x)) ** 2 / len(x)
    freqs = np.fft.rfftfreq(len(x), d=1.0 / fs)
    dom = float(freqs[1:][np.argmax(spec[1:])]) if len(spec) > 1 else 0.0
    band = lambda lo, hi: float(spec[(freqs >= lo) & (freqs < hi)].sum())  # noqa: E731
    f += [dom, band(0.3, 3), band(3, 6), band(6, 12), float(spec[1:].sum())]

    tilt = tilt_deg(acc)
    mean_vec = acc.mean(axis=0)
    mean_tilt = float(tilt_deg(mean_vec[None, :])[0])
    f += [mean_tilt, float(tilt.std()), float(np.abs(np.diff(svm)).mean() * fs), float(svm.max() - svm.min())]

    if pressure is not None:
        f += baro_features(np.asarray(pressure, dtype=np.float64), fs)
    return np.asarray(f, dtype=np.float32)


def baro_features(p: np.ndarray, fs: int = FS) -> list[float]:
    """Dùng hiệu áp (Pa/s) thay vì áp tuyệt đối vì áp tuyệt đối đổi theo thời tiết."""
    if p.size < 2 or not np.all(np.isfinite(p)):
        return [0.0, 0.0, 0.0]
    t = np.arange(len(p)) / fs
    slope, intercept = np.polyfit(t, p, 1)
    resid = p - (slope * t + intercept)
    alt_change = -(slope * t[-1]) / PA_PER_METER
    return [float(slope), float(alt_change), float(resid.std())]


def smooth_pressure(p: np.ndarray, fs: int = FS, window_s: float = 0.5) -> np.ndarray:
    """Lọc thông thấp đơn giản (trung bình trượt) cho áp suất đã nội suy lên 50 Hz."""
    k = max(1, int(window_s * fs))
    if len(p) < k:
        return p
    kernel = np.ones(k) / k
    padded = np.pad(p, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def cnn_input(acc: np.ndarray, gyr: np.ndarray, pressure: np.ndarray | None = None) -> np.ndarray:
    """Đầu vào 1D-CNN: (n, 6) chỉ IMU hoặc (n, 7) thêm hiệu áp so với đầu cửa sổ (Pa)."""
    cols = [np.asarray(acc, dtype=np.float32), np.asarray(gyr, dtype=np.float32)]
    if pressure is not None:
        p = np.asarray(pressure, dtype=np.float32)
        p = np.nan_to_num(p - p[0]) if p.size else np.zeros(len(acc), np.float32)
        cols.append(p[:, None])
    return np.concatenate(cols, axis=1)
