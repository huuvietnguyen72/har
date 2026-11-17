"""Chuyển dataset SisFall sang định dạng phiên của dự án (imu.csv + meta.json).

SisFall: A. Sucerquia, J.D. López, J.F. Vargas-Bonilla, "SisFall: A Fall and Movement Dataset",
Sensors 17(1):198, 2017, doi:10.3390/s17010198. Khi dùng phải trích dẫn bài báo này.

Theo Readme.txt của dataset: 38 người (SA01–SA23 từ 19–30 tuổi, SE01–SE15 từ 60–75 tuổi), thiết bị đeo ở
thắt lưng, 200 Hz, mỗi file 9 cột số nguyên (bit): ADXL345 x,y,z (±16 g, 13 bit) | ITG3200 x,y,z (±2000 °/s,
16 bit) | MMA8451Q x,y,z (±8 g, 14 bit). Đổi đơn vị: [(2·Range)/(2^Resolution)]·giá_trị.
Bản sao dùng ở đây (gitee.com/yuxiqin/imu-fall-database) lưu mỗi file thành .npy int32 cùng 9 cột.

Chuyển đổi cho khớp bộ đeo har01:
- Gia tốc lấy từ MMA8451Q (±8 g như MPU6050), con quay ITG3200 cắt về ±500 °/s.
- Lọc chống răng cưa + lấy mẫu 200 Hz -> 50 Hz (resample_poly 1/4).
- Hệ trục: SisFall đứng thẳng thì Y chỉ xuống; mỗi người được xoay sao cho trọng lực trung bình khi đi bộ
  (D01) trùng UPRIGHT của bộ đeo (X chỉ xuống). Hướng quanh trục đứng (trước/sau, trái/phải) không căn được,
  giống giữa các người đeo thật.
- Nhãn: D01, D02 -> walk; F01–F15 -> fall (chỉ đoạn quanh va chạm, "fall_lie": false vì không chắc người
  ngã nằm yên tới hết lượt). Hoạt động khác -> "adl" (không dùng huấn luyện, giữ để đo báo động giả).
"""
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from har_edge.features import FS, UPRIGHT

FS_SRC = 200
K_GYRO = 2 * 2000 / 2**16  # °/s mỗi bit (ITG3200)
K_MMA = 2 * 8 / 2**14  # g mỗi bit (MMA8451Q)
ACC_RANGE_G = 8.0  # MPU6050 trên bộ đeo
GYRO_RANGE_DPS = 500.0

ACTIVITIES = {
    "D01": "Walking slowly", "D02": "Walking quickly", "D03": "Jogging slowly", "D04": "Jogging quickly",
    "D05": "Walking upstairs and downstairs slowly", "D06": "Walking upstairs and downstairs quickly",
    "D07": "Slowly sit in a half height chair, wait a moment, and up slowly",
    "D08": "Quickly sit in a half height chair, wait a moment, and up quickly",
    "D09": "Slowly sit in a low height chair, wait a moment, and up slowly",
    "D10": "Quickly sit in a low height chair, wait a moment, and up quickly",
    "D11": "Sitting a moment, trying to get up, and collapse into a chair",
    "D12": "Sitting a moment, lying slowly, wait a moment, and sit again",
    "D13": "Sitting a moment, lying quickly, wait a moment, and sit again",
    "D14": "Being on one's back change to lateral position, wait a moment, and change to one's back",
    "D15": "Standing, slowly bending at knees, and getting up",
    "D16": "Standing, slowly bending without bending knees, and getting up",
    "D17": "Standing, get into a car, remain seated and get out of the car",
    "D18": "Stumble while walking", "D19": "Gently jump without falling (trying to reach a high object)",
    "F01": "Fall forward while walking caused by a slip", "F02": "Fall backward while walking caused by a slip",
    "F03": "Lateral fall while walking caused by a slip", "F04": "Fall forward while walking caused by a trip",
    "F05": "Fall forward while jogging caused by a trip", "F06": "Vertical fall while walking caused by fainting",
    "F07": "Fall while walking, with use of hands in a table to dampen fall, caused by fainting",
    "F08": "Fall forward when trying to get up", "F09": "Lateral fall when trying to get up",
    "F10": "Fall forward when trying to sit down", "F11": "Fall backward when trying to sit down",
    "F12": "Lateral fall when trying to sit down", "F13": "Fall forward while sitting, caused by fainting or falling asleep",
    "F14": "Fall backward while sitting, caused by fainting or falling asleep",
    "F15": "Lateral fall while sitting, caused by fainting or falling asleep",
}


