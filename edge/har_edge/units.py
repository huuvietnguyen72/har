"""Đổi giá trị thô của ESP32 sang đơn vị vật lý. Giữ khớp với firmware và docs/mqtt.md.

MPU6050 cấu hình ±8 g (4096 LSB/g) và ±500 °/s (65,5 LSB/(°/s)).
"""
import numpy as np

ACC_LSB_PER_G = 4096.0
GYRO_LSB_PER_DPS = 65.5
PA_PER_METER = 12.0  # gần mặt đất, áp giảm ~12 Pa mỗi mét


def imu_packet_to_array(msg: dict) -> np.ndarray:
    """Gói har/{dev}/imu -> mảng (n, 7): t_ms, ax, ay, az (g), gx, gy, gz (°/s)."""
    n = len(msg["ax"])
    t = msg["t0"] + np.arange(n, dtype=np.int64) * int(msg.get("dt", 20))
    acc = np.stack([msg["ax"], msg["ay"], msg["az"]], axis=1).astype(np.float64) / ACC_LSB_PER_G
    gyr = np.stack([msg["gx"], msg["gy"], msg["gz"]], axis=1).astype(np.float64) / GYRO_LSB_PER_DPS
    return np.column_stack([t.astype(np.float64), acc, gyr])


def env_packet_to_array(msg: dict) -> np.ndarray:
    """Gói har/{dev}/env -> mảng (n, 2): t_ms, p_pa."""
    p = np.asarray(msg.get("p_pa", []), dtype=np.float64)
    t = msg["t0"] + np.arange(len(p), dtype=np.int64) * int(msg.get("dt", 100))
    return np.column_stack([t.astype(np.float64), p])


def to_raw_acc(g: np.ndarray) -> np.ndarray:
    return np.clip(np.round(np.asarray(g) * ACC_LSB_PER_G), -32768, 32767).astype(int)


def to_raw_gyro(dps: np.ndarray) -> np.ndarray:
    return np.clip(np.round(np.asarray(dps) * GYRO_LSB_PER_DPS), -32768, 32767).astype(int)


def battery_pct(v: float | None) -> float | None:
    """Ước lượng % pin Li-ion 1 cell từ điện áp không tải (đường cong gần đúng)."""
    if v is None:
        return None
    curve = [(3.30, 0), (3.50, 5), (3.60, 10), (3.70, 25), (3.75, 40), (3.80, 50),
             (3.85, 60), (3.90, 70), (4.00, 82), (4.10, 93), (4.20, 100)]
    vs, ps = zip(*curve)
    return float(round(np.interp(v, vs, ps), 1))
