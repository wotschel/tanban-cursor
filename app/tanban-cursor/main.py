from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

import schemas
from config import settings
from routers import webhooks as webhook_routes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="tanban-cursor", lifespan=lifespan)
app.include_router(webhook_routes.router)


@app.get("/health", response_model=schemas.HealthOut)
def health():
    return schemas.HealthOut(app_env=settings.app_env)


@app.get("/")
def root():
    return JSONResponse(
        {
            "service": "tanban-cursor",
            "health": "/health",
            "webhooks": {"tanban": "POST /webhooks/tanban"},
        }
    )


def add_security_headers(response: Response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    add_security_headers(response)
    return response
