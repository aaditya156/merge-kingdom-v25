from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.api.v1 import (
    auth,
    players,
    saves,
    legacy,
    wallet,
    purchases,
    entitlements,
    migration,
    admin,
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Authoritative backend prototype for Merge Kingdom 2.5 currency & synchronization migration.",
    version="2.5.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# CORS configuration for frontend React dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": str(exc),
        },
    )


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": "2.5.0",
        "environment": settings.ENVIRONMENT,
    }

# Include routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(players.router, prefix=settings.API_V1_STR)
app.include_router(saves.router, prefix=settings.API_V1_STR)
app.include_router(legacy.router, prefix=settings.API_V1_STR)
app.include_router(wallet.router, prefix=settings.API_V1_STR)
app.include_router(purchases.router, prefix=settings.API_V1_STR)
app.include_router(entitlements.router, prefix=settings.API_V1_STR)
app.include_router(migration.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)
