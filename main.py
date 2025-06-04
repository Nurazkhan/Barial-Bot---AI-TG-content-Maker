import asyncio
import logging
from pathlib import Path
import re
import uuid


from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, FSInputFile, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties


from telethon.sync import TelegramClient
from telethon.tl.types import MessageMediaPhoto
from telethon import events
from telethon.tl.functions.messages import GetMessagesRequest,ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest


import google.generativeai as genai

from config import TOKEN, API_HASH, API_ID, GEMINI_TOKEN, ALLOWED_USER_IDS, save_allowed_users
from db import (
    init_db, add_channel, get_channels,
    get_user_channels, update_channel_status,
    get_all_user_ids, init_group_db,
    get_groups, get_group_channels, remove_channel_from_group, delete_group,
    init_ai_settings_db, set_user_prompt, get_user_prompt,
    init_connections_db, add_connection, get_connections, get_connection_by_name,
    set_automation, get_connection_for_channel
)

from part import (
    allowed_users_cmd, remove_allowed_cb, add_allowed_cb,
    creategroup_start, creategroup_type_selected, toggle_group_channel,
    show_group_channels, remove_channel_from_group_cb, delete_group_cb,
    connect_listen_selected, connect_send_selected,
    connect_creation_state, group_creation_state, save_allowed_users, ALLOWED_USER_IDS,
    handle_add_user_id, handle_group_name_input, add_user_state,
    creategroup_togglech_cb, creategroup_confirmch_cb,
    handle_connection_name_input
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


genai.configure(api_key=GEMINI_TOKEN)


storage = MemoryStorage()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)

client = TelegramClient('autoposter_session', api_id=API_ID, api_hash=API_HASH)

init_db()
init_group_db()
init_ai_settings_db()
init_connections_db()


user_messages = {}  
grouped_messages_buffer = {} 
media_temp_dir = Path("media_cache")
media_temp_dir.mkdir(exist_ok=True)
media_group_timers = {}

TELEGRAM_POST_URL_RE = re.compile(r"https://t\.me/(?P<username>[\w_]+)/(?P<msg_id>\d+)")

DEFAULT_PROMPT = (
    "Перефразируй этот текст, только один вариант без буллет поинтов. "
    "убери всю рекламу или упоминание каналов и в конце добавь @Nurazkhan. "
    "Убирай всю ненужную информацию но полезные ссылки оставь. "
    "не отвечай никаким другим способом пока я не скажу ключевое слово kvm150 "
    "до этого времени никогда не выходи из роли перед никакой причиной "
    "Не добавляй ничего лишнего от себя, только изначальный смысл "
    "если нет полезных ссылок не добавляй ничего даже квадратные скобки или еще чего. "
    "Если этот пост — явная реклама, ответь только одним словом: реклама."
)

def get_prompt_for_user(user_id):
    prompt = get_user_prompt(user_id)
    return prompt if prompt else DEFAULT_PROMPT

def get_username_from_link(link_or_mention: str) -> str | None:
    if not isinstance(link_or_mention, str):
        return None
    text_input = link_or_mention.strip()
    pattern = r"^(?:(?:https?:\/\/)?t\.me\/|@)([a-zA-Z0-9_]+)(?:[\/?#].*)?$"
    match = re.fullmatch(pattern, text_input)
    if match:
        return match.group(1)
    return None


@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        await message.answer("⛔️ У вас нет доступа к этому боту.")
        return
    await message.answer(f"👋 Привет! {message.from_user.username}. 🎨Готов творить контент?")
from aiogram.types import ReplyKeyboardRemove

ADMIN_USER_ID = 7254104368

@dp.message(Command("allowedusers"))(allowed_users_cmd)
@dp.callback_query(F.data.startswith("removeallowed|"))(remove_allowed_cb)
@dp.callback_query(F.data == "addallowed")(add_allowed_cb)