def label_of(code: str) -> str:
    """Nhãn của dự án cho mã hoạt động SisFall: walk | fall | adl (không dùng huấn luyện)."""
    if code in ("D01", "D02"):
        return "walk"
    if code.startswith("F"):
        return "fall"
    return "adl"


def parse_name(name: str) -> tuple[str, str, int]:
    """'F05_SA01_R04.npy' -> ('F05', 'SA01', 4)."""
    code, subj, trial = Path(name).stem.split("_")
    return code, subj, int(trial.lstrip("R"))


def to_units(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mảng thô (n, 9) bit -> (gia tốc MMA8451Q g, con quay ITG3200 °/s) ở 200 Hz."""
    raw = np.asarray(raw, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] != 9:
        raise ValueError(f"cần 9 cột, nhận {raw.shape}")
    return raw[:, 6:9] * K_MMA, raw[:, 3:6] * K_GYRO


def resample_50hz(x: np.ndarray) -> np.ndarray:
    """200 Hz -> 50 Hz có lọc chống răng cưa."""
    return resample_poly(x, 1, FS_SRC // FS, axis=0)


def rotation_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Ma trận xoay R (3x3) đưa hướng a về hướng b: R @ a/|a| = b/|b|."""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        # ngược chiều: xoay 180° quanh một trục vuông góc với a
        p = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        u = np.cross(a, p)
        u /= np.linalg.norm(u)
        return 2 * np.outer(u, u) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def convert(raw: np.ndarray, rot: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mảng thô (n, 9) -> (acc g, gyr °/s) ở 50 Hz, đã xoay về hệ trục bộ đeo và cắt theo dải đo MPU6050."""
    acc, gyr = to_units(raw)
    acc, gyr = resample_50hz(acc) @ rot.T, resample_50hz(gyr) @ rot.T
    return np.clip(acc, -ACC_RANGE_G, ACC_RANGE_G), np.clip(gyr, -GYRO_RANGE_DPS, GYRO_RANGE_DPS)


def subject_rotation(walk_raw: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Từ các lượt đi bộ của một người: (trọng lực trung bình khi đứng thẳng, ma trận xoay về UPRIGHT)."""
    g = np.mean(np.concatenate([to_units(r)[0] for r in walk_raw]), axis=0)
    return g, rotation_to(g, UPRIGHT)


def write_session(out_root: Path, code: str, subj: str, trial: int, acc: np.ndarray, gyr: np.ndarray,
                  t0: int, gravity: np.ndarray) -> Path:
    sid = f"sisfall_{subj}_{code}_R{trial:02d}"
    d = Path(out_root) / sid
    d.mkdir(parents=True, exist_ok=True)
    t = t0 + np.arange(len(acc), dtype=np.int64) * (1000 // FS)
    with open(d / "imu.csv", "w", encoding="utf-8", newline="") as f:
        f.write("t,ax,ay,az,gx,gy,gz\n")
        for i in range(len(acc)):
            f.write(f"{t[i]},{acc[i, 0]:.5f},{acc[i, 1]:.5f},{acc[i, 2]:.5f},"
                    f"{gyr[i, 0]:.5f},{gyr[i, 1]:.5f},{gyr[i, 2]:.5f}\n")
    meta = {
        "id": sid, "dev": "sisfall", "subject": f"SisFall_{subj}", "activity": label_of(code),
        "note": ACTIVITIES.get(code, code), "source": "SisFall", "sisfall_code": code, "trial": trial,
        "start": int(t[0]) if len(t) else t0, "end": int(t[-1]) if len(t) else t0,
        "upright": [float(x) for x in UPRIGHT], "upright_source": "sisfall_walk",
        "sisfall_gravity_g": [round(float(x), 4) for x in gravity],
        "fall_lie": False, "fs_src": FS_SRC, "samples": int(len(acc)),
        "sensor": "MMA8451Q ±8 g + ITG3200 (cắt ±500 °/s), 200 Hz -> 50 Hz",
        "citation": "Sucerquia et al., Sensors 17(1):198, 2017, doi:10.3390/s17010198",
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d
