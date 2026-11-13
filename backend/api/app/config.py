from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://har:har@db:5432/har"
    jwt_secret: str = "doi-chuoi-ngau-nhien-dai"
    jwt_expire_hours: int = 12
    # Múi giờ dùng để chia "ngày" cho trang Lịch sử và tổng hợp theo ngày.
    tz_name: str = "Asia/Ho_Chi_Minh"
    # Trạng thái cũ hơn số giây này thì coi như thiết bị offline.
    status_stale_s: int = 30
    # Ghi lịch sử pin/nhiệt độ tối đa 1 dòng mỗi N giây cho mỗi thiết bị.
    status_log_every_s: int = 60
    # Chỉ dùng khi chạy web app dev ở cổng khác; trên VPS web app cùng tên miền nên không cần.
    cors_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
