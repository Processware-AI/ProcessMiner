from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import worker
from app.api import auth, build, documents, records, sources, tenants
from app.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    stop = worker.start_in_background() if get_settings().run_worker_in_api else None
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="ProcessMiner API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(documents.router)
app.include_router(sources.router)
app.include_router(build.router)
app.include_router(records.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
