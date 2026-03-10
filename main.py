import os
import json
import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", "10000"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super-secret-key")
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else None

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

START_MOVES = 12
PLACEHOLDER_PATH = "placeholder.png"

TRUST_NEUTRAL = "neutral"
TRUST_CAREFUL = "careful"
TRUST_CLOSED = "closed"

RULES_TEXT = (
    "Правила игры\n\n"
    "Перед вами детективная история с ограниченным числом ходов. "
    f"На одно дело у вас есть {START_MOVES} ходов.\n\n"
    "Ходы тратятся на осмотр локаций, просмотр камер и допросы. "
    "Досье, журнал и список улик можно открывать бесплатно.\n\n"
    "Часть вопросов открывается только после того, как вы находите новую информацию. "
    "Сначала собирайте факты, потом возвращайтесь к подозреваемым.\n\n"
    "У каждого подозреваемого есть своё состояние. Если вы слишком рано давите, "
    "персонаж это запомнит и станет отвечать суше.\n\n"
    "Чтобы закончить дело, нужно выбрать подозреваемого и предъявить доказательства."
)

HELP_TEXT = (
    "Помощь\n\n"
    "Нажмите «Начать расследование», чтобы перейти к делу.\n\n"
    "Сначала осмотрите ключевые места и камеры. После этого в допросах откроются новые вопросы.\n\n"
    "Если запутаетесь, откройте журнал. Туда записываются важные сведения."
)

SUSPECTS = {
    "alina": {
        "name": "Алина Белова",
        "card": """
<b>Алина Белова</b>

<b>Возраст:</b> 20 лет
<b>Статус:</b> студентка 2 курса
<b>Проживает:</b> блок 314, соседка жертвы

Алина живёт в общежитии уже второй год. По словам соседей, часто шумит и устраивает поздние встречи с друзьями. Жертва неоднократно жаловалась на неё коменданту.

В день происшествия Алина находилась на этаже и могла контактировать с Ильёй. Она утверждает, что вечером занималась своими делами и не заходила к нему.
""",
        "is_guilty": False,
    },
    "timur": {
        "name": "Тимур Каримов",
        "card": """
<b>Тимур Каримов</b>

<b>Возраст:</b> 22 года
<b>Статус:</b> студент 3 курса
<b>Проживает:</b> блок 317

Тимур был близким другом Ильи и часто помогал ему с учёбой. В последнее время между ними возникали напряжённые разговоры, и соседи слышали спор на повышенных тонах.

В ночь происшествия Тимур утверждает, что почти не выходил из комнаты. При этом его видели на кухне, где жильцы часто готовят кофе и разводят энергетики.
""",
        "is_guilty": False,
    },
    "nikita": {
        "name": "Никита Орлов",
        "card": """
<b>Никита Орлов</b>

<b>Возраст:</b> 21 год
<b>Статус:</b> студент 3 курса
<b>Проживает:</b> комната жертвы

Никита делил комнату с Ильёй. Их отношения были сложными. Соседи не раз слышали ссоры и взаимные претензии. Илья говорил, что хочет переехать и написать заявление.

В день происшествия Никита заявляет, что был в библиотеке и вернулся поздно. Некоторые детали его алиби звучат неуверенно, и он раздражается на уточняющие вопросы.
""",
        "is_guilty": False,
    },
    "danil": {
        "name": "Данил Громов",
        "card": """
<b>Данил Громов</b>

<b>Возраст:</b> 23 года
<b>Статус:</b> староста этажа
<b>Проживает:</b> блок 312

Данил отвечает за порядок на этаже и часто общается с администрацией. Он знает расписания, привычки жильцов и быстро ориентируется в происходящем.

В ночь происшествия Данил утверждает, что следил за дисциплиной и был на месте. Он слишком активно предлагает помощь и старается контролировать разговоры на этаже.
""",
        "is_guilty": False,
    },
    "maria": {
        "name": "Мария Литвинова",
        "card": """
<b>Мария Литвинова</b>

<b>Возраст:</b> 21 год
<b>Статус:</b> студентка 3 курса
<b>Проживает:</b> блок 318

Мария учится с Ильёй на одном курсе. По словам одногруппников, она всегда собранная и редко участвует в шумных компаниях. В этом семестре она резко усилила подготовку к конкурсам.

Вечером она утверждает, что занималась у себя в комнате и почти ни с кем не общалась. При упоминании конкурса на грант её реакция кажется слишком напряжённой.
""",
        "is_guilty": True,
    },
}

SUSPECT_ORDER = [
    ("Алина Белова", "alina"),
    ("Тимур Каримов", "timur"),
    ("Никита Орлов", "nikita"),
    ("Данил Громов", "danil"),
    ("Мария Литвинова", "maria"),
]

