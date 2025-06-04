import logging
from aiogram import F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from config import ADMIN_USER_ID, ALLOWED_USER_IDS, save_allowed_users
from db import (
    get_channels, get_groups, get_group_channels, add_channel_to_group, remove_channel_from_group, delete_group,
    add_connection, get_connections, set_automation, get_connection_for_channel, create_group
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

connect_creation_state = {}
group_creation_state = {}
add_user_state = set()

ALLOWED_USERS_FILE = "allowed_users.txt"

async def allowed_users_cmd(message: Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("⛔️ Нет доступа.")
        return
    text = "<b>Список разрешённых пользователей:</b>\n" + "\n".join(str(uid) for uid in ALLOWED_USER_IDS)
    builder = InlineKeyboardBuilder()
    for uid in ALLOWED_USER_IDS:
        builder.button(text=f"Удалить {uid}", callback_data=f"removeallowed|{uid}")
    builder.button(text="Добавить", callback_data="addallowed")
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())

async def remove_allowed_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_USER_ID:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, uid = callback.data.split("|", 1)
    try:
        uid = int(uid)
        if uid in ALLOWED_USER_IDS:
            ALLOWED_USER_IDS.remove(uid)
            save_allowed_users()
    except Exception:
        pass
    text = "<b>Список разрешённых пользователей:</b>\n" + "\n".join(str(uid) for uid in ALLOWED_USER_IDS)
    builder = InlineKeyboardBuilder()
    for uid in ALLOWED_USER_IDS:
        builder.button(text=f"Удалить {uid}", callback_data=f"removeallowed|{uid}")
    builder.button(text="Добавить", callback_data="addallowed")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

async def add_allowed_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_USER_ID:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    await callback.message.answer("Введите ID пользователя для добавления:", reply_markup=ReplyKeyboardRemove())
    add_user_state.add(callback.from_user.id)
    await callback.answer()


async def handle_add_user_id(message: Message):
   
    if message.from_user.id != ADMIN_USER_ID:
        return
    if message.from_user.id not in add_user_state:
        return
    try:
        uid = int(message.text.strip())
        if uid not in ALLOWED_USER_IDS:
            ALLOWED_USER_IDS.append(uid)
            save_allowed_users()
            await message.answer(f"Пользователь {uid} добавлен.")
        else:
            await message.answer(f"Пользователь {uid} уже есть в списке.")
    except Exception:
        await message.answer("Некорректный ID пользователя.")
    add_user_state.discard(message.from_user.id)


async def creategroup_start(message: Message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Группа для прослушивания", callback_data="creategroup_type|listen")
    builder.button(text="Группа для отправки", callback_data="creategroup_type|send")
    builder.adjust(1)
    await message.answer("Выберите тип группы:", reply_markup=builder.as_markup())

async def creategroup_type_selected(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, group_type = callback.data.split("|", 1)
    user_id = callback.from_user.id
  
    channels = get_channels(user_id, group_type)
    group_creation_state[user_id] = {
        'type': group_type,
        'selected_channels': set(),
        'step': 'select_channels'
    }
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.button(
            text=f"➕ @{ch}",
            callback_data=f"creategroup_togglech|{ch}"
        )
    builder.button(text="Готово", callback_data="creategroup_confirmch")
    builder.adjust(2)
    await callback.message.answer(
        f"Выберите каналы для группы типа '{'прослушивания' if group_type == 'listen' else 'отправки'}':",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

async def creategroup_togglech_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in group_creation_state or group_creation_state[user_id].get('step') != 'select_channels':
        await callback.answer("Нет состояния создания группы.", show_alert=True)
        return
    ch = callback.data.split("|", 1)[1]
    state = group_creation_state[user_id]
    if ch in state['selected_channels']:
        state['selected_channels'].remove(ch)
    else:
        state['selected_channels'].add(ch)

    channels = get_channels(user_id, state['type'])
    builder = InlineKeyboardBuilder()
    for channel in channels:
        in_group = channel in state['selected_channels']
        builder.button(
            text=f"{'✅' if in_group else '➕'} @{channel}",
            callback_data=f"creategroup_togglech|{channel}"
        )
    builder.button(text="Готово", callback_data="creategroup_confirmch")
    builder.adjust(2)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()

async def creategroup_confirmch_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in group_creation_state or group_creation_state[user_id].get('step') != 'select_channels':
        await callback.answer("Нет состояния создания группы.", show_alert=True)
        return
    if not group_creation_state[user_id]['selected_channels']:
        await callback.answer("Выберите хотя бы один канал.", show_alert=True)
        return
    group_creation_state[user_id]['step'] = 'enter_name'
    await callback.message.edit_text("Введите название группы:")
    await callback.answer()

async def handle_group_name_input(message: Message):
    user_id = message.from_user.id
    if user_id not in group_creation_state or group_creation_state[user_id].get('step') != 'enter_name':
        return
    state = group_creation_state[user_id]
    group_type = state.get('type')
    group_name = message.text.strip()
    selected_channels = state.get('selected_channels', set())
    if not group_name:
        await message.answer("Название группы не может быть пустым.")
        return
    create_group(user_id, group_name, group_type)
    for ch in selected_channels:
        add_channel_to_group(user_id, group_name, ch)
    await message.answer(f"Группа '{group_name}' типа '{'прослушивания' if group_type == 'listen' else 'отправки'}' создана и добавлены {len(selected_channels)} канал(ов).")
    group_creation_state.pop(user_id, None)

async def toggle_group_channel(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    parts = callback.data.split("|")
    group_name, channel = parts[1], parts[2]
    group_type = parts[3] if len(parts) > 3 else "send"
    user_id = callback.from_user.id
    group_channels = set(get_group_channels(user_id, group_name))
    if channel in group_channels:
        remove_channel_from_group(user_id, group_name, channel)
    else:
        add_channel_to_group(user_id, group_name, channel)
    channels = get_channels(user_id, group_type)
    group_channels = set(get_group_channels(user_id, group_name))
    builder = InlineKeyboardBuilder()
    for ch in channels:
        in_group = ch in group_channels
        builder.button(
            text=f"{'✅' if in_group else '➕'} @{ch}",
            callback_data=f"togglegroupch|{group_name}|{ch}|{group_type}"
        )
    builder.adjust(2)
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())

async def show_group_channels(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, group_name = callback.data.split("|", 1)
    user_id = callback.from_user.id
    channels = get_group_channels(user_id, group_name)
    if not channels:
        await callback.message.edit_text(f"В группе <b>{group_name}</b> нет каналов.")
        return
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.button(text=f"Удалить @{ch}", callback_data=f"removegroupch|{group_name}|{ch}")
    builder.adjust(1)
    await callback.message.edit_text(f"Каналы в группе <b>{group_name}</b>:", reply_markup=builder.as_markup())

async def remove_channel_from_group_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, group_name, channel = callback.data.split("|", 2)
    user_id = callback.from_user.id
    remove_channel_from_group(user_id, group_name, channel)
    channels = get_group_channels(user_id, group_name)
    if not channels:
        await callback.message.edit_text(f"В группе <b>{group_name}</b> нет каналов.")
        return
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.button(text=f"Удалить @{ch}", callback_data=f"removegroupch|{group_name}|{ch}")
    builder.adjust(1)
    await callback.message.edit_text(f"Каналы в группе <b>{group_name}</b>:", reply_markup=builder.as_markup())

async def delete_group_cb(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    _, group_name = callback.data.split("|", 1)
    user_id = callback.from_user.id
    delete_group(user_id, group_name)
    groups = get_groups(user_id)
    if not groups:
        await callback.message.edit_text("У вас нет групп для удаления.")
        return
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.button(text=f"Удалить {group}", callback_data=f"deletegroup|{group}")
    builder.adjust(1)
    await callback.message.edit_text("Выберите группу для удаления:", reply_markup=builder.as_markup())


async def connect_listen_selected(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    user_id = callback.from_user.id
    listen_group = callback.data.split("|", 1)[1]
    connect_creation_state[user_id] = {'listen_group': listen_group}
    send_groups = []
    for g in get_groups(user_id):
        if g == listen_group:
            continue
        chs = get_group_channels(user_id, g)
        if chs:
            send_chs = get_channels(user_id, "send")
            if all(ch in send_chs for ch in chs):
                send_groups.append(g)
    if not send_groups:
        await callback.message.answer("У вас нет групп для отправки с каналами.")
        connect_creation_state.pop(user_id, None)
        return
    builder = InlineKeyboardBuilder()
    for g in send_groups:
        builder.button(text=g, callback_data=f"connect_send|{g}")
    builder.adjust(1)
    await callback.message.answer("Выберите группу для отправки:", reply_markup=builder.as_markup())
    await callback.answer()

async def connect_send_selected(callback: CallbackQuery):
    if callback.from_user.id not in ALLOWED_USER_IDS:
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    user_id = callback.from_user.id
    send_group = callback.data.split("|", 1)[1]
    state = connect_creation_state.get(user_id)
  
    if not state or 'listen_group' not in state:
        await callback.message.answer("Ошибка состояния. Начните заново.")
        return
    connect_creation_state[user_id]['send_group'] = send_group
    await callback.message.answer("Введите имя для связки:")
    await callback.answer()

async def handle_connection_name_input(message: Message):

    user_id = message.from_user.id
    state = connect_creation_state.get(user_id)
    if not state or 'listen_group' not in state or 'send_group' not in state:
        return
    connection_name = message.text.strip()
    if not connection_name:
        await message.answer("Имя связки не может быть пустым.")
        return
    add_connection(user_id, state['listen_group'], state['send_group'], connection_name)
    await message.answer(f"Связка '{connection_name}' создана: {state['listen_group']} → {state['send_group']}")
    connect_creation_state.pop(user_id, None)
