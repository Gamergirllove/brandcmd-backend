from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from app.config import get_settings
from app.routers import auth, connect, analytics


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate config is loadable
    settings = get_settings()
    print(f"Starting creator analytics API — frontend: {settings.frontend_url}")
    yield
    # Shutdown
    print("Shutting down creator analytics API")


app = FastAPI(
    title="Creator Analytics API",
    description="Backend API for aggregating creator analytics across YouTube, Instagram, TikTok, Twitter, and more.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(connect.router)
app.include_router(analytics.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", tags=["root"])
async def root():
    return {
        "name": "Creator Analytics API",
        "docs": "/docs",
        "health": "/health",
    }
