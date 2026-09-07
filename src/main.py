from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from src.core.config import settings
from src.db.session import engine
from src.routers.v1.router import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Dream Lounge API",
    description="청주대학교 동아리 관리 시스템 백엔드 API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(v1_router, prefix="/api/v1")


@app.middleware("http")
async def protect_cookie_authenticated_writes(request: Request, call_next):
    """운영에서 쿠키 인증 변경 요청의 출처를 검증해 CSRF를 차단한다."""
    if (
        settings.ENVIRONMENT.lower() == "production"
        and request.method in {"POST", "PATCH", "PUT", "DELETE"}
        and (
            request.cookies.get("dreamlounge_access")
            or request.cookies.get("dreamlounge_refresh")
        )
        and not request.headers.get("authorization")
    ):
        origin = request.headers.get("origin")
        if origin not in settings.get_allowed_origins():
            return JSONResponse(
                status_code=403,
                content={"detail": "허용되지 않은 요청 출처입니다."},
            )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}


@app.get("/health/ready", tags=["health"])
def readiness_check():
    """배포 트래픽 수신 전 실제 DB 연결 상태를 확인한다."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
