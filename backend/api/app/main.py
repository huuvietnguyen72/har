import logging

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlmodel import Session

from .config import get_settings
from .db import get_session
from .routers import auth, ingest, read
from .security import ws_user
from .ws import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="HAR cloud API",
    description="API của bộ đeo hông nhận dạng hoạt động và phát hiện té ngã (IoT Level 5).",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

if len(get_settings().jwt_secret) < 32 or get_settings().jwt_secret.startswith("doi-"):
    logging.getLogger("har").warning("JWT_SECRET đang là giá trị mẫu hoặc quá ngắn — đổi trong backend/.env!")

origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True
    )

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(read.router)


@app.get("/api/health", tags=["giám sát"])
def health(session: Session = Depends(get_session)):
    session.exec(text("SELECT 1"))
    return {"ok": True, "ws_clients": manager.count}


@app.websocket("/ws")
async def websocket(ws: WebSocket, claims: dict | None = Depends(ws_user)):
    if claims is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(ws)
    try:
        while True:
            # Web app gửi "ping" định kỳ; chỉ cần đọc để biết khi nào client đóng.
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
