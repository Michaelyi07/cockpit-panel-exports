"""FastAPI app factory with lifespan-managed background worker."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config
from .routes import root_router, router
from .worker import worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if config.WORKER_ENABLED:
        task = asyncio.create_task(worker_loop())
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    config.enforce_secrets()  # refuse to start without LINK_SECRET
    app = FastAPI(title="Dash Exports (S3-DASH-004)", version="1.0.0",
                  lifespan=lifespan)
    app.include_router(router)
    app.include_router(root_router)
    return app


app = create_app()
