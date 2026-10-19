from __future__ import annotations

import asyncio
import contextlib
import logging
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from . import control, db, profiles, security
from .config import ETC, public, read_json

log = logging.getLogger("ruvpn.bot")
PAGE_SIZE = 6
FORMATS = {"amnezia": "AmneziaVPN · CHIMERA", "awg": "AmneziaWG · .conf", "vless": "VLESS · Happ / v2rayNG", "singbox": "sing-box · JSON"}


@dataclass
class PendingInput:
    kind: str
    expires: float


waiting: dict[int, PendingInput] = {}


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows])


def with_home(rows, back="devices:active:0"):
    if back == "home":
        return keyboard(rows + [[("← Главная", "home")]])
    return keyboard(rows + [[("← Назад", back), ("⌂ Главная", "home")]])


def menu(admin=False):
    rows = [[("Мои устройства", "devices:active:0")], [("Добавить устройство", "add")], [("Сеть и маршруты", "network"), ("Инструкция", "guide")], [("Учётная запись", "account")]]
    if admin:
        rows.append([("Управление", "manage")])
    return keyboard(rows)


def bound(telegram_id):
    user = db.one("SELECT * FROM users WHERE telegram_id=? AND blocked=0", (telegram_id,))
    if not user:
        raise ValueError("Привяжите Telegram в личном кабинете: Учётная запись → Telegram-бот.")
    return user


def device_status(device):
    if device["state"] == "failed":
        return "Изменение не применено"
    if device["state"] != "applied":
        return "Применяется"
    return "Доступ разрешён" if device["desired"] else "Доступ отозван"


async def screen(message, text, markup):
    # Keep navigation in one message. Media requested by the user stays in chat.
    if message.from_user and message.from_user.is_bot and message.text:
        try:
            await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            if "can't be edited" not in str(exc).lower() and "message to edit not found" not in str(exc).lower():
                raise
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def home(message, user, note=""):
    text = "CHIMERA · Личный VPN\n\nУстройства, профили подключения и инструкции."
    if note:
        text = note + "\n\n" + text
    await screen(message, text, menu(user["admin"]))


