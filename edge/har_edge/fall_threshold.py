"""Bản Python của bộ phát hiện té bằng ngưỡng trên ESP32 (firmware/lib/fall_detector).

Giữ hai bản giống hệt nhau để: (1) thí nghiệm D đánh giá ngưỡng trên dataset,
(2) fake_device.py giả lập ESP32. Máy trạng thái 4 bước:

1. Rơi tự do: SVM < freefall_g kéo dài ≥ freefall_ms
2. Va chạm: trong impact_window_ms sau đó có SVM > impact_g
3. Bất động: trong 1 s cuối của still_delay_ms sau va chạm, SVM trong [still_lo, still_hi],
   con quay < still_gyro_dps (cho phép 10 % mẫu lệch) và tư thế đã đổi (nghiêng > posture_deg)
4. -> nghi té (suspected)
"""
from dataclasses import dataclass, field

import numpy as np

from .features import UPRIGHT


@dataclass
class ThresholdParams:
    freefall_g: float = 0.4
    freefall_ms: int = 80
    impact_g: float = 2.5
    impact_window_ms: int = 500
    still_delay_ms: int = 2000
    still_check_ms: int = 1000
    still_lo: float = 0.8
    still_hi: float = 1.2
    still_gyro_dps: float = 30.0
    still_ratio: float = 0.9
    posture_deg: float = 50.0


@dataclass
class FallThreshold:
    p: ThresholdParams = field(default_factory=ThresholdParams)
    state: str = "idle"
    _ff_start: int | None = None
    _ff_end: int = 0
    _impact_t: int = 0
    _peak: float = 0.0
    _n: int = 0
    _n_still: int = 0
    _sum: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def reset(self) -> None:
        self.state = "idle"
        self._ff_start = None

    def update(self, t_ms: int, acc_g, gyr_dps) -> dict | None:
        """Gọi cho từng mẫu 50 Hz. Trả {"t": thời điểm va chạm, "peak_g": ...} khi nghi té."""
        ax, ay, az = acc_g
        svm = (ax * ax + ay * ay + az * az) ** 0.5
        gmag = (gyr_dps[0] ** 2 + gyr_dps[1] ** 2 + gyr_dps[2] ** 2) ** 0.5
        p = self.p

        if self.state == "idle":
            if svm < p.freefall_g:
                if self._ff_start is None:
                    self._ff_start = t_ms
                if t_ms - self._ff_start >= p.freefall_ms:
                    self.state = "freefall"
            else:
                self._ff_start = None
        elif self.state == "freefall":
            if svm < p.freefall_g:
                self._ff_end = t_ms  # vẫn đang rơi
            elif svm > p.impact_g:
                self.state = "impact"
                self._impact_t = t_ms
                self._peak = svm
                self._n = self._n_still = 0
                self._sum = np.zeros(3)
            elif t_ms - max(self._ff_end, self._ff_start or 0) > p.impact_window_ms:
                self.reset()
        elif self.state == "impact":
            dt = t_ms - self._impact_t
            if dt < 300:
                self._peak = max(self._peak, svm)
            if dt >= p.still_delay_ms - p.still_check_ms:
                self._n += 1
                if p.still_lo <= svm <= p.still_hi and gmag < p.still_gyro_dps:
                    self._n_still += 1
                self._sum += np.array([ax, ay, az])
            if dt >= p.still_delay_ms:
                still = self._n > 0 and self._n_still / self._n >= p.still_ratio
                mean = self._sum / max(self._n, 1)
                norm = np.linalg.norm(mean) or 1.0
                tilt = float(np.degrees(np.arccos(np.clip(mean @ UPRIGHT / norm, -1, 1))))
                result = {"t": self._impact_t, "peak_g": round(float(self._peak), 2), "tilt_deg": round(tilt, 1)}
                self.reset()
                if still and tilt > p.posture_deg:
                    return result
        return None


def detect_all(t_ms: np.ndarray, acc: np.ndarray, gyr: np.ndarray, params: ThresholdParams | None = None) -> list[dict]:
    """Chạy bộ phát hiện trên cả một bản ghi; trả danh sách lần nghi té."""
    det = FallThreshold(params or ThresholdParams())
    out = []
    for i in range(len(t_ms)):
        r = det.update(int(t_ms[i]), acc[i], gyr[i])
        if r:
            out.append(r)
    return out
