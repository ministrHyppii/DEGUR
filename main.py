import asyncio
import json
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Загружаем токен из .env файла
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

ADMIN_USERNAME = "ARTISTirbis" # Главный админ
SETTINGS_FILE = "settings.json"

# --- РАБОТА С БАЗОЙ ДАННЫХ (JSON) ---
def load_settings():
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- СОСТОЯНИЯ (FSM) ---
class FormStates(StatesGroup):
    waiting_for_media = State()
    waiting_for_floor = State()
    waiting_for_sector = State()

class AdminStates(StatesGroup):
    waiting_for_mod_id = State()
    waiting_for_standard_msg = State()

# --- КЛАВИАТУРЫ ---
def get_user_keyboard():
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📸 Отправить дежурство")]], resize_keyboard=True)
    return kb

def get_floors_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 Этаж", callback_data="floor_1"),
         InlineKeyboardButton(text="2 Этаж", callback_data="floor_2"),
         InlineKeyboardButton(text="3 Этаж", callback_data="floor_3")]
    ])
    return kb

def get_sector_keyboard():
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить сектор")]], resize_keyboard=True)
    return kb

def get_admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Управление модераторами", callback_data="admin_mods")],
        [InlineKeyboardButton(text="📝 Изменить стандартное сообщение", callback_data="admin_msg")]
    ])
    return kb

# --- ХЭНДЛЕРЫ ПОЛЬЗОВАТЕЛЯ ---

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Это бот для сдачи дежурства.\nНажми на кнопку ниже, чтобы отправить отчет.",
        reply_markup=get_user_keyboard()
    )

@router.message(F.text == "📸 Отправить дежурство")
async def start_form(message: Message, state: FSMContext):
    await state.set_state(FormStates.waiting_for_media)
    await message.answer("Пожалуйста, отправьте фото или видео вашего дежурства.", reply_markup=ReplyKeyboardMarkup(keyboard=[], resize_keyboard=True))

@router.message(FormStates.waiting_for_media, F.photo | F.video)
async def process_media(message: Message, state: FSMContext):
    # Сохраняем file_id медиафайла
    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    else:
        file_id = message.video.file_id
        media_type = "video"
    
    await state.update_data(media_id=file_id, media_type=media_type)
    await state.set_state(FormStates.waiting_for_floor)
    await message.answer("Выберите этаж, на котором вы дежурите:", reply_markup=get_floors_keyboard())

@router.callback_query(FormStates.waiting_for_floor, F.data.startswith("floor_"))
async def process_floor(callback: CallbackQuery, state: FSMContext):
    floor = callback.data.split("_")[1]
    await state.update_data(floor=floor)
    await state.set_state(FormStates.waiting_for_sector)
    await callback.message.edit_text(f"Выбран {floor} этаж.\nТеперь напишите сектор (или нажмите 'Пропустить'):", reply_markup=get_sector_keyboard())
    await callback.answer()

@router.message(FormStates.waiting_for_sector)
async def process_sector(message: Message, state: FSMContext):
    sector = message.text if message.text != "Пропустить сектор" else "Не указан"
    data = await state.get_data()
    await state.clear()
    
    settings = load_settings()
    moderators = settings.get("moderators", [])
    standard_msg = settings.get("standard_message", "Отчет отправлен.")
    
    # Формируем текст для модераторов
    mod_text = (
        f"🚨 **Новый отчет о дежурстве!**\n\n"
        f"👤 От кого: @{message.from_user.username or message.from_user.full_name}\n"
        f"🏢 Этаж: {data['floor']}\n"
        f"📍 Сектор: {sector}"
    )

    # Отправляем модераторам
    sent_count = 0
    for mod_id in moderators:
        try:
            if data['media_type'] == "photo":
                await bot.send_photo(chat_id=mod_id, photo=data['media_id'], caption=mod_text, parse_mode="Markdown")
            else:
                await bot.send_video(chat_id=mod_id, video=data['media_id'], caption=mod_text, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            logging.error(f"Не удалось отправить модератору {mod_id}: {e}")

    # Отправляем стандартное сообщение пользователю
    await message.answer(f"{standard_msg}\n\n(Доставлено модераторам: {sent_count})", reply_markup=get_user_keyboard())

# --- ХЭНДЛЕРЫ МОДЕРАТОРА ---

@router.message(Command("mod"))
async def cmd_mod(message: Message):
    settings = load_settings()
    if message.from_user.id in settings["moderators"] or message.from_user.username == ADMIN_USERNAME:
        await message.answer("Вы вошли в режим модератора. Сюда будут приходить отчеты о дежурствах.")
    else:
        await message.answer("У вас нет прав модератора.")

# --- ХЭНДЛЕРЫ АДМИНИСТРАТОРА ---

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.username != ADMIN_USERNAME:
        await message.answer("У вас нет доступа к админ-панели.")
        return
    
    await message.answer("Добро пожаловать в админ-панель.", reply_markup=get_admin_keyboard())

@router.callback_query(F.data == "admin_mods")
async def admin_mods_menu(callback: CallbackQuery):
    if callback.from_user.username != ADMIN_USERNAME: return
    
    settings = load_settings()
    mods = settings["moderators"]
    text = "👥 **Список модераторов:**\n\n"
    if not mods:
        text += "Список пуст."
    else:
        for m in mods:
            text += f"- `{m}`\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить модератора", callback_data="admin_add_mod")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_add_mod")
async def admin_add_mod_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.username != ADMIN_USERNAME: return
    await state.set_state(AdminStates.waiting_for_mod_id)
    await callback.message.edit_text("Отправьте **ID пользователя** (число), которого хотите сделать модератором.\n\n(Узнать ID можно, переслав сообщение от человека боту @userinfobot)")
    await callback.answer()

@router.message(AdminStates.waiting_for_mod_id)
async def admin_add_mod_save(message: Message, state: FSMContext):
    if message.from_user.username != ADMIN_USERNAME: return
    try:
        mod_id = int(message.text.strip())
        settings = load_settings()
        if mod_id not in settings["moderators"]:
            settings["moderators"].append(mod_id)
            save_settings(settings)
            await message.answer(f"✅ Пользователь `{mod_id}` добавлен в модераторы!", reply_markup=get_admin_keyboard())
        else:
            await message.answer("Этот пользователь уже является модератором.", reply_markup=get_admin_keyboard())
    except ValueError:
        await message.answer("Ошибка! Отправьте числовой ID.")
    await state.clear()

@router.callback_query(F.data == "admin_msg")
async def admin_msg_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.username != ADMIN_USERNAME: return
    await state.set_state(AdminStates.waiting_for_standard_msg)
    await callback.message.edit_text("Отправьте новый текст **стандартного сообщения** (который видят ученики после отправки):")
    await callback.answer()

@router.message(AdminStates.waiting_for_standard_msg)
async def admin_msg_save(message: Message, state: FSMContext):
    if message.from_user.username != ADMIN_USERNAME: return
    settings = load_settings()
    settings["standard_message"] = message.text
    save_settings(settings)
    await state.clear()
    await message.answer("✅ Стандартное сообщение обновлено!", reply_markup=get_admin_keyboard())

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if callback.from_user.username != ADMIN_USERNAME: return
    await callback.message.edit_text("Добро пожаловать в админ-панель.", reply_markup=get_admin_keyboard())
    await callback.answer()

# --- ЗАПУСК БОТА ---
async def main():
    # Проверка, что файл settings.json существует
    if not os.path.exists(SETTINGS_FILE):
        save_settings({"moderators": [], "standard_message": "Спасибо!"})
        
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())