INTERROGATION_QUESTIONS = {
    "alina": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_noise"]},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "kitchen_seen": {"text": "Видели ли вы кого-нибудь на кухне?", "requires": ["visited_kitchen"]},
    },
    "timur": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_noise"]},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "energy": {"text": "Вы пили энергетики вечером?", "requires": ["found_energy_drinks"]},
        "camera_kitchen": {
            "text": "Камера показывает, что вы были на кухне. Что вы там делали?",
            "requires": ["saw_kitchen_camera", "saw_timur_on_kitchen_camera"],
        },
        "corridor_camera": {
            "text": "Камера показывает, что вы были рядом с комнатой Ильи. Зачем?",
            "requires": ["saw_corridor_camera", "saw_timur_in_corridor"],
        },
    },
    "nikita": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_noise"]},
        "room": {"text": "Вы были в комнате в тот момент?", "requires": []},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "energy": {"text": "Вы брали энергетики на кухне?", "requires": ["found_energy_drinks"]},
        "drink": {"text": "Кто приносил Илье напиток?", "requires": ["found_drink"]},
        "corridor_camera": {
            "text": "Камера показывает, что вы были у комнаты. Почему вы не сказали об этом?",
            "requires": ["saw_corridor_camera", "saw_nikita_in_corridor"],
        },
    },
    "danil": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_noise"]},
        "patrol": {"text": "Вы обходили этаж вечером?", "requires": []},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "energy": {"text": "Кто обычно берёт энергетики на кухне?", "requires": ["found_energy_drinks"]},
        "corridor_camera": {
            "text": "Камера показывает, что вы проходили мимо комнаты. Почему вы это не упомянули?",
            "requires": ["saw_corridor_camera", "saw_danil_in_corridor"],
        },
    },
    "maria": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "study": {"text": "Вы работали с ним по учёбе?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_noise"]},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "kitchen_seen": {"text": "Видели ли вы кого-нибудь на кухне?", "requires": ["visited_kitchen"]},
        "phone": {"text": "Илья кому-нибудь звонил перед смертью?", "requires": ["found_phone"]},
        "call": {"text": "Илья звонил вам вечером?", "requires": ["found_phone_logs"]},
        "drink": {"text": "Кто приносил Илье напиток?", "requires": ["found_drink"]},
        "camera_kitchen": {
            "text": "Камера показывает, что вы были на кухне. Что вы там делали?",
            "requires": ["saw_kitchen_camera", "saw_maria_on_kitchen_camera"],
        },
        "poison": {
            "text": "Вы добавили что-то в напиток Ильи?",
            "requires": ["found_drink", "found_energy_drinks", "saw_kitchen_camera", "saw_maria_on_kitchen_camera"],
        },
    },
}

user_state = {}


def default_state() -> dict:
    return {
        "case_started": False,
        "moves_left": START_MOVES,
        "trust_state": {key: TRUST_NEUTRAL for _, key in SUSPECT_ORDER},
        "found_clues": [],
        "viewed_cameras": [],
        "visited_locations": [],
        "searched_spots": [],
        "flags": [],
        "journal": [],
        "interrogated": [],
        "asked_questions": {key: [] for _, key in SUSPECT_ORDER},
    }


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не найден. Проверь Environment Variables в Render")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_saves (
                    user_id BIGINT PRIMARY KEY,
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()


def load_state(user_id: int) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state_json FROM player_saves WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return row["state_json"]


