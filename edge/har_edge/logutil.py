"""Cấu hình log chung cho các dịch vụ: che token Telegram, tắt log từng request của httpx.

URL của Telegram Bot API chứa token (https://api.telegram.org/bot<token>/...). httpx ghi URL ở mức INFO cho mọi
request và trong thông báo lỗi, nên không che thì token nằm trong journal của Pi.
"""
import logging
import re

FMT = "%(asctime)s %(name)s %(levelname)s %(message)s"
TOKEN_RE = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")


def redact(text: str) -> str:
    return TOKEN_RE.sub("bot<token-ẩn>", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # gồm cả traceback
        return redact(super().format(record))


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(FMT))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
