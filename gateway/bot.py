from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from . import control, db, profiles, security
from .config import ETC, public, read_json

log = logging.getLogger("ruvpn.bot")
waiting = {}


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows])


def menu(admin=False):
    rows = [[("Мои устройства", "devices"), ("Добавить устройство", "add")], [("Инструкция", "guide")]]
    if admin:
        rows += [[("Приглашения", "invite-help"), ("Блокировка", "block-help")]]
    return keyboard(rows)


def bound(telegram_id):
    user = db.one("SELECT * FROM users WHERE telegram_id=? AND blocked=0", (telegram_id,))
    if not user:
        raise ValueError("Сначала привяжите Telegram по приглашению из личного кабинета")
    return user


async def notify(bot):
    latest = db.one("SELECT COALESCE(MAX(id),0) AS id FROM events")["id"]
    last_sent = 0.0
    while True:
        try:
            events = db.rows("SELECT * FROM events WHERE id>? AND kind IN ('path_changed','foreign_down','foreign_recovered') ORDER BY id", (latest,))
            if events and time.monotonic() - last_sent >= 120:
                event = events[-1]
                for user in db.rows("SELECT telegram_id FROM users WHERE admin=1 AND blocked=0 AND telegram_id IS NOT NULL"):
                    await bot.send_message(user["telegram_id"], "Шлюз: " + event["detail"])
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
    if cfg["telegram"]["route"] == "foreign":
        auth = cfg["proxy_auth"]
        proxy = f"http://{auth['username']}:{auth['password']}@127.0.0.1:10083"
    session = AiohttpSession(proxy=proxy)
    bot = Bot(cfg["bot_token"], session=session)
    dp = Dispatcher()
    dp.message.filter(F.chat.type == "private")

    async def respond_error(destination, exc):
        await destination.answer(str(exc))

    @dp.message(CommandStart())
    async def start(message: Message):
        try:
            pieces = (message.text or "").split(maxsplit=1)
            if len(pieces) == 2:
                if not security.allow_attempt("tg-bind:" + str(message.from_user.id), 10):
                    raise ValueError("Слишком много попыток привязки")
                await asyncio.to_thread(control.consume_invitation, pieces[1], telegram_id=message.from_user.id)
            user = bound(message.from_user.id)
            await message.answer("Ваш личный VPN. Профили доступны здесь и в панели.", reply_markup=menu(user["admin"]))
        except ValueError as e:
            await respond_error(message, e)

    @dp.message(Command("invite"))
    async def invite(message: Message):
        try:
            user = bound(message.from_user.id)
            control.require_admin(user["id"])
            pieces = (message.text or "").split()
            if len(pieces) != 2:
                raise ValueError("Использование: /invite login")
            _, value = await asyncio.to_thread(control.create_user, user["id"], pieces[1], 3)
            await message.answer("Логин: " + pieces[1] + "\nОдноразовое приглашение на 24 часа:\n" + public()["url"] + "/join/" + value, disable_web_page_preview=True)
        except ValueError as e:
            await respond_error(message, e)

    @dp.message(Command("block"))
    async def block(message: Message):
        try:
            admin = bound(message.from_user.id)
            control.require_admin(admin["id"])
            pieces = (message.text or "").split()
            if len(pieces) != 2:
                raise ValueError("Использование: /block login")
            target = db.one("SELECT id FROM users WHERE login=?", (pieces[1].lower(),))
            if not target:
                raise ValueError("Пользователь не найден")
            await asyncio.to_thread(control.block_user, admin["id"], target["id"], True)
            await message.answer("Доступ заблокирован на сервере.")
        except ValueError as e:
            await respond_error(message, e)

    @dp.callback_query()
    async def callback(query: CallbackQuery):
        if not query.message or query.message.chat.type != "private":
            await query.answer()
            return
        try:
            user = bound(query.from_user.id)
            if not security.allow_attempt("tg-actions:" + str(query.from_user.id), 80, 60):
                raise ValueError("Слишком много действий. Подождите минуту")
            data = query.data or ""
            await query.answer()
            message = query.message
            if data == "devices":
                devices = db.rows("SELECT id,name,state FROM devices WHERE user_id=? AND desired=1 ORDER BY created", (user["id"],))
                if not devices:
                    await message.answer("Устройств пока нет.", reply_markup=menu(user["admin"]))
                for device in devices:
                    await message.answer(device["name"] + " · " + device["state"], reply_markup=keyboard([[("Получить профиль", "device:" + device["id"])], [("Отозвать устройство", "revoke-ask:" + device["id"])]]))
            elif data == "add":
                waiting[query.from_user.id] = time.monotonic() + 300
                await message.answer("Отправьте название нового устройства одним сообщением.")
            elif data == "guide":
                await message.answer("Импортируйте профиль в совместимый клиент. Для VLESS включите полный VPN/TUN, DNS через VPN и блокировку IPv6. AWG требует поддержки версии 3.1.\n" + public()["url"] + "/guide", disable_web_page_preview=True)
            elif data in {"invite-help", "block-help"}:
                control.require_admin(user["id"])
                await message.answer("Создать пользователя и приглашение: /invite login\nБлокировать пользователя с отзывом доступа: /block login\nОстальные настройки — в панели.")
            elif data.startswith("device:"):
                device_id = data.split(":", 1)[1]
                control.device_for(user["id"], device_id)
                await message.answer("Выберите профиль:", reply_markup=keyboard([[("AmneziaWG 3.1", "link:awg:" + device_id)], [("VLESS URI", "link:vless:" + device_id)], [("sing-box VPN JSON", "link:singbox:" + device_id)]]))
            elif data.startswith("link:"):
                _, protocol, device_id = data.split(":", 2)
                link = control.download_link(user["id"], device_id, protocol)
                await message.answer("Одноразовая ссылка на 5 минут:\n" + link + "\n\nОтправка файла в чат сохранит ключ в Telegram. Выберите её только если согласны.", disable_web_page_preview=True, reply_markup=keyboard([[("Отправить файл в Telegram", "chat:" + protocol + ":" + device_id)]]))
            elif data.startswith("chat:"):
                _, protocol, device_id = data.split(":", 2)
                name, text = profiles.profile(user["id"], device_id, protocol)
                await message.answer_document(BufferedInputFile(text.encode(), filename=name), caption="Личный ключ доступа. Не пересылайте другим.")
            elif data.startswith("revoke-ask:"):
                device_id = data.split(":", 1)[1]
                control.device_for(user["id"], device_id)
                await message.answer("Отозвать доступ этого устройства? Текущие VLESS-сессии кратко перезапустятся.", reply_markup=keyboard([[("Да, отозвать", "revoke:" + device_id)], [("Отмена", "devices")]]))
            elif data.startswith("revoke:"):
                await asyncio.to_thread(control.revoke_device, user["id"], data.split(":", 1)[1])
                await message.answer("Доступ отозван на сервере.")
        except ValueError as e:
            await query.message.answer(str(e))

    @dp.message(F.text)
    async def device_name(message: Message):
        try:
            user = bound(message.from_user.id)
            expiry = waiting.pop(message.from_user.id, 0)
            if expiry < time.monotonic():
                await message.answer("Выберите действие.", reply_markup=menu(user["admin"]))
                return
            request_key = "tg_" + str(message.from_user.id) + "_" + str(message.message_id)
            request_key = request_key.ljust(12, "0")
            device_id = await asyncio.to_thread(control.create_device, user["id"], message.text, request_key)
            await message.answer("Устройство создано, конфигурация применена.", reply_markup=keyboard([[("Получить профиль", "device:" + device_id)]]))
        except ValueError as e:
            await respond_error(message, e)

    notices = asyncio.create_task(notify(bot))
    try:
        # Never let bot failures terminate the panel or data plane.
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
