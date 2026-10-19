from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import control, db, passkeys, profiles, rpc, security, telemetry
from .config import ROOT, ETC, read_json, public

templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(app):
    from .monitor import run as monitor_run
    from .bot import run as bot_run
    db.initialize()
    tasks = [asyncio.create_task(monitor_run()), asyncio.create_task(bot_run()), asyncio.create_task(telemetry.run_collector())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="CHIMERA", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def headers(request, call_next):
    request.state.csp_nonce = secrets.token_urlsafe(24)
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
    # no-referrer makes browsers send Origin: null on regular form POSTs.
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = f"default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; script-src 'self' 'nonce-{request.state.csp_nonce}'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def page(request, template, **context):
    cfg = public()
    person = context.pop("user", None)
    safe_user = {k: person[k] for k in ("id", "login", "admin", "device_limit", "telegram_id", "csrf")} if person else None
    safe_cfg = {k: cfg[k] for k in ("endpoint", "url", "bot_username", "limits")}
    safe_cfg["topology"] = cfg.get("topology", {"entry": "ru", "remote": "foreign"})
    safe_cfg.update(awg={"gateway": cfg["awg"]["gateway"], "port": cfg["awg"]["port"]}, vless={"port": cfg["vless"]["port"], "server_name": cfg["vless"]["server_name"]})
    if person and person["admin"]:
        safe_cfg["admin_slug"] = cfg["admin_slug"]
    data = {"view": template.removesuffix(".html"), "user": safe_user, "cfg": safe_cfg, **context}
    if person:
        data["state"] = panel_state(person, administrative=data["view"] == "admin")
        data["password_min"] = security.password_minimum(bool(person["admin"]))
        data["passkeys"] = db.rows("SELECT id,label,created,last_used FROM passkeys WHERE user_id=? ORDER BY created", (person["id"],))
    # Only these whitelisted presentation fields reach the browser. Credentials
    # are included solely on the authenticated single-device profile page.
    manifest = ROOT / "static/panel/manifest.json"
    if not manifest.exists():
        return HTMLResponse("Панель CHIMERA не собрана. Выполните npm ci && npm run build в web/.", status_code=503)
    entry = read_json(manifest)["src/main.ts"]
    return templates.TemplateResponse(request=request, name="shell.html", context={"data": data, "entry": entry, "nonce": request.state.csp_nonce})


def monitor_state():
    monitor = json.loads(db.setting("monitor", "{}"))
    checked = monitor.get("checked_at", 0)
    interval = read_json(ETC / "control.json")["paths"]["interval"]
    monitor["stale"] = time.time() - checked > max(90, interval * 3)
    return monitor


def panel_state(user, administrative=False, period="24h"):
    metrics = telemetry.current()
    cfg = public()
    devices = db.rows("SELECT id,name,address,desired,state,created FROM devices WHERE user_id=? ORDER BY desired DESC,created DESC", (user["id"],))
    subnet = ipaddress.ip_network(cfg["awg"]["subnet"])
    for device in devices:
        device["ip"] = str(subnet[device["address"]])
        device["usage"] = metrics.get("devices", {}).get(device["id"]) if not metrics["stale"] else None
    own_usage = [d["usage"] for d in devices if d["desired"] and d["usage"]]
    data = {
        "checked_at": int(time.time()), "monitor": monitor_state(), "devices": devices,
        "telemetry_stale": metrics["stale"],
        "usage": {k: sum(d[k] for d in own_usage if d.get(k) is not None) if any(d.get(k) is not None for d in own_usage) else None for k in ("download", "upload", "download_total", "upload_total")},
        "events": db.rows("SELECT created,kind,detail FROM events WHERE actor=? ORDER BY id DESC LIMIT 40", (user["id"],)),
    }
    if administrative:
        try:
            status = rpc.call("status")
        except ValueError:
            status = {"components": {"ruvpn-helper": "unavailable"}}
        data.update(
            metrics={k: v for k, v in metrics.items() if k != "devices"}, status=status,
            history=telemetry.history(period),
            users=db.rows("SELECT u.id,u.login,u.admin,u.blocked,u.device_limit,u.telegram_id,u.created,CASE WHEN u.password IS NOT NULL THEN 1 ELSE 0 END AS activated,(SELECT COUNT(*) FROM devices d WHERE d.user_id=u.id AND d.desired=1) AS device_count FROM users u ORDER BY u.id"),
            rules=db.rows("SELECT * FROM route_overrides ORDER BY priority,id"),
            revisions=db.rows("SELECT id,state,created,error FROM applied_revisions ORDER BY id DESC LIMIT 10"),
            events=db.rows("SELECT e.created,e.kind,e.detail,u.login AS actor_login FROM events e LEFT JOIN users u ON u.id=e.actor ORDER BY e.id DESC LIMIT 100"),
            mode=db.setting("path_mode", "auto"),
        )
    return data


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
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": str(exc)}, status_code=400)
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
    remember = form.get("remember") == "on"
    value = security.new_session(user["id"], remember=remember, verified_hash=user["password"])
    response = redirect()
    response.delete_cookie("ruvpn_login", secure=True, httponly=True, samesite="strict")
    response.set_cookie("ruvpn_session", value, max_age=604800 if remember else 43200, secure=True, httponly=True, samesite="lax")
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
    invitation = invitation_user(value, "join")
    response = page(request, "join.html", value=value, csrf=csrf, login=invitation["login"], password_min=security.password_minimum(bool(invitation["admin"])))
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
    return page(request, "devices.html", user=user, intent=security.token())


@app.post("/devices")
async def add_device(request: Request, user=Depends(write)):
    form = await request.form()
    device_id = await asyncio.to_thread(control.create_device, user["id"], str(form.get("name", "")), str(form.get("intent", "")))
    return redirect("/device/" + device_id)


@app.post("/devices/clear-revoked")
async def clear_revoked(user=Depends(write)):
    await asyncio.to_thread(control.delete_revoked, user["id"])
    return redirect("/#devices")


@app.get("/device/{device_id}")
def device_page(device_id: str, request: Request, user=Depends(current)):
    d = control.device_for(user["id"], device_id)
    protocol = request.query_params.get("protocol", "amnezia")
    if protocol not in {"awg", "amnezia", "vless", "singbox"}:
        raise ValueError("Неизвестный протокол")
    text = None
    if d["desired"] and d["state"] == "applied":
        _, text = profiles.profile(user["id"], device_id, protocol)
    return page(request, "device.html", user=user, device={k: d[k] for k in ("id", "name", "desired", "state", "created")}, protocol=protocol, profile=text)


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
    if action == "rename":
        form = await request.form()
        control.rename_device(user["id"], device_id, form.get("name", ""))
        return redirect("/device/" + device_id)
    if action == "delete":
        await asyncio.to_thread(control.delete_revoked, user["id"], device_id)
        return redirect("/#devices")
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
    if action == "passkey-delete":
        passkeys.remove(user["id"], str(form.get("credential_id", "")))
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
    return admin_page(request)


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
    elif action == "reset":
        value = control.invite(actor, int(form.get("user_id", "0")), "reset")
        return page(request, "invitation.html", user=user, title="Восстановление доступа", link=public()["url"] + "/reset/" + value, note="Ссылка одноразовая, действует 24 часа. После установки нового пароля завершатся сеансы и будут удалены ключи входа; VPN-профили сохранятся.")
    elif action in {"block", "unblock"}:
        await asyncio.to_thread(control.block_user, actor, int(form.get("user_id", "0")), action == "block")
    elif action == "revoke-all":
        await asyncio.to_thread(control.revoke_all, actor, int(form.get("user_id", "0")))
    elif action == "limit":
        limit = int(form.get("limit", "0"))
        if not 1 <= limit <= public()["limits"]["devices"]:
            raise ValueError("Недопустимый лимит")
        with db.transaction() as c:
            if not c.execute("SELECT 1 FROM users WHERE id=?", (int(form.get("user_id", "0")),)).fetchone():
                raise ValueError("Пользователь не найден")
            c.execute("UPDATE users SET device_limit=? WHERE id=?", (limit, int(form.get("user_id", "0"))))
            db.event(c, actor, "device_limit_changed", str(int(form.get("user_id", "0"))))
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
    section = str(form.get("section", "overview"))
    if section not in {"overview", "network", "users", "access", "gateways", "routing", "events"}:
        section = "overview"
    return redirect("/manage/" + slug + "#" + section)


def invitation_user(value, kind):
    user = db.one("SELECT u.login,u.admin FROM invitations i JOIN users u ON u.id=i.user_id WHERE i.token_hash=? AND i.kind=? AND i.consumed IS NULL AND i.expires>? AND u.blocked=0", (security.digest(value), kind, int(time.time())))
    if not user:
        raise ValueError("Приглашение истекло или уже использовано")
    return user


@app.get("/help-login")
def help_login(request: Request):
    return page(request, "help-login.html")


@app.get("/reset/{value}")
def reset_page(value: str, request: Request):
    invitation = invitation_user(value, "reset")
    csrf = security.token()
    response = page(request, "reset.html", value=value, csrf=csrf, login=invitation["login"], password_min=security.password_minimum(bool(invitation["admin"])))
    response.set_cookie("ruvpn_login", csrf, max_age=900, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/reset/{value}")
async def reset_password(value: str, request: Request):
    form = await request.form(max_fields=5, max_files=0)
    if not security.csrf_ok(form.get("csrf"), request.cookies.get("ruvpn_login", "")):
        raise ValueError("Обновите страницу восстановления")
    if not security.allow_attempt("reset:" + (request.client.host if request.client else "unknown"), 20):
        raise ValueError("Слишком много попыток")
    await asyncio.to_thread(control.consume_invitation, value, password=str(form.get("password", "")), reset=True)
    return redirect("/login")


@app.get("/api/state")
def api_state(user=Depends(current)):
    return panel_state(user)


@app.get("/api/manage/{slug}")
def api_manage(slug: str, request: Request, user=Depends(admin)):
    if slug != public()["admin_slug"]:
        raise HTTPException(404)
    period = request.query_params.get("period", "24h")
    if period not in {"24h", "7d", "30d"}:
        raise ValueError("Неизвестный период")
    return panel_state(user, administrative=True, period=period)


async def passkey_body(request, csrf):
    data = await request.json()
    if not isinstance(data, dict) or not security.csrf_ok(data.get("csrf"), csrf):
        raise ValueError("Обновите страницу и повторите действие")
    return data


def challenge_cookie(response, value):
    response.set_cookie("chimera_challenge", value, max_age=300, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/api/passkeys/login/begin")
async def passkey_login_begin(request: Request):
    await passkey_body(request, request.cookies.get("ruvpn_login", ""))
    address = request.client.host if request.client else "unknown"
    if not security.allow_attempt("passkey-login:" + address, 25):
        raise ValueError("Слишком много попыток входа")
    options, value = passkeys.begin()
    return challenge_cookie(JSONResponse(options), value)


@app.post("/api/passkeys/login/complete")
async def passkey_login_complete(request: Request):
    data = await passkey_body(request, request.cookies.get("ruvpn_login", ""))
    user_id, verified_hash = await asyncio.to_thread(passkeys.finish_login, request.cookies.get("chimera_challenge", ""), data.get("credential"))
    remember = bool(data.get("remember"))
    response = JSONResponse({"redirect": "/"})
    response.set_cookie("ruvpn_session", security.new_session(user_id, remember=remember, verified_hash=verified_hash), max_age=604800 if remember else 43200, secure=True, httponly=True, samesite="lax")
    for cookie in ("chimera_challenge", "ruvpn_login"):
        response.delete_cookie(cookie, secure=True, httponly=True, samesite="strict")
    return response


@app.post("/api/passkeys/register/begin")
async def passkey_register_begin(request: Request, user=Depends(current)):
    data = await passkey_body(request, user["csrf"])
    if not security.allow_attempt("passkey-register:" + str(user["id"]), 8):
        raise ValueError("Слишком много попыток")
    if not await asyncio.to_thread(security.verify_password, user["password"], data.get("password", "")):
        raise ValueError("Текущий пароль не подошёл")
    options, value = passkeys.begin(user)
    return challenge_cookie(JSONResponse(options), value)


@app.post("/api/passkeys/register/complete")
async def passkey_register_complete(request: Request, user=Depends(current)):
    data = await passkey_body(request, user["csrf"])
    await asyncio.to_thread(passkeys.finish_registration, request.cookies.get("chimera_challenge", ""), user, data.get("credential"), data.get("label", ""))
    response = JSONResponse({"redirect": "/account"})
    response.delete_cookie("chimera_challenge", secure=True, httponly=True, samesite="strict")
    return response
