from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from fastapi.responses import FileResponse
from models import Base, init_models, AsyncSessionLocal
from routers import attendance, administration
from auth import router as auth_router, get_async_session, engine_url

app = FastAPI(title="Attendance API")

# CORS (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(attendance.router, prefix="", tags=["attendance"])
app.include_router(administration.router, prefix="/admin", tags=["admin"])

# Create DB on startup
@app.on_event("startup")
async def on_startup():
    engine = create_async_engine(engine_url, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Подаваме AsyncSessionLocal вместо get_async_session
    await init_models(AsyncSessionLocal)

@app.on_event("shutdown")
async def on_shutdown():
    pass

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse("index.html")