async def device_list(message, user, kind="active", page=0, note=""):
    if kind not in {"active", "revoked"} or page < 0:
        raise ValueError("Откройте список устройств заново")
    desired = int(kind == "active")
    devices = db.rows("SELECT id,name,state,desired FROM devices WHERE user_id=? AND desired=? ORDER BY created DESC,id", (user["id"], desired))
    pages = max(1, (len(devices) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages - 1)
    heading = "Мои устройства" if desired else "Отозванные устройства"
    text = f"CHIMERA · {heading}\nВсего: {len(devices)}"
    if desired:
        text += f" / {user['device_limit']}"
    text += f" · Страница {page + 1}/{pages}\n\n"
    text += "Выберите устройство." if devices else ("Пока нет устройств. Создайте профиль для первого подключения." if desired else "Отозванных устройств нет.")
    if note:
        text = note + "\n\n" + text
    rows = [[(d["name"][:35] + (" · ошибка" if d["state"] == "failed" else ""), "device:" + d["id"])] for d in devices[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    pagination = []
    if page:
        pagination.append(("‹ Предыдущая", f"devices:{kind}:{page - 1}"))
    if page + 1 < pages:
        pagination.append(("Следующая ›", f"devices:{kind}:{page + 1}"))
    if pagination:
        rows.append(pagination)
    if desired:
        rows += [[("+ Добавить устройство", "add")], [("Отозванные", "devices:revoked:0")]]
    else:
        if any(d["state"] == "applied" for d in devices):
            rows.append([("Очистить отозванные", "clear-ask")])
        rows.append([("← Действующие устройства", "devices:active:0")])
    rows.append([("⌂ Главная", "home")])
    await screen(message, text, keyboard(rows))


async def device_card(message, user, device_id, note=""):
    device = control.device_for(user["id"], device_id)
    text = f"CHIMERA · {device['name']}\n{device_status(device)}"
    rows = []
    if device["desired"]:
        if device["state"] == "applied":
            rows.append([("Получить профиль", "protocol:" + device_id)])
        rows.append([("Отозвать доступ", "revoke-ask:" + device_id)])
    elif device["state"] == "applied":
        text += "\n\nПрофиль больше не действует. Его можно удалить из списка."
        rows.append([("Удалить профиль", "delete-ask:" + device_id)])
    else:
        text += "\n\nОтзыв ещё не подтверждён сервером. Удаление станет доступно после успешного применения."
    if device["state"] == "failed":
        text += "\n\nОбратитесь к владельцу: изменение конфигурации не применилось."
    back = "devices:active:0" if device["desired"] else "devices:revoked:0"
    await screen(message, (note + "\n\n" if note else "") + text, with_home(rows, back))


async def protocol_picker(message, user, device_id):
    device = control.device_for(user["id"], device_id)
    if not device["desired"] or device["state"] != "applied":
        raise ValueError("Профиль недоступен. Откройте карточку устройства заново")
    rows = [[(label, f"profile:{protocol}:{device_id}")] for protocol, label in FORMATS.items()]
    await screen(message, f"{device['name']} · Способ импорта\n\nAmneziaVPN добавит сервер с именем CHIMERA. Для Happ и v2rayNG выберите VLESS.", with_home(rows, "device:" + device_id))


async def owner_menu(message, user):
    control.require_admin(user["id"])
    await screen(message, "CHIMERA · Управление\n\nПользователи и приглашения. Маршрутизация, статистика и остальные настройки доступны в панели.", with_home([[("Пользователи", "users:0")], [("Пригласить пользователя", "invite-new")], [("Панель владельца", "owner-panel")]], "home"))


async def users_list(message, user, page=0):
    control.require_admin(user["id"])
    people = db.rows("SELECT id,login,blocked FROM users ORDER BY id")
    pages = max(1, (len(people) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    rows = [[(("⛔ " if p["blocked"] else "") + p["login"], "user:" + str(p["id"]))] for p in people[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    pagination = []
    if page:
        pagination.append(("‹ Предыдущая", f"users:{page - 1}"))
    if page + 1 < pages:
        pagination.append(("Следующая ›", f"users:{page + 1}"))
    if pagination:
        rows.append(pagination)
    rows.append([("Пригласить пользователя", "invite-new")])
    await screen(message, f"Пользователи · {len(people)}\nСтраница {page + 1}/{pages}", with_home(rows, "manage"))


def managed_user(actor, user_id):
    control.require_admin(actor)
    target = db.one("SELECT id,login,blocked,password IS NOT NULL AS activated,device_limit FROM users WHERE id=?", (int(user_id),))
    if not target:
        raise ValueError("Пользователь не найден")
    return target


async def user_card(message, user, user_id, note=""):
    target = managed_user(user["id"], user_id)
    count = db.one("SELECT COUNT(*) AS n FROM devices WHERE user_id=? AND desired=1", (target["id"],))["n"]
    text = f"Пользователь: {target['login']}\nДоступ: {'заблокирован' if target['blocked'] else 'разрешён'}\nУстройства: {count} / {target['device_limit']}"
    uid = str(target["id"])
    rows = []
    if not target["blocked"]:
        rows.append([("Восстановить вход" if target["activated"] else "Новое приглашение", ("reset:" if target["activated"] else "invite:") + uid)])
    if target["id"] != user["id"]:
        rows.append([("Разблокировать" if target["blocked"] else "Заблокировать доступ", ("unblock-ask:" if target["blocked"] else "block-ask:") + uid)])
    if count:
        rows.append([("Отозвать все устройства", "all-ask:" + uid)])
    await screen(message, (note + "\n\n" if note else "") + text, with_home(rows, "users:0"))


async def notify(bot):
    latest = db.one("SELECT COALESCE(MAX(id),0) AS id FROM events")["id"]
    last_sent = 0.0
    while True:
        try:
            events = db.rows("SELECT * FROM events WHERE id>? AND kind IN ('path_changed','foreign_down','foreign_recovered','hop_down','hop_recovered') ORDER BY id", (latest,))
            if events and time.monotonic() - last_sent >= 120:
                event = events[-1]
                for user in db.rows("SELECT telegram_id FROM users WHERE admin=1 AND blocked=0 AND telegram_id IS NOT NULL"):
                    await bot.send_message(user["telegram_id"], "CHIMERA · Шлюз\n" + event["detail"], reply_markup=keyboard([[("Главная", "home"), ("Управление", "manage")]]))
                latest = event["id"]
                last_sent = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Уведомление Telegram отложено")
        await asyncio.sleep(30)


async def run():
    cfg = read_json(ETC / "control.json")
    if not cfg["telegram"]["enabled"] or not cfg.get("bot_token"):
        return
    proxy = None
    if cfg["telegram"]["route"] == "foreign" and cfg.get("topology", {}).get("entry", "ru") == "ru":
        auth = cfg["proxy_auth"]
        proxy = f"http://{auth['username']}:{auth['password']}@127.0.0.1:10083"
    session = AiohttpSession(proxy=proxy)
    bot = Bot(cfg["bot_token"], session=session)
    dp = Dispatcher()
    dp.message.filter(F.chat.type == "private")
    locks = defaultdict(asyncio.Lock)

    async def error(message, telegram_id, exc):
        user = db.one("SELECT admin FROM users WHERE telegram_id=? AND blocked=0", (telegram_id,))
        text = str(exc) if isinstance(exc, ValueError) else "Не удалось выполнить действие. Откройте меню и повторите попытку."
        if user:
            await screen(message, text, menu(user["admin"]))
        else:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть личный кабинет", url=public()["url"])]])
            await screen(message, text, markup)

    @dp.message(CommandStart())
    async def start(message: Message):
        waiting.pop(message.from_user.id, None)
        try:
            pieces = (message.text or "").split(maxsplit=1)
            if len(pieces) == 2:
                if not security.allow_attempt("tg-bind:" + str(message.from_user.id), 10):
                    raise ValueError("Слишком много попыток привязки")
                await asyncio.to_thread(control.consume_invitation, pieces[1], telegram_id=message.from_user.id)
            await home(message, bound(message.from_user.id))
        except ValueError as exc:
            await error(message, message.from_user.id, exc)

    @dp.message(Command("menu", "cancel", "devices", "help"))
    async def command_menu(message: Message):
        waiting.pop(message.from_user.id, None)
        try:
            user = bound(message.from_user.id)
            command = (message.text or "").split()[0].split("@")[0]
            if command == "/devices":
                await device_list(message, user)
            else:
                await home(message, user, "Ввод отменён." if command == "/cancel" else "")
        except ValueError as exc:
            await error(message, message.from_user.id, exc)

    @dp.message(Command("invite", "block"))
    async def owner_command(message: Message):
        waiting.pop(message.from_user.id, None)
        try:
            user = bound(message.from_user.id)
            control.require_admin(user["id"])
            pieces = (message.text or "").split()
            if len(pieces) != 2:
                raise ValueError("Команда: /invite login или /block login. Можно использовать меню «Управление».")
            if pieces[0].split("@")[0] == "/invite":
                uid, value = await asyncio.to_thread(control.create_user, user["id"], pieces[1], min(3, public()["limits"]["devices"]))
                await show_invitation(message, uid, value)
            else:
                target = db.one("SELECT id FROM users WHERE login=?", (pieces[1].lower(),))
                if not target:
                    raise ValueError("Пользователь не найден")
                await confirm_user_action(message, user, "block", target["id"])
        except ValueError as exc:
            await error(message, message.from_user.id, exc)

    async def show_invitation(message, uid, value, reset=False):
        title = "Восстановление входа" if reset else "Приглашение в CHIMERA"
        note = "Новый пароль завершит сеансы и удалит ключи входа. VPN-профили сохранятся." if reset else "Пользователь сам задаст пароль от 8 символов."
        await screen(message, title + "\n\nОдноразовая ссылка на 24 часа:\n" + public()["url"] + ("/reset/" if reset else "/join/") + value + "\n\n" + note, with_home([], "user:" + str(uid)))

    async def confirm_user_action(message, user, action, uid):
        target = managed_user(user["id"], uid)
        if action in {"block", "unblock"} and target["id"] == user["id"]:
            raise ValueError("Нельзя блокировать собственную учётную запись")
        titles = {"block": "Заблокировать доступ", "unblock": "Разблокировать доступ", "all": "Отозвать все устройства"}
        note = "Изменение применяется на сервере и может кратко перезапустить VLESS-сессии."
        await screen(message, f"{titles[action]}: {target['login']}?\n\n{note}", with_home([[("Да, подтвердить", f"{action}:{target['id']}")]], "user:" + str(target["id"])))

    @dp.callback_query()
    async def callback(query: CallbackQuery):
        with contextlib.suppress(TelegramBadRequest):
            await query.answer()
        if not query.message or query.message.chat.type != "private":
            return
        async with locks[query.from_user.id]:
            waiting.pop(query.from_user.id, None)
            try:
                user = bound(query.from_user.id)
                if not security.allow_attempt("tg-actions:" + str(query.from_user.id), 80, 60):
                    raise ValueError("Слишком много действий. Подождите минуту")
                data = query.data or ""
                # Old messages remain navigable after an update.
                aliases = {"devices": "devices:active:0", "invite-help": "manage", "block-help": "manage"}
                data = aliases.get(data, data)
                if data.startswith("link:"):
                    data = "profile:" + data.split(":", 1)[1]
                parts = data.split(":")
                action = parts[0]
                message = query.message
                if data == "home":
                    await home(message, user)
                elif action == "devices" and len(parts) == 3:
                    await device_list(message, user, parts[1], int(parts[2]))
                elif data in {"add", "invite-new"}:
                    if data == "invite-new":
                        control.require_admin(user["id"])
                    waiting[query.from_user.id] = PendingInput(data, time.monotonic() + 300)
                    text = "Отправьте название нового устройства одним сообщением (1–48 символов)." if data == "add" else "Отправьте логин нового пользователя (3–32 латинских символа, цифры, . _ -)."
                    await screen(message, text + "\n\nВвод действует 5 минут. Для отмены нажмите «Назад» или /cancel.", with_home([], "devices:active:0" if data == "add" else "manage"))
                elif data == "guide":
                    await screen(message, "Подключение к CHIMERA\n\n1. Создайте устройство.\n2. Получите профиль для AmneziaVPN или VLESS.\n3. Импортируйте его в клиент и подключитесь там.\n\nAWG требует поддержки 3.1. Для VLESS включите полный VPN/TUN и DNS через VPN.\n\nПодробная инструкция:\n" + public()["url"] + "/guide", with_home([[("Мои устройства", "devices:active:0")]], "home"))
                elif data == "network":
                    info = public()
                    reverse = info.get("topology", {}).get("entry", "ru") == "foreign"
                    monitor = json.loads(db.setting("monitor", "{}"))
                    stale = time.time() - monitor.get("checked_at", 0) > max(90, cfg["paths"]["interval"] * 3)
                    selected = monitor.get("active", "unknown")
                    label = {"primary": "VLESS REALITY", "backup": "Hysteria2", "closed": "Закрыт"}.get(selected, "Не проверен")
                    state = monitor.get(selected, {}).get("state", "unknown")
                    health = "Нет свежих данных" if stale else {"available": "Доступность подтверждена", "unavailable": "Недоступен"}.get(state, "Доступность не подтверждена")
                    routes = "Российские сервисы из списков → через сервер RU.\nОстальное → прямо с зарубежного входа.\n\nПри отказе обоих путей до RU российская ветка закрывается. Зарубежный интернет продолжает работать напрямую." if reverse else "Российские сервисы из списков → напрямую из RU.\nОстальное → через зарубежный выход.\n\nПри отказе обоих зарубежных путей зарубежная ветка закрывается."
                    await screen(message, "CHIMERA · Сеть\nВход: " + ("зарубежный" if reverse else "Россия") + "\n" + info["endpoint"] + "\n\n" + routes + "\n\nМежсерверный путь: " + label + "\n" + health, with_home([[("Мои устройства", "devices:active:0")]], "home"))
                elif data == "account":
                    await screen(message, f"Учётная запись CHIMERA\nЛогин: {user['login']}\nTelegram привязан.\n\nПароль, ключи входа и отвязка Telegram:\n" + public()["url"] + "/account", with_home([], "home"))
                elif action == "device" and len(parts) == 2:
                    await device_card(message, user, parts[1])
                elif action == "protocol" and len(parts) == 2:
                    await protocol_picker(message, user, parts[1])
                elif action in {"profile", "chat", "qr"} and len(parts) == 3:
                    protocol, device_id = parts[1:]
                    if protocol not in FORMATS:
                        raise ValueError("Выберите формат профиля заново")
                    if action == "profile":
                        link = control.download_link(user["id"], device_id, protocol)
                        markup = with_home([[("Отправить файл в чат", f"chat:{protocol}:{device_id}")]] + ([[("Отправить QR в чат", f"qr:{protocol}:{device_id}")]] if protocol != "singbox" else []), "protocol:" + device_id)
                        markup.inline_keyboard.insert(0, [InlineKeyboardButton(text="Скачать по HTTPS", url=link)])
                        await screen(message, FORMATS[protocol] + "\n\nОдноразовая ссылка действует 5 минут и расходуется при скачивании.\n\nФайл и QR содержат личные ключи. Отправка в чат сохранит их в Telegram; выбирайте её осознанно.", markup)
                    else:
                        name, text = profiles.profile(user["id"], device_id, protocol)
                        markup = with_home([], "protocol:" + device_id)
                        caption = "CHIMERA · Личный профиль. Не пересылайте другим."
                        if action == "chat":
                            await message.answer_document(BufferedInputFile(text.encode(), filename=name), caption=caption, reply_markup=markup)
                        else:
                            await message.answer_photo(BufferedInputFile(profiles.qr_png(text), filename="CHIMERA.png"), caption=caption, reply_markup=markup)
                elif action in {"revoke-ask", "delete-ask"} and len(parts) == 2:
                    device = control.device_for(user["id"], parts[1])
                    deleting = action == "delete-ask"
                    if deleting and (device["desired"] or device["state"] != "applied"):
                        raise ValueError("Сначала дождитесь успешного отзыва на сервере")
                    text = f"{'Удалить отозванный профиль' if deleting else 'Отозвать доступ'} «{device['name']}»?\n\n" + ("Запись и сохранённые ключи будут удалены." if deleting else "Доступ отключится на сервере. VLESS-сессии кратко перезапустятся.")
                    await screen(message, text, with_home([[("Да, удалить" if deleting else "Да, отозвать", ("delete:" if deleting else "revoke:") + device["id"])]], "device:" + device["id"]))
                elif action == "revoke" and len(parts) == 2:
                    await asyncio.to_thread(control.revoke_device, user["id"], parts[1])
                    await device_card(message, user, parts[1], "Доступ отозван на сервере.")
                elif action == "delete" and len(parts) == 2:
                    await asyncio.to_thread(control.delete_revoked, user["id"], parts[1])
                    await device_list(message, user, "revoked", note="Отозванный профиль удалён.")
                elif data == "clear-ask":
                    count = db.one("SELECT COUNT(*) AS n FROM devices WHERE user_id=? AND desired=0 AND state='applied'", (user["id"],))["n"]
                    await screen(message, f"Удалить {count} успешно отозванных профилей и их сохранённые ключи?", with_home([[("Да, очистить", "clear-do")]], "devices:revoked:0"))
                elif data == "clear-do":
                    count = await asyncio.to_thread(control.delete_revoked, user["id"])
                    await device_list(message, user, "revoked", note=f"Удалено профилей: {count}.")
                elif data == "manage":
                    await owner_menu(message, user)
                elif data == "owner-panel":
                    control.require_admin(user["id"])
                    await screen(message, "Панель владельца CHIMERA:\n" + public()["url"] + "/manage/" + public()["admin_slug"], with_home([], "manage"))
                elif action == "users" and len(parts) == 2:
                    await users_list(message, user, int(parts[1]))
                elif action == "user" and len(parts) == 2:
                    await user_card(message, user, int(parts[1]))
                elif action in {"invite", "reset"} and len(parts) == 2:
                    target = managed_user(user["id"], parts[1])
                    value = control.invite(user["id"], target["id"], "reset" if action == "reset" else "join")
                    await show_invitation(message, target["id"], value, reset=action == "reset")
                elif action in {"block-ask", "unblock-ask", "all-ask"} and len(parts) == 2:
                    await confirm_user_action(message, user, action.removesuffix("-ask"), int(parts[1]))
                elif action in {"block", "unblock", "all"} and len(parts) == 2:
                    target = managed_user(user["id"], parts[1])
                    if action == "all":
                        await asyncio.to_thread(control.revoke_all, user["id"], target["id"])
                    else:
                        await asyncio.to_thread(control.block_user, user["id"], target["id"], action == "block")
                    await user_card(message, user, target["id"], "Изменение применено на сервере.")
                else:
                    await home(message, user, "Меню обновилось. Выберите действие заново.")
            except Exception as exc:
                if not isinstance(exc, ValueError):
                    log.warning("Действие Telegram не выполнено: %s", type(exc).__name__)
                await error(query.message, query.from_user.id, exc)

    @dp.message(F.text)
    async def entered_text(message: Message):
        async with locks[message.from_user.id]:
            try:
                user = bound(message.from_user.id)
                pending = waiting.get(message.from_user.id)
                if not pending or pending.expires < time.monotonic() or (message.text or "").startswith("/"):
                    waiting.pop(message.from_user.id, None)
                    await home(message, user, "Выберите действие в меню.")
                    return
                if not security.allow_attempt("tg-input:" + str(message.from_user.id), 20, 60):
                    raise ValueError("Слишком много попыток. Подождите минуту")
                try:
                    if pending.kind == "add":
                        request_key = f"tg_{message.from_user.id}_{message.message_id}".ljust(12, "0")
                        device_id = await asyncio.to_thread(control.create_device, user["id"], message.text, request_key)
                        waiting.pop(message.from_user.id, None)
                        await device_card(message, user, device_id, "Устройство создано. Конфигурация применена.")
                    else:
                        control.require_admin(user["id"])
                        uid, value = await asyncio.to_thread(control.create_user, user["id"], message.text, min(3, public()["limits"]["devices"]))
                        waiting.pop(message.from_user.id, None)
                        await show_invitation(message, uid, value)
                except ValueError as exc:
                    await screen(message, str(exc) + "\n\nОтправьте исправленное название или нажмите «Назад».", with_home([], "devices:active:0" if pending.kind == "add" else "manage"))
            except Exception as exc:
                if not isinstance(exc, ValueError):
                    log.warning("Ввод Telegram не обработан: %s", type(exc).__name__)
                await error(message, message.from_user.id, exc)

    try:
        await bot.set_my_name(name="CHIMERA")
        await bot.set_my_description(description="Частная VPN-сеть CHIMERA. Привяжите Telegram в личном кабинете, чтобы получать профили и управлять своими устройствами.")
        await bot.set_my_short_description(short_description="Личный доступ к CHIMERA: устройства, профили подключения и помощь.")
        await bot.set_my_commands(commands=[
            BotCommand(command="start", description="Главная и привязка Telegram"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="devices", description="Мои устройства"),
            BotCommand(command="cancel", description="Отменить ввод"),
            BotCommand(command="help", description="Помощь и меню"),
        ])
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("Описание Telegram-бота не обновлено; запуск продолжается")
    notices = asyncio.create_task(notify(bot))
    try:
        await dp.start_polling(bot, handle_signals=False, close_bot_session=False, allowed_updates=["message", "callback_query"])
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("Telegram недоступен; панель и VPN продолжают работу")
    finally:
        notices.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notices
        await session.close()
