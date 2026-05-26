from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import create_async_engine
from models import Base, init_models, AsyncSessionLocal
from routers import attendance, administration
from auth import router as auth_router, engine_url

app = FastAPI(title="Attendance API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers (задължително ПРЕДИ StaticFiles)
app.include_router(auth_router,       prefix="/auth",  tags=["auth"])
app.include_router(attendance.router, prefix="",       tags=["attendance"])
app.include_router(administration.router, prefix="/admin", tags=["admin"])

# ── Статични файлове: CSS, JS, лого ──────────────────────────
# Монтира се на /static, но файловете са в текущата директория.
# html=True позволява директен достъп по filename.
app.mount("/static", StaticFiles(directory=".", html=False), name="static")

# ── Фронтенд: всички останали заявки → index.html ────────────
@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse("index.html")

# Поддръжка на директен достъп до CSS/JS/лого от корена
@app.get("/styles.css", include_in_schema=False)
async def serve_css():
    return FileResponse("styles.css", media_type="text/css")

@app.get("/app.js", include_in_schema=False)
async def serve_js():
    return FileResponse("app.js", media_type="application/javascript")

@app.get("/TU-Sofia_logo.png", include_in_schema=False)
async def serve_logo():
    return FileResponse("TU-Sofia_logo.png", media_type="image/png")

# ── Стартиране на БД ─────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    engine = create_async_engine(engine_url, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_models(AsyncSessionLocal)

@app.on_event("shutdown")
async def on_shutdown():
    pass