def save_state(user_id: int) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO player_saves (user_id, state_json, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET
                    state_json = EXCLUDED.state_json,
                    updated_at = NOW()
                """,
                (user_id, json.dumps(user_state[user_id], ensure_ascii=False)),
            )
        conn.commit()


def get_state(user_id: int) -> dict:
    if user_id not in user_state:
        loaded = load_state(user_id)
        user_state[user_id] = loaded if loaded else default_state()
    return user_state[user_id]


def add_note(user_id: int, text: str) -> None:
    state = get_state(user_id)
    if text not in state["journal"]:
        state["journal"].append(text)
        save_state(user_id)


def add_flag(user_id: int, flag: str) -> None:
    state = get_state(user_id)
    if flag not in state["flags"]:
        state["flags"].append(flag)
        save_state(user_id)


def has_flags(user_id: int, required_flags: list[str]) -> bool:
    if not required_flags:
        return True
    state = get_state(user_id)
    current_flags = set(state.get("flags", []))
    return all(flag in current_flags for flag in required_flags)


def add_clue(user_id: int, clue: str) -> None:
    state = get_state(user_id)
    if clue not in state["found_clues"]:
        state["found_clues"].append(clue)
        save_state(user_id)


def mark_location_visited(user_id: int, location_key: str) -> None:
    state = get_state(user_id)
    if location_key not in state["visited_locations"]:
        state["visited_locations"].append(location_key)
        save_state(user_id)


def mark_camera_viewed(user_id: int, camera_key: str) -> None:
    state = get_state(user_id)
    if camera_key not in state["viewed_cameras"]:
        state["viewed_cameras"].append(camera_key)
        save_state(user_id)


def mark_spot_searched(user_id: int, spot_key: str) -> None:
    state = get_state(user_id)
    if spot_key not in state["searched_spots"]:
        state["searched_spots"].append(spot_key)
        save_state(user_id)


def was_spot_searched(user_id: int, spot_key: str) -> bool:
    state = get_state(user_id)
    return spot_key in state.get("searched_spots", [])


def spend_move(user_id: int) -> bool:
    state = get_state(user_id)
    if state["moves_left"] <= 0:
        return False
    state["moves_left"] -= 1
    save_state(user_id)
    return True


def spend_move_if_first_time(user_id: int, spot_key: str) -> bool:
    if was_spot_searched(user_id, spot_key):
        return True
    if not spend_move(user_id):
        return False
    mark_spot_searched(user_id, spot_key)
    return True


def moves_line(user_id: int) -> str:
    state = get_state(user_id)
    return f"Осталось ходов: {state['moves_left']}"


def get_trust_state(user_id: int, suspect_key: str) -> str:
    state = get_state(user_id)
    return state["trust_state"].get(suspect_key, TRUST_NEUTRAL)


def trust_status_text(user_id: int, suspect_key: str) -> str:
    state = get_trust_state(user_id, suspect_key)
    if state == TRUST_CLOSED:
        return "закрыт" if suspect_key in {"timur", "nikita", "danil"} else "закрыта"
    if state == TRUST_CAREFUL:
        return "насторожен" if suspect_key in {"timur", "nikita", "danil"} else "насторожена"
    return "спокоен" if suspect_key in {"timur", "nikita", "danil"} else "спокойна"


def worsen_trust_state(user_id: int, suspect_key: str, severity: str) -> str:
    state = get_state(user_id)
    current = state["trust_state"].get(suspect_key, TRUST_NEUTRAL)

    if severity == TRUST_CLOSED:
        state["trust_state"][suspect_key] = TRUST_CLOSED
    elif severity == TRUST_CAREFUL and current == TRUST_NEUTRAL:
        state["trust_state"][suspect_key] = TRUST_CAREFUL

    save_state(user_id)
    return state["trust_state"][suspect_key]


def was_question_asked(user_id: int, suspect_key: str, question_key: str) -> bool:
    state = get_state(user_id)
    return question_key in state["asked_questions"].get(suspect_key, [])


def mark_question_asked(user_id: int, suspect_key: str, question_key: str) -> None:
    state = get_state(user_id)
    if question_key not in state["asked_questions"][suspect_key]:
        state["asked_questions"][suspect_key].append(question_key)
        save_state(user_id)


def get_available_questions(user_id: int, suspect_key: str) -> dict:
    questions = INTERROGATION_QUESTIONS[suspect_key]
    result = {}
    for key, data in questions.items():
        if has_flags(user_id, data.get("requires", [])):
            result[key] = data
    return result


def build_main_menu_markup(has_save: bool) -> InlineKeyboardMarkup:
    keyboard = []
    if has_save:
        keyboard.append([InlineKeyboardButton("Продолжить", callback_data="continue_case")])

    keyboard.extend([
        [InlineKeyboardButton("Начать расследование", callback_data="new_case")],
        [InlineKeyboardButton("Досье подозреваемых", callback_data="suspects")],
        [InlineKeyboardButton("Правила игры", callback_data="rules")],
        [InlineKeyboardButton("Помощь", callback_data="help")],
    ])
    return InlineKeyboardMarkup(keyboard)


def build_investigation_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Локации", callback_data="locations")],
        [InlineKeyboardButton("Допрос", callback_data="interrogation")],
        [InlineKeyboardButton("Камеры", callback_data="cameras")],
        [InlineKeyboardButton("Улики", callback_data="clues")],
        [InlineKeyboardButton("Журнал", callback_data="journal")],
        [InlineKeyboardButton("Обвинить", callback_data="accuse")],
        [InlineKeyboardButton("Назад в меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_locations_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Кухня", callback_data="location:kitchen")],
        [InlineKeyboardButton("Комната Ильи", callback_data="location:room")],
        [InlineKeyboardButton("Коридор", callback_data="location:corridor")],
        [InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_location_actions_markup(location_key: str) -> InlineKeyboardMarkup:
    if location_key == "kitchen":
        keyboard = [
            [InlineKeyboardButton("Осмотреть стол", callback_data="spot:kitchen:table")],
            [InlineKeyboardButton("Проверить мусорное ведро", callback_data="spot:kitchen:trash")],
            [InlineKeyboardButton("Осмотреть раковину", callback_data="spot:kitchen:sink")],
            [InlineKeyboardButton("Проверить холодильник", callback_data="spot:kitchen:fridge")],
            [InlineKeyboardButton("Назад к локациям", callback_data="locations")],
        ]
    elif location_key == "room":
        keyboard = [
            [InlineKeyboardButton("Осмотреть стол", callback_data="spot:room:desk")],
            [InlineKeyboardButton("Проверить телефон", callback_data="spot:room:phone")],
            [InlineKeyboardButton("Осмотреть кровать и тумбу", callback_data="spot:room:bedside")],
            [InlineKeyboardButton("Проверить бумаги и тетради", callback_data="spot:room:papers")],
            [InlineKeyboardButton("Назад к локациям", callback_data="locations")],
        ]
    elif location_key == "corridor":
        keyboard = [
            [InlineKeyboardButton("Поговорить с жильцами", callback_data="spot:corridor:witnesses")],
            [InlineKeyboardButton("Осмотреть пол у комнаты", callback_data="spot:corridor:floor")],
            [InlineKeyboardButton("Проверить дверь комнаты", callback_data="spot:corridor:door")],
            [InlineKeyboardButton("Осмотреть подоконник", callback_data="spot:corridor:window")],
            [InlineKeyboardButton("Назад к локациям", callback_data="locations")],
        ]
    else:
        keyboard = [[InlineKeyboardButton("Назад к локациям", callback_data="locations")]]

    return InlineKeyboardMarkup(keyboard)


def build_cameras_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Камера кухни", callback_data="camera:kitchen")],
        [InlineKeyboardButton("Камера коридора", callback_data="camera:corridor")],
        [InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_interrogation_suspects_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"interrogate:{key}")]
        for name, key in SUSPECT_ORDER
    ]
    keyboard.append([InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")])
    return InlineKeyboardMarkup(keyboard)


def build_questions_markup(user_id: int, suspect_key: str) -> InlineKeyboardMarkup:
    questions = get_available_questions(user_id, suspect_key)
    keyboard = []

    for key, data in questions.items():
        keyboard.append([InlineKeyboardButton(data["text"], callback_data=f"ask:{suspect_key}:{key}")])

    keyboard.append([InlineKeyboardButton("Назад к подозреваемым", callback_data="interrogation")])
    keyboard.append([InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")])
    return InlineKeyboardMarkup(keyboard)


async def safe_show_text_screen(query, context, text: str, reply_markup=None, parse_mode=None) -> None:
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except BadRequest:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


async def show_main_menu(query, context, user_id: int) -> None:
    has_save = load_state(user_id) is not None
    await safe_show_text_screen(
        query,
        context,
        "Последний допрос\n\n"
        "Вы, детектив Андрей Соколов. Это ваше последнее дело.\n\n"
        "Выберите действие:",
        reply_markup=build_main_menu_markup(has_save=has_save),
    )


async def show_investigation_menu(query, context, user_id: int) -> None:
    await safe_show_text_screen(
        query,
        context,
        "Вы заходите в холл общежития. Сейчас начнётся расследование.\n\n"
        f"{moves_line(user_id)}",
        reply_markup=build_investigation_menu_markup(),
    )


async def show_interrogation_menu(query, context, user_id: int, suspect_key: str) -> None:
    name = SUSPECTS[suspect_key]["name"]
    available_questions = get_available_questions(user_id, suspect_key)

    await safe_show_text_screen(
        query,
        context,
        f"Вы начинаете разговор с {name}.\n\n"
        f"Состояние: {trust_status_text(user_id, suspect_key)}\n"
        f"{moves_line(user_id)}\n\n"
        f"Доступно вопросов: {len(available_questions)}\n\n"
        "Выберите вопрос:",
        reply_markup=build_questions_markup(user_id, suspect_key),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    get_state(user_id)
    has_save = load_state(user_id) is not None

    if update.message:
        await update.message.reply_text(
            "Последний допрос\n\n"
            "Вы, детектив Андрей Соколов. Это ваше последнее дело.\n\n"
            "Выберите действие:",
            reply_markup=build_main_menu_markup(has_save=has_save),
        )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    state = get_state(user_id)

    if query.data == "main_menu":
        await show_main_menu(query, context, user_id)

    elif query.data == "back_to_investigation":
        await show_investigation_menu(query, context, user_id)

    elif query.data == "rules":
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
        )
        await safe_show_text_screen(
            query,
            context,
            "Вы раскрываете служебную памятку и ещё раз пробегаете глазами по основным правилам дела.\n\n"
            + RULES_TEXT,
            reply_markup=reply_markup,
        )

    elif query.data == "help":
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
        )
        await safe_show_text_screen(
            query,
            context,
            "Вы быстро сверяетесь с подсказкой, чтобы ничего не упустить.\n\n"
            + HELP_TEXT,
            reply_markup=reply_markup,
        )

    elif query.data == "new_case":
        user_state[user_id] = default_state()
        user_state[user_id]["case_started"] = True
        save_state(user_id)
        await safe_show_text_screen(
            query,
            context,
            "Вы заходите в холл общежития. Сейчас начнётся расследование.\n\n"
            "Перед вами длинный коридор, общая кухня и слишком много людей, которым есть что скрывать.",
            reply_markup=build_investigation_menu_markup(),
        )

    elif query.data == "continue_case":
        loaded = load_state(user_id)
        if loaded:
            user_state[user_id] = loaded
            await show_investigation_menu(query, context, user_id)
        else:
            await show_main_menu(query, context, user_id)

    elif query.data == "suspects":
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"suspect:{key}")]
            for name, key in SUSPECT_ORDER
        ]
        keyboard.append([InlineKeyboardButton("Назад в меню", callback_data="main_menu")])

        await safe_show_text_screen(
            query,
            context,
            "Вы открываете папку с материалами дела. Перед вами список подозреваемых.\n\n"
            "Выберите карточку:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("suspect:"):
        key = query.data.split("suspect:", 1)[1].strip()
        card_text = SUSPECTS.get(key, {}).get("card", "Карточка не найдена.")

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Назад к списку", callback_data="suspects")],
            [InlineKeyboardButton("Назад в меню", callback_data="main_menu")],
        ])

        if key == "alina" and Path(PLACEHOLDER_PATH).exists():
            try:
                await query.message.delete()
            except Exception:
                pass

            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=PLACEHOLDER_PATH,
                caption=card_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        else:
            await safe_show_text_screen(
                query,
                context,
                card_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )

    elif query.data == "locations":
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        await safe_show_text_screen(
            query,
            context,
            "Вы выбираете, что осмотреть.\n\n"
            f"{moves_line(user_id)}",
            reply_markup=build_locations_markup(),
        )

    elif query.data.startswith("location:"):
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        location_key = query.data.split(":", 1)[1].strip()
        mark_location_visited(user_id, location_key)

        if location_key == "kitchen":
            add_flag(user_id, "visited_kitchen")
            text = (
                "Вы входите на общую кухню.\n\n"
                "На столе стоит посуда, у раковины что-то недавно споласкивали, а мусорное ведро переполнено.\n\n"
                "Выберите, что осмотреть:"
            )
        elif location_key == "room":
            text = (
                "Вы входите в комнату Ильи.\n\n"
                "На столе беспорядок, рядом кровать и тумба, а в бумагах явно кто-то копался.\n\n"
                "Выберите, что осмотреть:"
            )
        elif location_key == "corridor":
            add_flag(user_id, "heard_noise")
            text = (
                "Вы осматриваете коридор у комнаты Ильи.\n\n"
                "Здесь слышали шум, кто-то проходил мимо в нужное время, а жильцы готовы делиться обрывками воспоминаний.\n\n"
                "Выберите, что осмотреть:"
            )
        else:
            text = "Локация пока недоступна."

        await safe_show_text_screen(
            query,
            context,
            text,
            reply_markup=build_location_actions_markup(location_key),
        )

    elif query.data.startswith("spot:"):
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        _, location_key, spot_key = query.data.split(":")
        full_spot_key = f"{location_key}:{spot_key}"

        if not spend_move_if_first_time(user_id, full_spot_key):
            await safe_show_text_screen(
                query,
                context,
                "Ходы закончились. Пора переходить к обвинению.",
                reply_markup=build_investigation_menu_markup(),
            )
            return

        text = "Ничего важного."
        reply_markup = build_location_actions_markup(location_key)

        if location_key == "kitchen":
            add_flag(user_id, "visited_kitchen")

            if spot_key == "table":
                add_flag(user_id, "found_energy_drinks")
                add_clue(user_id, "На кухонном столе стоят открытые банки энергетика и липкий след от пролитого напитка.")
                add_note(user_id, "На кухонном столе найдены энергетики. Теперь можно спрашивать, кто пил их вечером.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди кружек и упаковок стоят открытые банки энергетика. На поверхности липкий след, будто что-то пролили наспех.\n\n"
                    "Теперь открылись вопросы про энергетики."
                )

            elif spot_key == "trash":
                add_flag(user_id, "found_pill_package")
                add_clue(user_id, "В мусорном ведре лежит смятая упаковка от таблеток без двух капсул.")
                add_note(user_id, "В мусорном ведре найдена упаковка от таблеток. Это может быть связано с причиной смерти.")
                text = (
                    "Вы проверяете мусорное ведро.\n\n"
                    "Под салфетками и пустыми упаковками лежит смятая блистерная упаковка. В ней не хватает двух таблеток.\n\n"
                    "Это уже серьёзная улика."
                )

            elif spot_key == "sink":
                add_flag(user_id, "found_rinsed_mug")
                add_clue(user_id, "В раковине стоит плохо промытая кружка с горьким запахом.")
                add_note(user_id, "В раковине найдена плохо промытая кружка. Возможно, кто-то пытался скрыть следы напитка.")
                text = (
                    "Вы осматриваете раковину.\n\n"
                    "Внутри стоит кружка, которую явно сполоснули наспех. От неё идёт слабый горький запах.\n\n"
                    "Теперь версия с напитком выглядит гораздо серьёзнее."
                )

            elif spot_key == "fridge":
                add_flag(user_id, "checked_fridge")
                add_clue(user_id, "В холодильнике хранятся общие напитки, доступ к ним был у всех жильцов этажа.")
                add_note(user_id, "Напитки на кухне были в общем доступе. Это важно для версии с подмешиванием.")
                text = (
                    "Вы проверяете холодильник.\n\n"
                    "Внутри стоят общие напитки, вода и ещё несколько банок. Доступ к ним явно был у всех.\n\n"
                    "Это не даёт имени, но расширяет круг тех, кто мог подмешать что-то в напиток."
                )

        elif location_key == "room":
            if spot_key == "desk":
                add_flag(user_id, "found_drink")
                add_clue(user_id, "На столе в комнате Ильи стоит недопитый напиток с непривычно горьким привкусом.")
                add_note(user_id, "В комнате найден недопитый напиток Ильи. Теперь можно спрашивать, кто его приносил.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди тетрадей и зарядки стоит недопитый напиток. Запах сладкий, но во вкусе явно чувствовалась бы горечь.\n\n"
                    "Теперь открылись вопросы про напиток жертвы."
                )

            elif spot_key == "phone":
                add_flag(user_id, "found_phone")
                add_flag(user_id, "found_phone_logs")
                add_clue(user_id, "Телефон Ильи сохранил несколько недавних вызовов, включая разговор с Марией.")
                add_note(user_id, "В телефоне Ильи найден недавний вызов Марии. Теперь можно спрашивать её об этом напрямую.")
                text = (
                    "Вы проверяете телефон.\n\n"
                    "В журнале вызовов есть несколько свежих записей. Один из последних звонков связан с Марией.\n\n"
                    "Теперь у Марии открылся вопрос про звонок."
                )

            elif spot_key == "bedside":
                add_flag(user_id, "found_room_disturbance")
                add_clue(user_id, "На тумбе и возле кровати видны следы поспешных движений, будто в комнате недавно спорили.")
                add_note(user_id, "В комнате заметны следы недавнего беспорядка. Версия о конфликте усиливается.")
                text = (
                    "Вы осматриваете кровать и тумбу.\n\n"
                    "Вещи лежат неровно, одна из книг упала на пол, а на тумбе будто что-то резко сдвинули.\n\n"
                    "Похоже, в комнате действительно был напряжённый разговор."
                )

            elif spot_key == "papers":
                add_flag(user_id, "found_project_notes")
                add_clue(user_id, "Среди бумаг Ильи лежат заметки по общему проекту и пометка о конкурсе на грант.")
                add_note(user_id, "В бумагах Ильи есть упоминание общего проекта и гранта. Это связывает его с Марией сильнее, чем казалось.")
                text = (
                    "Вы перебираете бумаги.\n\n"
                    "Среди черновиков и распечаток есть заметки по общему проекту, а ещё лист с пометкой о гранте.\n\n"
                    "Теперь учебная линия и напряжение вокруг конкурса выглядят важнее."
                )

        elif location_key == "corridor":
            add_flag(user_id, "heard_noise")

            if spot_key == "witnesses":
                add_flag(user_id, "heard_argument")
                add_clue(user_id, "Жильцы коридора вспоминают короткий спор у комнаты Ильи незадолго до происшествия.")
                add_note(user_id, "Жильцы подтверждают, что вечером у комнаты Ильи был спор. Теперь можно задавать прямые вопросы о шуме и ссоре.")
                text = (
                    "Вы разговариваете с жильцами.\n\n"
                    "Несколько человек вспоминают, что вечером у комнаты Ильи действительно звучали раздражённые голоса.\n\n"
                    "Теперь открылись вопросы про шум и спор."
                )

            elif spot_key == "floor":
                add_flag(user_id, "found_corridor_trace")
                add_clue(user_id, "У двери комнаты виден засохший след от сладкого напитка, будто что-то капнули на пол.")
                add_note(user_id, "У комнаты найден след от напитка. Это связывает коридор с версией о подмешивании.")
                text = (
                    "Вы осматриваете пол у комнаты.\n\n"
                    "У порога заметен старый липкий след. Кто-то, похоже, нёс напиток и пролил немного по дороге.\n\n"
                    "Это делает маршрут от кухни до комнаты ещё важнее."
                )

            elif spot_key == "door":
                add_flag(user_id, "checked_door")
                add_clue(user_id, "На двери комнаты нет следов взлома. Илья, вероятно, сам открыл человеку, который пришёл.")
                add_note(user_id, "На двери нет следов взлома. Значит, жертва либо знала гостя, либо не ждала угрозы.")
                text = (
                    "Вы осматриваете дверь.\n\n"
                    "Замок цел, следов взлома нет. Похоже, Илья сам открыл дверь или вообще не опасался того, кто пришёл.\n\n"
                    "Это сужает круг сценариев."
                )

            elif spot_key == "window":
                add_flag(user_id, "checked_window")
                add_clue(user_id, "На подоконнике лежит смятая салфетка с едва заметным запахом энергетика.")
                add_note(user_id, "На подоконнике найдена салфетка с запахом энергетика. Кто-то задерживался здесь с напитком.")
                text = (
                    "Вы проверяете подоконник.\n\n"
                    "Среди мелкого мусора лежит смятая салфетка. От неё едва заметно пахнет сладким энергетиком.\n\n"
                    "Кто-то явно стоял здесь с напитком в руках."
                )

        await safe_show_text_screen(
            query,
            context,
            text + f"\n\n{moves_line(user_id)}",
            reply_markup=reply_markup,
        )

    elif query.data == "cameras":
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        await safe_show_text_screen(
            query,
            context,
            "Вы подходите к записям с камер наблюдения.\n\n"
            f"{moves_line(user_id)}",
            reply_markup=build_cameras_markup(),
        )

    elif query.data.startswith("camera:"):
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        camera_key = query.data.split(":", 1)[1].strip()

        if camera_key not in state["viewed_cameras"]:
            if not spend_move(user_id):
                await safe_show_text_screen(
                    query,
                    context,
                    "Ходы закончились. Пора переходить к обвинению.",
                    reply_markup=build_investigation_menu_markup(),
                )
                return

        if camera_key == "kitchen":
            mark_camera_viewed(user_id, "kitchen")
            add_flag(user_id, "saw_kitchen_camera")
            add_flag(user_id, "saw_maria_on_kitchen_camera")
            add_clue(user_id, "Камера кухни показывает Марию у холодильника и полки с напитками.")
            add_note(user_id, "На записи с кухни видно Марию рядом с напитками. Теперь можно задавать ей более точные вопросы.")

            await safe_show_text_screen(
                query,
                context,
                "Вы просматриваете камеру кухни.\n\n"
                "На записи видно, как Мария задерживается у холодильника и полки с напитками дольше остальных.\n\n"
                "Теперь у Марии открылись новые вопросы по камере кухни.\n\n"
                f"{moves_line(user_id)}",
                reply_markup=build_investigation_menu_markup(),
            )

        elif camera_key == "corridor":
            mark_camera_viewed(user_id, "corridor")
            add_flag(user_id, "saw_corridor_camera")
            add_flag(user_id, "saw_nikita_in_corridor")
            add_clue(user_id, "Камера коридора показывает Никиту у двери комнаты за несколько минут до происшествия.")
            add_note(user_id, "На записи коридора видно Никиту рядом с комнатой Ильи. Его алиби начинает трещать.")

            await safe_show_text_screen(
                query,
                context,
                "Вы просматриваете камеру коридора.\n\n"
                "Никита появляется рядом с дверью комнаты Ильи незадолго до происшествия. Это расходится с его уверенностью про библиотеку.\n\n"
                "Теперь у Никиты открылся новый вопрос по камере коридора.\n\n"
                f"{moves_line(user_id)}",
                reply_markup=build_investigation_menu_markup(),
            )

    elif query.data == "interrogation":
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        await safe_show_text_screen(
            query,
            context,
            "Вы готовитесь к разговору с подозреваемыми.\n\n"
            "Сначала открыты только базовые вопросы. Новые появятся после улик, локаций и камер.\n\n"
            "Выберите человека для допроса:",
            reply_markup=build_interrogation_suspects_markup(),
        )

    elif query.data.startswith("interrogate:"):
        if not state.get("case_started"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала начните расследование.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
                ),
            )
            return

        suspect_key = query.data.split("interrogate:", 1)[1].strip()

        if suspect_key not in state["interrogated"]:
            state["interrogated"].append(suspect_key)
            save_state(user_id)

        await show_interrogation_menu(query, context, user_id, suspect_key)

    elif query.data.startswith("ask:"):
        _, suspect_key, question = query.data.split(":")
        name = SUSPECTS[suspect_key]["name"]

        if question not in get_available_questions(user_id, suspect_key):
            await safe_show_text_screen(
                query,
                context,
                "Этот вопрос пока недоступен. Сначала соберите больше информации.",
                reply_markup=build_questions_markup(user_id, suspect_key),
            )
            return

        if was_question_asked(user_id, suspect_key, question):
            answer = (
                f"{name} уже отвечал на этот вопрос.\n\n"
                "Он не хочет повторяться."
            )
        else:
            mark_question_asked(user_id, suspect_key, question)
            answer = ""

            if suspect_key == "alina":
                if question == "where":
                    answer = "Алина отвечает без паузы.\n\nЯ была на этаже, потом ушла в душевую."
                    add_note(user_id, "Алина утверждает, что после коридора ушла в душевую.")
                elif question == "last_seen":
                    answer = "Алина вспоминает.\n\nЯ видела его у комнаты незадолго до шума."
                elif question == "relation":
                    answer = "Алина пожимает плечами.\n\nОн пару раз жаловался на шум, но мы почти не общались."
                    add_note(user_id, "Алина говорит, что Илья жаловался на шум.")
                elif question == "heard_noise":
                    answer = "Алина кивает.\n\nДа, на этаже было неспокойно. Кто-то явно говорил на повышенных тонах."
                    add_note(user_id, "Алина подтверждает, что вечером на этаже был шум.")
                elif question == "heard_argument":
                    answer = "Алина говорит осторожно.\n\nЭто был короткий спор. Я не могу точно назвать всех, но голосов было больше одного."
                    add_note(user_id, "Алина слышала короткий спор в коридоре.")
                elif question == "kitchen_visit":
                    answer = "Алина отвечает после паузы.\n\nДа, я заходила налить воды, но надолго не оставалась."
                elif question == "kitchen_seen":
                    answer = "Алина вспоминает.\n\nКто-то крутился у холодильника, но я не вглядывалась."

            elif suspect_key == "timur":
                if question == "where":
                    answer = "Тимур отвечает спокойно.\n\nЯ был у себя, потом ненадолго выходил."
                    add_note(user_id, "Тимур говорит, что ненадолго выходил из комнаты.")
                elif question == "last_seen":
                    answer = "Тимур вздыхает.\n\nМы виделись днём. Вечером я только проходил мимо."
                elif question == "relation":
                    answer = "Тимур отвечает глухо.\n\nМы были друзьями. Иногда спорили по учёбе."
                    add_note(user_id, "Тимур говорит, что они с Ильёй были друзьями.")
                elif question == "heard_noise":
                    answer = "Тимур качает головой.\n\nЧто-то слышал, но не придал этому значения."
                elif question == "heard_argument":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур хмурится.\n\nДа, спор был. Но не всё на этаже крутится вокруг меня."
                elif question == "kitchen_visit":
                    answer = "Тимур отвечает чуть суше.\n\nЗаходил. Просто за водой."
                elif question == "energy":
                    answer = "Тимур морщится.\n\nИногда пью энергетики. В тот вечер тоже мог взять банку."
                elif question == "camera_kitchen":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур раздражается.\n\nКамера показывает кухню, а не преступление. Я просто заходил туда на минуту."
                elif question == "corridor_camera":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур говорит жёстче.\n\nЯ проходил мимо, и всё. Не вижу, что тут скрывать."

            elif suspect_key == "nikita":
                if question == "where":
                    answer = "Никита отвечает резко.\n\nЯ был в библиотеке."
                    add_note(user_id, "Никита утверждает, что был в библиотеке.")
                elif question == "last_seen":
                    answer = "Никита отводит взгляд.\n\nМы виделись у комнаты раньше вечером."
                elif question == "relation":
                    answer = "Никита усмехается.\n\nМы делили комнату. Иногда ругались."
                    add_note(user_id, "Никита признаёт, что они часто ругались.")
                elif question == "heard_noise":
                    answer = "Никита говорит коротко.\n\nШум был. Это общежитие."
                elif question == "heard_argument":
                    answer = "Никита отвечает после паузы.\n\nСпор слышал, но не лез."
                elif question == "room":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита раздражается.\n\nЭто была и моя комната тоже."
                elif question == "kitchen_visit":
                    answer = "Никита хмурится.\n\nМог зайти. Не помню точно."
                elif question == "energy":
                    answer = "Никита отвечает уклончиво.\n\nЯ мог взять банку, но не для Ильи."
                elif question == "drink":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита резко отвечает.\n\nЯ не носил ему никакой напиток."
                elif question == "corridor_camera":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита заметно напрягается.\n\nЯ был рядом с дверью, потому что это моя комната. Это ещё ничего не значит."
                    add_note(user_id, "Никита занервничал после упоминания записи с камеры коридора.")

            elif suspect_key == "danil":
                if question == "where":
                    answer = "Данил отвечает уверенно.\n\nЯ обходил этаж."
                    add_note(user_id, "Данил говорит, что обходил этаж вечером.")
                elif question == "last_seen":
                    answer = "Данил говорит спокойно.\n\nВидел Илью мельком в коридоре."
                elif question == "relation":
                    answer = "Данил пожимает плечами.\n\nЯ следил за порядком, не больше."
                elif question == "heard_noise":
                    answer = "Данил вспоминает.\n\nДа, на этаже поднимались голоса."
                elif question == "heard_argument":
                    answer = "Данил отвечает осторожнее.\n\nПохоже, спор был у комнаты, но я не подошёл сразу."
                elif question == "patrol":
                    answer = "Данил кивает.\n\nДа, это моя обязанность."
                elif question == "kitchen_visit":
                    answer = "Данил отвечает ровно.\n\nЗаглядывал туда, как и в другие общие зоны."
                elif question == "energy":
                    answer = "Данил смотрит внимательнее.\n\nЭнергетики там часто стоят, но в тот вечер их брали чаще обычного."
                elif question == "corridor_camera":
                    answer = "Данил спокойно отвечает.\n\nЯ действительно проходил мимо. Мне казалось, это несущественно."

            elif suspect_key == "maria":
                if question == "where":
                    answer = "Мария отвечает спокойно.\n\nЯ была у себя в комнате."
                elif question == "last_seen":
                    answer = "Мария говорит тихо.\n\nПоследний раз видела его днём, после пары."
                elif question == "relation":
                    answer = "Мария опускает глаза.\n\nМы учились вместе, иногда обсуждали задания."
                    add_note(user_id, "Мария училась с Ильёй на одном курсе.")
                elif question == "study":
                    answer = "Мария кивает.\n\nДа, у нас был общий проект."
                    add_note(user_id, "Мария говорит, что они с Ильёй работали над одним проектом.")
                elif question == "heard_noise":
                    answer = "Мария говорит неуверенно.\n\nЧто-то было слышно, но я не вслушивалась."
                elif question == "heard_argument":
                    answer = "Мария немного напрягается.\n\nПоказалось, что кто-то спорил, но я не вышла смотреть."
                elif question == "kitchen_visit":
                    answer = "Мария отвечает после короткой паузы.\n\nДа, я заходила туда ненадолго."
                elif question == "kitchen_seen":
                    answer = "Мария подбирает слова.\n\nНа кухне кто-то был, но я не хочу ошибиться."
                elif question == "phone":
                    answer = "Мария смотрит на вас внимательнее.\n\nНе знаю. Мы не переписывались постоянно."
                elif question == "call":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария заметно напрягается.\n\nОн звонил, но это был короткий разговор. Я не думала, что это важно."
                    add_note(user_id, "Мария сначала умолчала о звонке от Ильи.")
                elif question == "drink":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария отвечает тише.\n\nЯ не приносила ему напиток. Я только заходила на кухню."
                elif question == "camera_kitchen":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария сжимает пальцы.\n\nЯ действительно была на кухне. Брала воду и стояла там дольше, чем собиралась."
                elif question == "poison":
                    worsen_trust_state(user_id, "maria", TRUST_CLOSED)
                    answer = "Мария бледнеет.\n\nНет. Я ничего не добавляла... Я просто не хотела, чтобы всплыл мой разговор с ним."
                    add_note(user_id, "После прямого вопроса про напиток Мария резко закрылась и стала отвечать осторожнее.")

        await safe_show_text_screen(
            query,
            context,
            answer + f"\n\nСостояние: {trust_status_text(user_id, suspect_key)}",
            reply_markup=build_questions_markup(user_id, suspect_key),
        )

    elif query.data == "clues":
        clues = state.get("found_clues", [])
        text = "Вы раскрываете папку с уликами.\n\n"
        if not clues:
            text += "Пока у вас нет найденных улик."
        else:
            text += "\n".join([f"• {c}" for c in clues])

        await safe_show_text_screen(
            query,
            context,
            text,
            reply_markup=build_investigation_menu_markup(),
        )

    elif query.data == "journal":
        notes = state.get("journal", [])
        text = "Вы листаете записи по делу.\n\n"
        if not notes:
            text += "Пока в журнале нет важных заметок."
        else:
            text += "\n".join([f"• {item}" for item in notes])

        await safe_show_text_screen(
            query,
            context,
            text,
            reply_markup=build_investigation_menu_markup(),
        )

    elif query.data == "accuse":
        await safe_show_text_screen(
            query,
            context,
            "Вы подходите к самому опасному шагу расследования.\n\n"
            "Блок обвинения мы добавим следующим этапом, когда закончим логику улик и локаций.",
            reply_markup=build_investigation_menu_markup(),
        )

    else:
        await safe_show_text_screen(
            query,
            context,
            "Неизвестное действие. Вернитесь в меню.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
            ),
        )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не найден. Проверь переменные окружения")

    if not WEBHOOK_URL:
        raise RuntimeError("RENDER_EXTERNAL_URL не найден. Укажи его в Render")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))

    logger.info("Bot is starting with webhook: %s", WEBHOOK_URL)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH.lstrip("/"),
        webhook_url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()