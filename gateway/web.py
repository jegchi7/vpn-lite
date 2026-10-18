from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import control, db, profiles, rpc, security
from .config import ROOT, ETC, read_json, public

templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(app):
    from .monitor import run as monitor_run
    from .bot import run as bot_run
    db.initialize()
    tasks = [asyncio.create_task(monitor_run()), asyncio.create_task(bot_run())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="RU / Foreign", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def headers(request, call_next):
    try:
        length = int(request.headers.get("content-length", "0") or "0")
    except ValueError:
        return Response("Некорректный запрос", status_code=400)
    if length > 65536:
        return Response("Запрос слишком большой", status_code=413)
    if request.method == "POST":
        origin = request.headers.get("origin")
        cfg = public()
        expected = cfg["url"].rstrip("/")
        if origin and origin != expected:
            return Response("Источник запроса не разрешён", status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def page(request, template, **context):
    return templates.TemplateResponse(request=request, name=template, context={"cfg": public(), **context})


def current(request: Request):
    user = security.session(request.cookies.get("ruvpn_session"))
    if not user:
        raise HTTPException(303, headers={"Location": "/login"})
    return user


async def write(request: Request, user=Depends(current)):
    form = await request.form(max_files=0, max_fields=30)
    if not security.csrf_ok(form.get("csrf"), user["csrf"]):
        raise HTTPException(403, "Обновите страницу и повторите действие")
    return user


def admin(user=Depends(current)):
    if not user["admin"]:
        raise HTTPException(403, "Нужны права администратора")
    return user


def admin_page(request, template="admin.html", **context):
    user = current(request)
    if not user["admin"] or request.path_params.get("slug") != public()["admin_slug"]:
        raise HTTPException(404)
    return page(request, template, user=user, **context)


def redirect(path="/"):
    return RedirectResponse(path, status_code=303)


@app.exception_handler(ValueError)
async def input_error(request, exc):
    response = page(request, "error.html", user=security.session(request.cookies.get("ruvpn_session")), error=str(exc))
    response.status_code = 400
    return response


@app.get("/healthz")
def health():
    return {"panel": "running"}


@app.get("/login")
def login_page(request: Request):
    value = security.token()
    response = page(request, "login.html", csrf=value, error=request.query_params.get("error"))
    response.set_cookie("ruvpn_login", value, max_age=900, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/login")
async def login(request: Request):
    form = await request.form(max_fields=5, max_files=0)
    login = str(form.get("login", "")).strip().lower()[:32]
    if not security.csrf_ok(form.get("csrf"), request.cookies.get("ruvpn_login", "")):
        raise ValueError("Обновите страницу входа")
    address = request.client.host if request.client else "unknown"
    if not security.allow_attempt("login-ip:" + address, 25) or not security.allow_attempt("login-user:" + login, 8):
        raise ValueError("Слишком много попыток. Повторите через 15 минут")
    user = db.one("SELECT * FROM users WHERE login=?", (login,))
    valid = security.verify_password(user["password"] if user else None, str(form.get("password", "")))
    if not valid or not user or user["blocked"] or not user["password"]:
        return redirect("/login?error=1")
    value = security.new_session(user["id"])
    response = redirect()
    response.delete_cookie("ruvpn_login", secure=True, httponly=True, samesite="strict")
    response.set_cookie("ruvpn_session", value, max_age=43200, secure=True, httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout(request: Request, user=Depends(write)):
    with db.transaction() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (security.digest(request.cookies.get("ruvpn_session", "")),))
    response = redirect("/login")
    response.delete_cookie("ruvpn_session", secure=True, httponly=True, samesite="lax")
    return response


@app.get("/join/{value}")
def join_page(value: str, request: Request):
    csrf = security.token()
    response = page(request, "join.html", value=value, csrf=csrf)
    response.set_cookie("ruvpn_login", csrf, max_age=900, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/join/{value}")
async def join(value: str, request: Request):
    form = await request.form(max_fields=5, max_files=0)
    if not security.csrf_ok(form.get("csrf"), request.cookies.get("ruvpn_login", "")):
        raise ValueError("Обновите страницу приглашения")
    if not security.allow_attempt("join:" + (request.client.host if request.client else "unknown"), 20):
        raise ValueError("Слишком много попыток")
    await asyncio.to_thread(control.consume_invitation, value, password=str(form.get("password", "")))
    return redirect("/login")


@app.get("/")
def dashboard(request: Request, user=Depends(current)):
    devices = db.rows("SELECT * FROM devices WHERE user_id=? ORDER BY desired DESC,created DESC", (user["id"],))
    return page(request, "devices.html", user=user, devices=devices, intent=security.token(), count=sum(d["desired"] for d in devices))


@app.post("/devices")
async def add_device(request: Request, user=Depends(write)):
    form = await request.form()
    device_id = await asyncio.to_thread(control.create_device, user["id"], str(form.get("name", "")), str(form.get("intent", "")))
    return redirect("/device/" + device_id)


@app.get("/device/{device_id}")
def device_page(device_id: str, request: Request, user=Depends(current)):
    d = control.device_for(user["id"], device_id)
    protocol = request.query_params.get("protocol", "awg")
    if protocol not in {"awg", "vless", "singbox"}:
        raise ValueError("Неизвестный протокол")
    text = None
    if d["desired"] and d["state"] == "applied":
        _, text = profiles.profile(user["id"], device_id, protocol)
    return page(request, "device.html", user=user, device=d, protocol=protocol, profile=text)


@app.get("/device/{device_id}/download")
def download(device_id: str, request: Request, user=Depends(current)):
    name, text = profiles.profile(user["id"], device_id, request.query_params.get("protocol", "awg"))
    return Response(text, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/device/{device_id}/qr")
def qr(device_id: str, request: Request, user=Depends(current)):
    _, text = profiles.profile(user["id"], device_id, request.query_params.get("protocol", "awg"))
    return Response(profiles.qr_png(text), media_type="image/png")


@app.post("/device/{device_id}/{action}")
async def device_action(device_id: str, action: str, request: Request, user=Depends(write)):
    if action == "revoke":
        await asyncio.to_thread(control.revoke_device, user["id"], device_id)
        return redirect()
    if action == "rotate":
        await asyncio.to_thread(control.rotate_device, user["id"], device_id)
        return redirect("/device/" + device_id)
    raise HTTPException(404)


@app.get("/guide")
def guide(request: Request, user=Depends(current)):
    return page(request, "guide.html", user=user)


@app.get("/account")
def account(request: Request, user=Depends(current)):
    return page(request, "account.html", user=user)


@app.post("/account/{action}")
async def account_action(action: str, request: Request, user=Depends(write)):
    form = await request.form()
    if action == "password":
        await asyncio.to_thread(control.change_password, user["id"], str(form.get("old", "")), str(form.get("new", "")))
        return redirect("/login")
    if action == "telegram":
        value = control.invite(user["id"], user["id"], "telegram")
        return page(request, "invitation.html", user=user, title="Привязать Telegram", link="https://t.me/" + public()["bot_username"] + "?start=" + value, note="Откройте ссылку в личном чате с ботом. Срок — 1 час.")
    if action == "unlink":
        control.unlink_telegram(user["id"])
        return redirect("/account")
    raise HTTPException(404)


@app.get("/d/{value}")
def one_shot_page(value: str, request: Request):
    control.download_record(value)
    return page(request, "one-shot.html", value=value)


@app.post("/d/{value}")
def one_shot(value: str):
    record = control.download_record(value, consume=True)
    name, text = profiles.profile(record["user_id"], record["device_id"], record["protocol"])
    return Response(text, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/manage/{slug}")
def manage(slug: str, request: Request, user=Depends(admin)):
    if slug != public()["admin_slug"]:
        raise HTTPException(404)
    monitor = json.loads(db.setting("monitor", "{}"))
    checked = monitor.get("checked_at", 0)
    monitor["stale"] = time.time() - checked > max(90, read_json(ETC / "control.json")["paths"]["interval"] * 3)
    monitor["when"] = datetime.datetime.fromtimestamp(checked, datetime.timezone.utc).strftime("%H:%M:%S UTC") if checked else "ещё нет данных"
    try:
        status = rpc.call("status")
    except ValueError:
        status = {"components": {"helper": "unavailable"}}
    return admin_page(request, users=db.rows("SELECT id,login,admin,blocked,device_limit,telegram_id FROM users ORDER BY id"), status=status, monitor=monitor, revisions=db.rows("SELECT id,state,created,error FROM applied_revisions ORDER BY id DESC LIMIT 6"), events=db.rows("SELECT created,kind,detail FROM events ORDER BY id DESC LIMIT 15"), rules=db.rows("SELECT * FROM route_overrides ORDER BY priority,id"), mode=db.setting("path_mode", "auto"))


@app.post("/manage/{slug}/{action}")
async def manage_action(slug: str, action: str, request: Request, user=Depends(write)):
    if not user["admin"] or slug != public()["admin_slug"]:
        raise HTTPException(404)
    form = await request.form()
    actor = user["id"]
    if action == "user":
        _, value = control.create_user(actor, str(form.get("login", "")), int(form.get("limit", "3")))
        return page(request, "invitation.html", user=user, title="Приглашение готово", link=public()["url"] + "/join/" + value, note="Передайте ссылку лично. Она одноразовая и действует 24 часа. Пользователь сам задаст пароль.")
    elif action == "invite":
        value = control.invite(actor, int(form.get("user_id", "0")), "join")
        return page(request, "invitation.html", user=user, title="Новое приглашение", link=public()["url"] + "/join/" + value, note="Предыдущее приглашение больше не действует. Срок — 24 часа.")
    elif action in {"block", "unblock"}:
        await asyncio.to_thread(control.block_user, actor, int(form.get("user_id", "0")), action == "block")
    elif action == "revoke-all":
        await asyncio.to_thread(control.revoke_all, actor, int(form.get("user_id", "0")))
    elif action == "limit":
        limit = int(form.get("limit", "0"))
        if not 1 <= limit <= public()["limits"]["devices"]:
            raise ValueError("Недопустимый лимит")
        with db.transaction() as c:
            c.execute("UPDATE users SET device_limit=? WHERE id=?", (limit, int(form.get("user_id", "0"))))
    elif action == "mode":
        control.set_mode(actor, str(form.get("mode", "")))
    elif action == "rule":
        await asyncio.to_thread(control.add_rule, actor, str(form.get("kind", "")), str(form.get("value", "")), str(form.get("route", "")), int(form.get("priority", "100")))
    elif action == "delete-rule":
        await asyncio.to_thread(control.delete_rule, actor, int(form.get("rule_id", "0")))
    elif action == "explain":
        result = rpc.call("explain", value=str(form.get("value", "")))
        return page(request, "explain.html", user=user, result=result)
    elif action == "apply":
        await asyncio.to_thread(control.reapply, actor)
    elif action in {"lists-update", "lists-rollback"}:
        with control.serialized():
            rpc.call(action)
            await asyncio.to_thread(control.apply_locked, actor)
    else:
        raise HTTPException(404)
    return redirect("/manage/" + slug)