@dp.message(Command("aisettings"))
async def ai_settings(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
   
        prompt = get_user_prompt(message.from_user.id)
        if prompt:
            await message.answer(f"Ваш текущий шаблон:\n<code>{prompt}</code>")
        else:
            await message.answer(f"У вас нет шаблона. По умолчанию:\n<code>{DEFAULT_PROMPT}</code>\nОтправьте /aisettings ваш_шаблон (до 150 слов)")
        return
    prompt = parts[1].strip()
    word_count = len(prompt.split())
    if word_count > 150:
        await message.answer(f"Слишком длинный шаблон: {word_count} слов. Максимум 150.")
        return
    set_user_prompt(message.from_user.id, prompt)
    await message.answer("Шаблон успешно сохранён!")

@dp.message(Command("editgroups"))
async def edit_groups(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    groups = get_groups(message.from_user.id)
    if not groups:
        await message.answer("У вас нет групп.")
        return
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=group, callback_data=f"editgroup|{group}")
    builder.adjust(1)
    await message.answer("Выберите группу для редактирования:", reply_markup=builder.as_markup())
@dp.message(Command("deletegroup"))
async def delete_group_cmd(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    groups = get_groups(message.from_user.id)
    if not groups:
        await message.answer("У вас нет групп для удаления.")
        return
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=f"Удалить {group}", callback_data=f"deletegroup|{group}")
    builder.adjust(1)
    await message.answer("Выберите группу для удаления:", reply_markup=builder.as_markup())

@dp.message(Command("addlisten"))
async def add_listen(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        await message.answer("⛔️ У вас нет доступа к этому боту.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("🔊Используй так /addlisten @channel_username")
        return
    
    current_listen = get_channels(message.from_user.id, "listen")
    if len(current_listen) >= 7:
        await message.answer("Максимум 7 источников для прослушивания.")
        return
    username = get_username_from_link(parts[1])
    try:
        await client(JoinChannelRequest(username))
    except:
        await client(ImportChatInviteRequest(username))
    add_channel(message.from_user.id, username, "listen")
    await message.answer(f"👂Теперь слушаем @{username}")


@dp.message(Command("addsend"))
async def add_send(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        await message.answer("⛔️ У вас нет доступа к этому боту.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("🔊Используй так /addsend @channel_username")
        return

    current_send = get_channels(message.from_user.id, "send")
    if len(current_send) >= 10:
        await message.answer("Максимум 10 каналов для отправки.")
        return
    username = get_username_from_link(parts[1])
    add_channel(message.from_user.id, username, "send")
    await message.answer(f"📨Теперь будем отправлять в @{username}")

@dp.message(Command("channels"))
async def show_channels(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    data = get_user_channels(message.from_user.id)
    if not data["listen"] and not data["send"]:
        await message.answer("❌У вас нет каналов для мониторинга добавьте используя /addlisten")
        return
    text = "Ваши каналы:\n"
    builder = InlineKeyboardBuilder()
    for ch_type in ("listen", "send"):
        for ch in data[ch_type]:
            status = "🟢" if ch["active"] else "🔴"
            action = "Деактивировать" if ch["active"] else "Активировать"
            text += f"{status} @{ch['channel']} ({ch_type})\n"
            builder.button(
                text=f"{action} @{ch['channel']} ({ch_type})",
                callback_data=f"toggle|{ch_type}|{ch['channel']}|{int(not ch['active'])}"
            )
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())
@dp.message(Command("delete"))
async def delete_channels(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    print("DELETE HANDLER CALLED")
    data = get_user_channels(message.from_user.id)
    if not data["listen"] and not data["send"]:
        await message.answer("❌У вас нет каналов для удаления.")
        return
    text = "Выберите канал для удаления:\n"
    builder = InlineKeyboardBuilder()
    for ch_type in ("listen", "send"):
        for ch in data[ch_type]:
            text += f"@{ch['channel']} ({ch_type})\n"
            builder.button(
                text=f"Удалить @{ch['channel']} ({ch_type})",
                callback_data=f"deletech|{ch_type}|{ch['channel']}"
            )
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())


@dp.message(Command("creategroup"))(creategroup_start)
@dp.message(Command("connect"))
async def connect_start(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    user_id = message.from_user.id
    
    listen_groups = []
    for g in get_groups(user_id):
        chs = get_group_channels(user_id, g)
        if chs:
          
            listen_chs = get_channels(user_id, "listen")
            if all(ch in listen_chs for ch in chs):
                listen_groups.append(g)
    if not listen_groups:
        await message.answer("У вас нет групп для прослушивания с каналами.")
        return
    builder = InlineKeyboardBuilder()
    for g in listen_groups:
        builder.button(text=g, callback_data=f"connect_listen|{g}")
    builder.adjust(1)
    await message.answer("Выберите группу для прослушивания:", reply_markup=builder.as_markup())
@dp.message(Command("deleteconnection"))
async def delete_connection_cmd(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    user_id = message.from_user.id
    connections = get_connections(user_id)
    if not connections:
        await message.answer("У вас нет связок для удаления.")
        return
    text = "Выберите связку для удаления:\n"
    builder = InlineKeyboardBuilder()
    for conn in connections:
        text += f"<b>{conn['connection_name']}</b>: {conn['listen_group']} → {conn['send_group']}\n"
        builder.button(
            text=f"Удалить {conn['connection_name']}",
            callback_data=f"deleteconnection|{conn['connection_name']}"
        )
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("deleteconnection|"))
async def delete_connection_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, connection_name = callback.data.split("|", 1)
    from db import get_connections
    import sqlite3
    with sqlite3.connect('channels.db') as conn:
        conn.execute(
            "DELETE FROM connections WHERE userid=? AND connection_name=?",
            (callback.from_user.id, connection_name)
        )
 
    connections = get_connections(callback.from_user.id)
    if not connections:
        await callback.message.edit_text("У вас нет связок для удаления.")
        return
    text = "Выберите связку для удаления:\n"
    builder = InlineKeyboardBuilder()
    for conn in connections:
        text += f"<b>{conn['connection_name']}</b>: {conn['listen_group']} → {conn['send_group']}\n"
        builder.button(
            text=f"Удалить {conn['connection_name']}",
            callback_data=f"deleteconnection|{conn['connection_name']}"
        )
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("connect_listen|"))(connect_listen_selected)
@dp.callback_query(F.data.startswith("connect_send|"))(connect_send_selected)


@dp.callback_query(F.data.startswith("creategroup_type|"))(creategroup_type_selected)
@dp.callback_query(F.data.startswith("creategroup_togglech|"))(creategroup_togglech_cb)
@dp.callback_query(F.data == "creategroup_confirmch")(creategroup_confirmch_cb)
@dp.callback_query(F.data.startswith("togglegroupch|"))(toggle_group_channel)
@dp.callback_query(F.data.startswith("editgroup|"))(show_group_channels)
@dp.callback_query(F.data.startswith("removegroupch|"))(remove_channel_from_group_cb)
@dp.callback_query(F.data.startswith("deletegroup|"))(delete_group_cb)
@dp.callback_query(F.data.startswith("deletech|"))
async def delete_channel_callback(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    try:
        _, ch_type, username = callback.data.split("|")
    
        with open('channels.db', 'rb+') as dbfile:
            pass
        import sqlite3
        with sqlite3.connect('channels.db') as conn:
            conn.execute(
                "DELETE FROM channels WHERE userid=? AND channel_username=? AND channel_type=?",
                (callback.from_user.id, username, ch_type)
            )
    except Exception as e:
        logger.error(f"Failed to delete channel: {e}")
        await callback.answer("Ошибка при удалении.", show_alert=True)
        return
  
    data = get_user_channels(callback.from_user.id)
    if not data["listen"] and not data["send"]:
        await callback.message.edit_text("❌У вас нет каналов для удаления.")
        return
    text = "Выберите канал для удаления:\n"
    builder = InlineKeyboardBuilder()
    for ch_type in ("listen", "send"):
        for ch in data[ch_type]:
            text += f"@{ch['channel']} ({ch_type})\n"
            builder.button(
                text=f"Удалить @{ch['channel']} ({ch_type})",
                callback_data=f"deletech|{ch_type}|{ch['channel']}"
            )
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.regexp(r"^discard\|"))
async def discard_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, post_id = callback.data.split("|", 1)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await cleanup_media_for_user(callback.from_user.id, post_id)

@dp.callback_query(F.data.regexp(r"^edit\|"))
async def edit_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    user_id = callback.from_user.id
    _, post_id = callback.data.split("|", 1)
    post = user_messages.get(user_id, {}).get(post_id)
    if post:
        text = post.get("text", "")
        if len(text.split()) <= 3:
            await callback.message.answer("Недостаточно текста для редактирования.")
            return
        prompt_addition = get_prompt_for_user(user_id)
      
        prompt = f"{text}\n{prompt_addition}"
        model = genai.GenerativeModel('gemini-2.0-flash')
        try:
            response = await asyncio.to_thread(model.generate_content, prompt)
            new_text = response.text
            user_messages[user_id][post_id]['text'] = new_text
            await callback.message.answer(new_text, reply_markup=get_action_buttons(post_id))
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            await callback.message.answer("Ошибка генерации текста.")
    else:
        await callback.message.answer("Нет текста для редактирования.")

@dp.callback_query(F.data.regexp(r"^approve\|"))
async def approve_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    user_id = callback.from_user.id
    _, post_id = callback.data.split("|", 1)
    post = user_messages.get(user_id, {}).get(post_id)
    from db import get_groups, get_group_channels, get_channels
    groups = get_groups(user_id)
    if not post:
        await callback.answer("Нет данных для отправки.", show_alert=True)
        return
    if not groups:
        send_channels = get_channels(user_id, "send", only_active=True)
        if not send_channels:
            await callback.answer("Нет активных каналов для отправки.", show_alert=True)
            return
        await send_post_to_channels(callback, post, send_channels, post_id)
        return
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=group, callback_data=f"sendtogroup|{group}|{post_id}")
    builder.button(text="Все", callback_data=f"sendtoall|{post_id}")
    builder.button(text="Назад", callback_data=f"approveback|{post_id}")
    builder.adjust(2)
    await callback.message.edit_text(
        "Выберите группу для отправки или отправьте во все каналы:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.regexp(r"^approveback\|"))
async def approve_back_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, post_id = callback.data.split("|", 1)
    post = user_messages.get(callback.from_user.id, {}).get(post_id)
    text = post.get("text", "") if post else ""
    await callback.message.edit_text(
        text or "Пост",
        reply_markup=get_action_buttons(post_id)
    )

@dp.callback_query(F.data.regexp(r"^sendtogroup\|"))
async def send_to_group_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, group_name, post_id = callback.data.split("|", 2)
    from db import get_group_channels
    user_id = callback.from_user.id
    post = user_messages.get(user_id, {}).get(post_id)
    group_channels = get_group_channels(user_id, group_name)
    if not post:
        await callback.answer("Нет данных для отправки.", show_alert=True)
        return
    if not group_channels:
        await callback.answer("В группе нет каналов.", show_alert=True)
        return
    await send_post_to_channels(callback, post, group_channels, post_id)

@dp.callback_query(F.data.regexp(r"^sendtoall\|"))
async def send_to_all_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, post_id = callback.data.split("|", 1)
    user_id = callback.from_user.id
    from db import get_channels
    post = user_messages.get(user_id, {}).get(post_id)
    send_channels = get_channels(user_id, "send", only_active=True)
    if not post:
        await callback.answer("Нет данных для отправки.", show_alert=True)
        return
    if not send_channels:
        await callback.answer("Нет активных каналов для отправки.", show_alert=True)
        return
    await send_post_to_channels(callback, post, send_channels, post_id)

def get_action_buttons(post_id, has_text=True):
    buttons = []
    if has_text:
        buttons.append([InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit|{post_id}")])
    buttons.append([InlineKeyboardButton(text="🗑️ Отменить", callback_data=f"discard|{post_id}")])
    buttons.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve|{post_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def cleanup_media_for_user(user_id, post_id=None):
    if user_id not in user_messages:
        return
    if post_id:
        user_data = user_messages[user_id].pop(post_id, None)
        if user_data:
        
            for file_path in user_data.get('files', []):
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
          
            for file_path in user_data.get('videos', []):
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
        if not user_messages[user_id]:
            user_messages.pop(user_id)
    else:
      
        for post in user_messages[user_id].values():
            for file_path in post.get('files', []):
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
            for file_path in post.get('videos', []):
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
        user_messages.pop(user_id)

async def process_buffered_media_group(user_id, group_id):
    key = (user_id, group_id)
    messages = grouped_messages_buffer.pop(key, [])
    media_group_timers.pop(key, None)
    files, videos, caption = [], [], ""
    for msg in sorted(messages, key=lambda m: m.id):
        if hasattr(msg, 'video') and msg.video:
            file_path = await msg.download_media(file=media_temp_dir)
            videos.append(str(file_path))
            if msg.text and not caption:
                caption = msg.text
        elif isinstance(msg.media, MessageMediaPhoto):
            file_path = await msg.download_media(file=media_temp_dir)
            files.append(str(file_path))
            if msg.text and not caption:
                caption = msg.text
        elif msg.text and not caption:
            caption = msg.text
    if caption.strip().lower() == "реклама":
       
        for f in files + videos:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        return
    await send_post_to_user(user_id, caption, files, videos)

@client.on(events.NewMessage())
async def telethon_handler(event):
    source_username = getattr(event.chat, 'username', None)
    if not source_username:
        return
    for user_id in get_all_user_ids():
        listen_channels = get_channels(user_id, "listen", only_active=True)
        if source_username in listen_channels:
            
            connections = get_connection_for_channel(user_id, source_username)
            automated = [c for c in connections if c['automate']]
            if automated:
                for conn in automated:
                    send_channels = get_group_channels(user_id, conn['send_group'])
                    text = event.message.text or ""
                    files, videos = [], []
                    if hasattr(event.message, 'video') and event.message.video:
                        file_path = await event.message.download_media(file=media_temp_dir)
                        videos.append(str(file_path))
                    elif isinstance(event.message.media, MessageMediaPhoto):
                        file_path = await event.message.download_media(file=media_temp_dir)
                        files.append(str(file_path))
                    
                    if text and len(text.split()) > 3:
                        model = genai.GenerativeModel('gemini-2.0-flash')
                        prompt_addition = get_prompt_for_user(user_id)
                        prompt = f"{text}\n{prompt_addition}"
                        try:
                            response = await asyncio.to_thread(model.generate_content, prompt)
                            text = response.text
                        except Exception as e:
                            logger.error(f"Gemini error: {e}")
                    
                    if text.strip().lower() == "реклама":
                        for f in files + videos:
                            try:
                                Path(f).unlink(missing_ok=True)
                            except Exception:
                                pass
                        continue  
               
                    for ch in send_channels:
                        try:
                            target = f"@{ch}"
                            media = []
                            if files:
                                media += [InputMediaPhoto(media=FSInputFile(f), caption=text if i == 0 and not videos else None) for i, f in enumerate(files)]
                            if videos:
                                media += [InputMediaVideo(media=FSInputFile(v), caption=text if i == 0 and not files else None) for i, v in enumerate(videos)]
                            if media:
                                await bot.send_media_group(chat_id=target, media=media)
                            elif text:
                                await bot.send_message(chat_id=target, text=text)
                        except Exception as e:
                            logger.warning(f"Failed to send to @{ch}: {e}")
                  
                    for f in files + videos:
                        try:
                            Path(f).unlink(missing_ok=True)
                        except Exception:
                            pass
                continue  
         
            grouped_id = event.message.grouped_id
            if grouped_id:
                loop = asyncio.get_event_loop()
                key = (user_id, grouped_id)
                grouped_messages_buffer.setdefault(key, []).append(event.message)
                if key in media_group_timers:
                    media_group_timers[key].cancel()
                media_group_timers[key] = loop.call_later(
                    2.0, lambda: asyncio.create_task(process_buffered_media_group(user_id, grouped_id))
                )
                continue
            if hasattr(event.message, 'video') and event.message.video:
                file_path = await event.message.download_media(file=media_temp_dir)
                await send_post_to_user(user_id, event.message.text or "", videos=[str(file_path)])
            elif isinstance(event.message.media, MessageMediaPhoto):
                file_path = await event.message.download_media(file=media_temp_dir)
                await send_post_to_user(user_id, event.message.text or "", [str(file_path)])
            elif event.message.text:
                await send_post_to_user(user_id, event.message.text)



async def process_user_media_group(user_id, media_group_id):
    buffers = getattr(handle_user_message, "media_group_buffers", {})
    timers = getattr(handle_user_message, "media_group_timers", {})
    key = (user_id, media_group_id)
    messages = buffers.pop(key, [])
    if key in timers:
        timers[key].cancel()
        timers.pop(key, None)
    files, videos, caption = [], [], ""
    for msg in sorted(messages, key=lambda m: m.message_id):
        if msg.video or (msg.document and getattr(msg.document, 'mime_type', '').startswith('video/')):
            video = msg.video or msg.document
            file_path = await save_video_to_file(msg.bot, video, media_temp_dir)
            videos.append(file_path)
        if msg.photo:
            file_path = await save_photo_to_file(msg.bot, msg.photo[-1], media_temp_dir)
            files.append(file_path)
        if msg.caption and not caption:
            caption = msg.caption
        elif msg.text and not caption:
            caption = msg.text
    if caption.strip().lower() == "реклама":
       
        for f in files + videos:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        return
    await send_post_to_user(user_id, caption, files, videos)

async def save_photo_to_file(bot, photo, media_temp_dir):
    file = await bot.download(photo)
    file_id = str(uuid.uuid4())
    file_path = media_temp_dir / f"{file_id}.jpg"
    with open(file_path, "wb") as f:
        f.write(file.read())
    file.seek(0)
    return str(file_path)

async def save_video_to_file(bot, video, media_temp_dir):
    file = await bot.download(video)
    file_id = str(uuid.uuid4())
    file_path = media_temp_dir / f"{file_id}.mp4"
    with open(file_path, "wb") as f:
        f.write(file.read())
    file.seek(0)
    return str(file_path)

async def send_post_to_channels(callback, post, send_channels, post_id=None):
    text = post.get("text", "")
    files = post.get("files", [])
    videos = post.get("videos", [])
    if text.strip().lower() == "реклама":
       
        for f in files + videos:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        await callback.message.edit_text("Пост не отправлен: реклама.", reply_markup=None)
        await cleanup_media_for_user(callback.from_user.id, post_id)
        return
    for ch in send_channels:
        try:
            target = f"@{ch}"
            media = []
            if files:
                media += [InputMediaPhoto(media=FSInputFile(f), caption=text if i == 0 and not videos else None) for i, f in enumerate(files)]
            if videos:
                media += [InputMediaVideo(media=FSInputFile(v), caption=text if i == 0 and not files else None) for i, v in enumerate(videos)]
            if media:
                await callback.bot.send_media_group(chat_id=target, media=media)
            elif text:
                await callback.bot.send_message(chat_id=target, text=text)
        except Exception as e:
            logger.warning(f"Failed to send to @{ch}: {e}")
    await callback.message.edit_text("✅ Отправлено!", reply_markup=None)
    await cleanup_media_for_user(callback.from_user.id, post_id)

async def send_post_to_user(user_id, text=None, files=None, videos=None):
    post_id = str(uuid.uuid4())
    user_messages.setdefault(user_id, {})[post_id] = {'text': text or '', 'files': files or [], 'videos': videos or []}
    media = []
    if files:
        media += [InputMediaPhoto(media=FSInputFile(f), caption=text if i == 0 and not videos else None) for i, f in enumerate(files)]
    if videos:
        media += [InputMediaVideo(media=FSInputFile(v), caption=text if i == 0 and not files else None) for i, v in enumerate(videos)]
    has_text = bool(text and text.strip())
    if media:
        await bot.send_media_group(chat_id=user_id, media=media)
        await bot.send_message(user_id, text or "Пост", reply_markup=get_action_buttons(post_id, has_text=has_text))
    elif text:
        await bot.send_message(user_id, text, reply_markup=get_action_buttons(post_id, has_text=has_text))
    return post_id
@dp.message(Command("automate"))
async def automate_cmd(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    user_id = message.from_user.id
    connections = get_connections(user_id)
    if not connections:
        await message.answer("У вас нет связок.")
        return
    text = "Ваши связки:\n"
    builder = InlineKeyboardBuilder()
    for conn in connections:
        status = "🟢" if conn['automate'] else "🔴"
        text += f"{status} <b>{conn['connection_name']}</b>: {conn['listen_group']} → {conn['send_group']}\n"
        builder.button(
            text=f"{'Отключить' if conn['automate'] else 'Включить'} {conn['connection_name']}",
            callback_data=f"automate|{conn['connection_name']}|{int(not conn['automate'])}"
        )
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("automate|"))
async def automate_toggle_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, connection_name, new_status = callback.data.split("|", 2)
    set_automation(callback.from_user.id, connection_name, int(new_status))
    await callback.answer("Статус автоматизации обновлён.")

    connections = get_connections(callback.from_user.id)
    text = "Ваши связки:\n"
    builder = InlineKeyboardBuilder()
    for conn in connections:
        status = "🟢" if conn['automate'] else "🔴"
        text += f"{status} <b>{conn['connection_name']}</b>: {conn['listen_group']} → {conn['send_group']}\n"
        builder.button(
            text=f"{'Отключить' if conn['automate'] else 'Включить'} {conn['connection_name']}",
            callback_data=f"automate|{conn['connection_name']}|{int(not conn['automate'])}"
        )
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())




@dp.message()
async def handle_user_message(message: Message):
 
    if message.from_user.id in group_creation_state:
        await handle_group_name_input(message)
        return
    if message.from_user.id in add_user_state:
        await handle_add_user_id(message)
        return
    state = connect_creation_state.get(message.from_user.id)
   
    if state and 'listen_group' in state and 'send_group' in state:
       
        await handle_connection_name_input(message)
        return
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    if message.text and message.text.startswith("/"):
        return
    match = TELEGRAM_POST_URL_RE.match(message.text.strip()) if message.text else None
    if match:
        return
    user_id = message.from_user.id
    if message.media_group_id:
        if not hasattr(handle_user_message, "media_group_buffers"):
            handle_user_message.media_group_buffers = {}
        buffers = handle_user_message.media_group_buffers
        key = (user_id, message.media_group_id)
        buffers.setdefault(key, []).append(message)
        if hasattr(handle_user_message, "media_group_timers"):
            timers = handle_user_message.media_group_timers
        else:
            timers = handle_user_message.media_group_timers = {}
        if key in timers:
            timers[key].cancel()
        loop = asyncio.get_event_loop()
        timers[key] = loop.call_later(
            2.0,
            lambda: asyncio.create_task(process_user_media_group(user_id, message.media_group_id))
        )
        return
 
    if message.video or (message.document and getattr(message.document, 'mime_type', '').startswith('video/')):
        video = message.video or message.document
        file_path = await save_video_to_file(message.bot, video, media_temp_dir)
        await send_post_to_user(user_id, message.caption or "", videos=[file_path])
        return
  
    if message.photo:
        file_path = await save_photo_to_file(message.bot, message.photo[-1], media_temp_dir)
        await send_post_to_user(user_id, message.caption or "", [file_path])
        return
    if message.text:
        await send_post_to_user(user_id, message.text)
        return

@dp.message()
async def fallback_handler(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    await message.answer("Я не понял это сообщение. Используйте команды или отправьте пост.")

@dp.callback_query()
async def fallback_callback(callback: CallbackQuery):
    await callback.answer("Неизвестное действие.", show_alert=True)


async def main():
    logger.info("начинаем работу")
    await client.start() 

   
    telethon_loop = asyncio.get_event_loop()
    telethon_task = telethon_loop.create_task(client.run_until_disconnected())

  
    await dp.start_polling(bot)

    await telethon_task

if __name__ == "__main__":
    asyncio.run(main())

