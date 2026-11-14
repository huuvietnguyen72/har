"""Đọc cấu hình từ edge/.env (xem .env.example)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

EDGE_DIR = Path(__file__).resolve().parent.parent


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass
class Config:
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    data_dir: Path = EDGE_DIR / "data"
    model_dir: Path = EDGE_DIR / "models" / "current"
    cloud_backend: str = "console"  # vps | console
    vps_api_url: str = ""
    vps_device_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    webapp_url: str = ""
    # Ngưỡng hợp nhất cảnh báo té (chọn lại theo thí nghiệm D)
    fall_p_confirm: float = 0.5
    fall_p_model_only: float = 0.8
    fall_lie_after_s: float = 5.0
    low_battery_v: float = 3.4
    offline_alert_s: float = 120.0
    status_every_s: float = 5.0
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "edge.db"


def load_config(env_file: str | os.PathLike | None = None) -> Config:
    load_dotenv(env_file or EDGE_DIR / ".env")
    data_dir = Path(os.getenv("DATA_DIR", EDGE_DIR / "data"))
    if not data_dir.is_absolute():
        data_dir = EDGE_DIR / data_dir
    model_dir = Path(os.getenv("MODEL_DIR", EDGE_DIR / "models" / "current"))
    if not model_dir.is_absolute():
        model_dir = EDGE_DIR / model_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        mqtt_host=os.getenv("MQTT_HOST", "localhost"),
        mqtt_port=int(os.getenv("MQTT_PORT", 1883)),
        mqtt_user=os.getenv("MQTT_USER", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        data_dir=data_dir,
        model_dir=model_dir,
        cloud_backend=os.getenv("CLOUD_BACKEND", "console"),
        vps_api_url=os.getenv("VPS_API_URL", "").rstrip("/"),
        vps_device_key=os.getenv("VPS_DEVICE_KEY", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        webapp_url=os.getenv("WEBAPP_URL", "").rstrip("/"),
        fall_p_confirm=_f("FALL_P_CONFIRM", 0.5),
        fall_p_model_only=_f("FALL_P_MODEL_ONLY", 0.8),
        fall_lie_after_s=_f("FALL_LIE_AFTER_S", 5.0),
        low_battery_v=_f("LOW_BATTERY_V", 3.4),
        offline_alert_s=_f("OFFLINE_ALERT_S", 120.0),
        status_every_s=_f("STATUS_EVERY_S", 5.0),
    )
