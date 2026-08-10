from pathlib import Path

import aiosqlite
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

DB_PATH = Path("/app/data/modbot.db")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

ACTION_COLORS = {
    "ban": "#ef4444",
    "kick": "#f97316",
    "timeout": "#eab308",
    "warn": "#3b82f6",
    "unban": "#22c55e",
    "clear": "#8b5cf6",
}


async def get_db_rows(query: str, params: tuple = ()):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    actions = await get_db_rows(
        "SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 50"
    )
    stats_raw = await get_db_rows(
        "SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action"
    )
    stats = {r["action"]: r["count"] for r in stats_raw}
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "actions": actions, "stats": stats, "colors": ACTION_COLORS},
    )


@app.get("/api/actions")
async def api_actions():
    return await get_db_rows(
        "SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 100"
    )


@app.get("/api/warnings")
async def api_warnings():
    return await get_db_rows(
        "SELECT * FROM warnings ORDER BY timestamp DESC LIMIT 100"
    )
