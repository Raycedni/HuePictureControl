from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from database import DATABASE_PATH, close_db, init_db
from routers.health import router as health_router
from routers.hue import router as hue_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB connection and initialize schema
    db = await init_db(DATABASE_PATH)
    app.state.db = db
    yield
    # Shutdown: close DB connection
    await close_db(db)


app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(hue_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
