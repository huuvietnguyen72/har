"""pytest ml/tests — chạy được không cần tải SisFall (dùng dữ liệu tổng hợp đúng định dạng)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from har_edge import LABELS  # noqa: E402
from har_edge.features import UPRIGHT  # noqa: E402
from har_ml.dataset import load_recordings, make_windows  # noqa: E402
from har_ml.sisfall import (K_GYRO, K_MMA, convert, label_of, parse_name, rotation_to, subject_rotation,  # noqa: E402
                            to_units, write_session)

G_BITS = 1024  # 1 g của MMA8451Q (±8 g, 14 bit)


def raw_signal(acc_g: np.ndarray, gyr_dps: np.ndarray | None = None) -> np.ndarray:
    """Tạo mảng thô 9 cột (bit) từ gia tốc g ở 200 Hz; cột ADXL345 để 0 (không dùng)."""
    n = len(acc_g)
    gyr = np.zeros((n, 3)) if gyr_dps is None else gyr_dps
    out = np.zeros((n, 9), dtype=np.int64)
    out[:, 3:6] = np.round(gyr / K_GYRO)
    out[:, 6:9] = np.round(acc_g / K_MMA)
    return out


def test_units_and_names():
    acc, gyr = to_units(np.array([[0, 0, 0, 16384, 0, -16384, 0, -G_BITS, 2 * G_BITS]]))
    assert np.allclose(acc, [[0, -1, 2]]) and np.allclose(gyr, [[1000, 0, -1000]])
    assert parse_name("F05_SA01_R04.npy") == ("F05", "SA01", 4)
    assert [label_of(c) for c in ("D01", "D02", "D03", "D05", "D18", "F01", "F15")] == \
        ["walk", "walk", "adl", "adl", "adl", "fall", "fall"]
    with pytest.raises(ValueError):
        to_units(np.zeros((5, 6)))


def test_rotation_to():
    for a in ([0, -1, 0], [0.2, -0.95, 0.1], [1, 0, 0], [-1, 0, 0]):
        R = rotation_to(a, UPRIGHT)
        assert np.allclose(R @ (np.asarray(a) / np.linalg.norm(a)), UPRIGHT, atol=1e-9)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and np.isclose(np.linalg.det(R), 1.0)


def test_convert_resample_rotate_clip():
    n = 800  # 4 s ở 200 Hz
    acc = np.tile([0.0, -1.0, 0.0], (n, 1))  # SisFall: đứng thẳng thì Y chỉ xuống
    acc[400] = [0, -7.9, 0]                   # va chạm gần trần ±8 g
    gyr = np.zeros((n, 3))
    gyr[400:410, 2] = 1500                    # vượt ±500 °/s của MPU6050
    raw = raw_signal(acc, gyr)
    g, R = subject_rotation([raw_signal(np.tile([0.0, -1.0, 0.0], (n, 1)))])
    assert np.allclose(g, [0, -1, 0], atol=1e-3)
    a50, g50 = convert(raw, R)
    assert a50.shape == (200, 3) and g50.shape == (200, 3)
    assert np.allclose(a50[:80].mean(axis=0), UPRIGHT, atol=0.01)  # đã xoay về X chỉ xuống
    assert np.abs(a50).max() <= 8.0 and np.abs(g50).max() <= 500.0
    assert np.abs(g50).max() == pytest.approx(500.0)


def test_sessions_load_and_windows(tmp_path):
    rng = np.random.default_rng(0)
    R = rotation_to([0, -1, 0], UPRIGHT)
    n = 15 * 200
    # té khi đang chạy (F05): các bước chạy > 2 g trước cú ngã 6 g ở giây 9
    acc = np.tile([0.0, -1.0, 0.0], (n, 1)) + rng.normal(0, 0.02, (n, 3))
    for s in range(200, 1600, 120):
        acc[s:s + 6, 1] -= 1.6                # bước chạy ~2,6 g
    acc[1800:1806] = [0.5, -6.0, 0.5]         # va chạm
    acc[1806:] = [0.0, 0.0, -1.0]             # nằm
    out = tmp_path / "sisfall_sessions"
    a50, g50 = convert(raw_signal(acc), R)
    write_session(out, "F05", "SA01", 1, a50, g50, 1_400_000_000_000, np.array([0, -1, 0]))
    walk = np.tile([0.0, -1.0, 0.0], (6000, 1)) + rng.normal(0, 0.1, (6000, 3))
    a50, g50 = convert(raw_signal(walk), R)
    write_session(out, "D01", "SA01", 1, a50, g50, 1_400_000_100_000, np.array([0, -1, 0]))
    a50, g50 = convert(raw_signal(walk[:2400]), R)
    write_session(out, "D18", "SA01", 1, a50, g50, 1_400_000_200_000, np.array([0, -1, 0]))
    meta = json.loads((out / "sisfall_SA01_F05_R01" / "meta.json").read_text(encoding="utf-8"))
    assert meta["subject"] == "SisFall_SA01" and meta["activity"] == "fall" and meta["fall_lie"] is False

    other = tmp_path / "raw"  # thư mục thứ hai: đọc được nhiều thư mục ngăn bằng dấu phẩy
    other.mkdir()
    recs = load_recordings(f"{out},{other}")
    assert sorted(r.activity for r in recs) == ["fall", "walk"]  # "adl" không dùng huấn luyện
    fall = [r for r in recs if r.activity == "fall"][0]
    assert fall.source == "SisFall" and fall.fall_lie is False
    win = make_windows(recs)
    labels = {LABELS[i] for i in win.y}
    assert labels == {"fall", "walk"}  # không có "lie" từ phần sau té của SisFall
    fall_rows = np.where(win.rec_ids == fall.id)[0]
    assert len(fall_rows) > 0
    # mọi cửa sổ té đều chứa đỉnh va chạm lớn nhất, không phải bước chạy
    for i in fall_rows:
        svm = np.linalg.norm(win.acc[i], axis=1)
        assert svm.max() > 4.0, "cửa sổ té phải chứa va chạm 6 g, không phải bước chạy 2,6 g"
