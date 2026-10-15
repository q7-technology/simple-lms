import logging

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from lms.api import errors, logs
from lms.api.deps import DB
from lms.api.routes import (
    auth, competencies, entra, learning, matrix, media, modules, overrides, people, policies,
    practicals, records, roles, settings, signoffs, tickets, uploads,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logs.install()

app = FastAPI(
    title="Simple LMS",
    version="0.1.0",
    description="Open source, self-hosted workplace training. The API is the only door.",
    docs_url="/docs",
    redoc_url=None,
)
errors.install(app)

v1 = APIRouter(prefix="/v1")
v1.include_router(auth.router)
v1.include_router(entra.router)
v1.include_router(people.router)
v1.include_router(roles.router)
v1.include_router(competencies.router)
v1.include_router(overrides.router)
v1.include_router(records.router)
v1.include_router(matrix.router)
v1.include_router(uploads.router)
v1.include_router(media.router)
v1.include_router(policies.router)
v1.include_router(tickets.router)
v1.include_router(modules.router)
v1.include_router(learning.router)
v1.include_router(practicals.router)
v1.include_router(signoffs.router)
v1.include_router(settings.router)


@v1.get("/health", tags=["system"])
def health(db: DB):
    db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(v1)
