"""Chạy toàn bộ thí nghiệm A1, A2, B1, B2, C, D trên một thư mục dữ liệu.

    python run_experiments.py --data data/raw            # dữ liệu thật
    python run_experiments.py --data data/synthetic --skip-cnn

C so sánh cửa sổ 2,0 s với 2,5 s cho RF có BMP280 (A2 là bản 2,5 s);
khi đã biết model tốt nhất, chạy lại train_*.py với --window 2.0 cho model đó.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import har_ml  # noqa: F401  (UTF-8 console)

HERE = Path(__file__).resolve().parent


def run(*args: str) -> None:
    print("\n$", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=HERE, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "raw"))
    ap.add_argument("--skip-cnn", action="store_true")
    ap.add_argument("--epochs", default="40")
    a = ap.parse_args()
    d = ["--data", a.data]
    run("train_rf.py", *d, "--experiment", "A1", "--no-baro")
    run("train_rf.py", *d, "--experiment", "A2", "--baro", "--export")
    if not a.skip_cnn:
        run("train_cnn.py", *d, "--experiment", "B1", "--no-baro", "--epochs", a.epochs)
        run("train_cnn.py", *d, "--experiment", "B2", "--baro", "--epochs", a.epochs, "--export")
    run("train_rf.py", *d, "--experiment", "C", "--baro", "--window", "2.0")
    run("eval_fall.py", *d, "--baro")
    print("\nXong. Kết quả ở results/*/metrics.json — đẩy lên VPS bằng push_metrics.py")


if __name__ == "__main__":
    main()
