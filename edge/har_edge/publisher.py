"""Lớp Publisher: har-uplink chỉ gọi các hàm này nên không phụ thuộc chi tiết API.

- HttpPublisher : gửi tới VPS (httpx, timeout 5 s), chỉ coi là thành công khi nhận 2xx
- ConsolePublisher : in ra màn hình, dùng để thử outbox trước khi VPS sẵn sàng
"""
import json
import logging

import httpx

log = logging.getLogger(__name__)


class PublishError(Exception):
    """Lỗi tạm thời (mạng, 5xx): giữ trong outbox và thử lại."""


class RejectedError(Exception):
    """Cloud từ chối hẳn (4xx khác 401/429): thử lại cũng vô ích."""


class Publisher:
    def publish_status(self, status: dict) -> dict: ...
    def publish_segments(self, segments: list[dict]) -> dict: ...
    def publish_events(self, events: list[dict]) -> dict: ...
    def publish_metrics(self, report: dict) -> dict: ...
    def publish_system_metrics(self, items: list[dict]) -> dict: ...

    def publish_event(self, event: dict) -> dict:
        return self.publish_events([event])

    def close(self) -> None:
        pass


class HttpPublisher(Publisher):
    def __init__(self, api_url: str, device_key: str, timeout: float = 5.0, client: httpx.Client | None = None):
        if not api_url or not device_key:
            raise ValueError("Thiếu VPS_API_URL hoặc VPS_DEVICE_KEY trong edge/.env")
        self.client = client or httpx.Client(
            base_url=api_url.rstrip("/"), timeout=timeout, headers={"X-Device-Key": device_key}
        )

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self.client.post(path, json=body)
        except httpx.HTTPError as e:
            raise PublishError(f"{path}: {e.__class__.__name__}: {e}") from e
        if 200 <= r.status_code < 300:
            return r.json()
        if r.status_code in (401, 408, 429) or r.status_code >= 500:
            raise PublishError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
        raise RejectedError(f"{path}: HTTP {r.status_code} {r.text[:300]}")

    def publish_status(self, status: dict) -> dict:
        return self._post("/ingest/status", status)

    def publish_segments(self, segments: list[dict]) -> dict:
        return self._post("/ingest/segments", {"v": 1, "segments": segments})

    def publish_events(self, events: list[dict]) -> dict:
        return self._post("/ingest/events", {"v": 1, "events": events})

    def publish_metrics(self, report: dict) -> dict:
        return self._post("/ingest/metrics", report)

    def publish_system_metrics(self, items: list[dict]) -> dict:
        return self._post("/ingest/system_metrics", {"v": 1, "items": items})

    def close(self) -> None:
        self.client.close()


class ConsolePublisher(Publisher):
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def _print(self, kind: str, body) -> dict:
        self.sent.append((kind, body))
        print(f"[publish {kind}] {json.dumps(body, ensure_ascii=False)[:300]}", flush=True)
        return {"ok": True}

    def publish_status(self, status: dict) -> dict:
        return self._print("status", status)

    def publish_segments(self, segments: list[dict]) -> dict:
        return self._print("segments", segments)

    def publish_events(self, events: list[dict]) -> dict:
        return self._print("events", events)

    def publish_metrics(self, report: dict) -> dict:
        return self._print("metrics", report)

    def publish_system_metrics(self, items: list[dict]) -> dict:
        return self._print("system_metrics", items)


def make_publisher(cfg) -> Publisher:
    if cfg.cloud_backend == "vps":
        return HttpPublisher(cfg.vps_api_url, cfg.vps_device_key)
    return ConsolePublisher()
