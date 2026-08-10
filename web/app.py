from pathlib import Path

import aiosqlite
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
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


async def get_config(key: str) -> str | None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else None
    except Exception:
        return None


async def set_config(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def ensure_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mod_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                target_name TEXT NOT NULL,
                moderator_id INTEGER NOT NULL,
                moderator_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


@app.on_event("startup")
async def startup():
    await ensure_tables()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    actions = await get_db_rows(
        "SELECT * FROM mod_actions ORDER BY timestamp DESC LIMIT 50"
    )
    stats_raw = await get_db_rows(
        "SELECT action, COUNT(*) as count FROM mod_actions GROUP BY action"
    )
    stats = {r["action"]: r["count"] for r in stats_raw}
    token_set = bool(await get_config("discord_token"))
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "actions": actions, "stats": stats, "colors": ACTION_COLORS, "token_set": token_set},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    token = await get_config("discord_token")
    masked = ("•" * 40 + token[-6:]) if token else None
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "masked": masked, "saved": saved},
    )


@app.post("/settings")
async def settings_save(token: str = Form(...)):
    token = token.strip()
    if token:
        await set_config("discord_token", token)
    return RedirectResponse("/settings?saved=true", status_code=303)


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
