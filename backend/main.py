from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.loop import AgentConfig, run_agent
from agent.observability.run_logger import RunLogger
from agent.schemas import RunRequest, RunResponse


BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
RUNS_DIR = BASE_DIR / "runs"
WORKSPACE_DIR = BASE_DIR / "workspace"

load_dotenv(override=True)

app = FastAPI(title="Mini Claude Code API")
logger = RunLogger(RUNS_DIR)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/run", response_model=RunResponse)
def create_run(request: RunRequest) -> RunResponse:
    try:
        return run_agent(request, logger, AgentConfig.from_env(WORKSPACE_DIR))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    try:
        events = logger.read_events(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc

    return {"run_id": run_id, "events": events}
