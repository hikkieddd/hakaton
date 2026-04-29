"""FastAPI-приложение «Бюджетный конструктор выборок»."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import DERIVED, METRIC_PRESETS, METRICS, SECTION_RULES
from etl import load_all
from excel_export import build_excel
from selection import apply_section_filter, build_selection, search_objects
from storage import StorageBackend, get_storage

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"


class State:
    df: pd.DataFrame = pd.DataFrame()
    loaded_at: datetime | None = None
    storage: StorageBackend | None = None


STATE = State()


def _load_facts() -> pd.DataFrame:
    """Загружает факты: из PostgreSQL, если режим включён, иначе из CSV/XLSX."""
    storage = STATE.storage
    if storage and storage.enabled:
        try:
            df = storage.load_facts()
            if df is not None and not df.empty:
                print(f"[main] loaded {len(df)} facts from PostgreSQL")
                return df
            print("[main] PostgreSQL пустой — fallback на CSV-загрузку")
        except Exception as exc:
            print(f"[main] PostgreSQL load failed: {exc} — fallback на CSV")
    df = load_all()
    if storage and storage.enabled and not df.empty:
        try:
            storage.save_facts(df)
            print(f"[main] факты сохранены в PostgreSQL ({len(df)} строк)")
        except Exception as exc:
            print(f"[main] PostgreSQL save failed: {exc}")
    return df


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE.storage = get_storage()
    if STATE.storage and STATE.storage.enabled:
        print(f"[main] storage backend: PostgreSQL ({STATE.storage.dsn_safe()})")
    else:
        print("[main] storage backend: file (CSV/XLSX)")
    STATE.df = _load_facts()
    STATE.loaded_at = datetime.now()
    print(f"[main] facts loaded: {len(STATE.df)} at {STATE.loaded_at}")
    yield


app = FastAPI(title="Бюджетный конструктор выборок", version="1.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    df = STATE.df
    storage_mode = "postgres" if STATE.storage and STATE.storage.enabled else "file"
    sources: dict[str, int] = {}
    if not df.empty and "source" in df.columns:
        sources = {str(k): int(v) for k, v in df["source"].value_counts().to_dict().items()}
    period_min = period_max = None
    if not df.empty and "date" in df.columns:
        try:
            period_min = str(df["date"].min())
            period_max = str(df["date"].max())
        except Exception:
            pass
    return {
        "ok": True,
        "facts": int(len(df)),
        "loaded_at": STATE.loaded_at.isoformat() if STATE.loaded_at else None,
        "sources": sources,
        "period_min": period_min,
        "period_max": period_max,
        "storage_mode": storage_mode,
    }


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    return {"metrics": METRICS, "presets": METRIC_PRESETS, "derived": DERIVED}


@app.get("/api/sections")
def sections() -> dict[str, Any]:
    return {
        "sections": [
            {"id": k, "title": v["title"], "rule": {kk: vv for kk, vv in v.items() if kk != "title"}}
            for k, v in SECTION_RULES.items()
        ]
    }


@app.get("/api/objects")
def objects(q: str = "", section: str | None = None,
            types: str | None = None, limit: int = 200) -> dict[str, Any]:
    try:
        type_list = [t for t in (types or "").split(",") if t]
        items = search_objects(STATE.df, query=q, types=type_list or None,
                               section=section, limit=limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"objects search failed: {exc}")


@app.get("/api/object_types")
def object_types() -> dict[str, Any]:
    df = STATE.df
    if df.empty or "object_type" not in df.columns:
        return {"items": []}
    counts = df["object_type"].value_counts().to_dict()
    titles = {
        "kcsr_event": "Мероприятия (КЦСР)",
        "capital_object": "Объекты капитальных вложений",
        "agreement": "Соглашения",
        "contract_object": "Контракты / договоры",
        "buau_org": "Организации БУ/АУ",
    }
    return {"items": [
        {"id": str(k), "title": titles.get(str(k), str(k)), "count": int(v)}
        for k, v in counts.items() if k
    ]}


class Period(BaseModel):
    type: str = Field("all")
    date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    date_a: str | None = None
    date_b: str | None = None


class SelectionRequest(BaseModel):
    objects: list[str] = []
    metrics: list[str] = []
    section: str | None = None
    period: Period = Field(default_factory=Period)


def _payload(req: SelectionRequest) -> dict[str, Any]:
    if hasattr(req, "model_dump"):
        return req.model_dump()
    return req.dict()


@app.post("/api/selection")
def selection(req: SelectionRequest) -> dict[str, Any]:
    try:
        return build_selection(STATE.df, _payload(req))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"build_selection failed: {exc}")


@app.post("/api/export")
def export(req: SelectionRequest) -> Response:
    try:
        result = build_selection(STATE.df, _payload(req))
        blob = build_excel(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"export failed: {exc}")
    filename = f"selection_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/storage")
def storage_info() -> dict[str, Any]:
    storage = STATE.storage
    if storage and storage.enabled:
        return {"mode": "postgres", "dsn": storage.dsn_safe(), "table": getattr(storage, "table", None)}
    return {"mode": "file", "dsn": None, "table": None}


@app.post("/api/reload")
def reload() -> dict[str, Any]:
    storage = STATE.storage
    if storage and storage.enabled:
        # При активном PostgreSQL — перечитываем CSV и переписываем в PG.
        df = load_all()
        try:
            if not df.empty:
                storage.save_facts(df)
        except Exception as exc:
            print(f"[main] reload: PostgreSQL save failed: {exc}")
        STATE.df = df
    else:
        STATE.df = load_all()
    STATE.loaded_at = datetime.now()
    return {"ok": True, "facts": int(len(STATE.df)), "storage_mode": "postgres" if storage and storage.enabled else "file"}


if FRONTEND_DIR.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
