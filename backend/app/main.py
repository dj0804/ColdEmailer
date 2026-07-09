from fastapi import FastAPI

from .db import Base, engine

app = FastAPI(title="Applier")


@app.on_event("startup")
def startup() -> None:
    from . import models  # noqa: F401  (register tables before create_all)

    Base.metadata.create_all(bind=engine)


@app.get("/api/health")
def health():
    return {"status": "ok"}
