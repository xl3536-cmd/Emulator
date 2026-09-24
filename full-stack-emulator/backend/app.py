from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.managers.emulator_manager import emulator_manager
from src.routes.config_routes import router as config_router
from src.routes.arctic_routes import router as arctic_router
from src.routes.emulator_routes import router as emulator_router
from src.routes.leak_sensor_routes import router as leak_sensor_router
from src.routes.rtd_routes import router as rtd_router
from src.routes.valve_routes import router as valve_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await emulator_manager.start()
    try:
        yield
    finally:
        await emulator_manager.stop()


app = FastAPI(
    title="Full Stack Emulator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(emulator_router)
app.include_router(rtd_router)
app.include_router(valve_router)
app.include_router(leak_sensor_router)
app.include_router(arctic_router)


@app.get("/")
def read_root():
    return {
        "message": "Full Stack Emulator",
        "status": "running",
        "config_endpoint": "/api/config",
        "runtime_endpoint": "/api/runtime",
    }
