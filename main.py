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

START_MOVES = 22
PLACEHOLDER_PATH = "placeholder.png"

TRUST_NEUTRAL = "neutral"
TRUST_CAREFUL = "careful"
TRUST_CLOSED = "closed"

CORRECT_SUSPECT = "maria"

STRONG_EVIDENCE_FLAGS = {
    "found_drink",
    "found_phone_logs",
    "found_pill_package",
    "saw_maria_on_kitchen_camera",
}

MIN_STRONG_EVIDENCE_TO_WIN = 3

RULES_TEXT = (
    "Правила игры\n\n"
    "Перед вами детективная история с ограниченным числом ходов. "
    f"На одно дело у вас есть {START_MOVES} ходов.\n\n"
    "Ходы тратятся на осмотр локаций, просмотр камер и новые действия расследования. "
    "Журнал, досье и папку с уликами можно открывать бесплатно.\n\n"
    "Часть вопросов открывается только после того, как вы находите новую информацию. "
    "Сначала собирайте факты, потом возвращайтесь к подозреваемым.\n\n"
    "У каждого подозреваемого есть своё состояние. Если вы слишком рано давите, "
    "персонаж станет отвечать суше.\n\n"
    "Чтобы выиграть, нужно выбрать правильного подозреваемого и предъявить достаточно сильных улик."
)

HELP_TEXT = (
    "Помощь\n\n"
    "Лучше сначала осмотреть ключевые места и камеры, а уже потом идти на допрос.\n\n"
    "Журнал помогает не потеряться в нитях расследования.\n\n"
    "Для уверенного обвинения лучше собрать не меньше 3 сильных улик."
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

CLUE_TEXTS = {
    "kitchen_table": "На кухонном столе найдены открытые банки энергетика и липкий след.",
    "pill_package": "В мусорном ведре кухни найдена упаковка от таблеток.",
    "rinsed_mug": "В раковине стоит плохо промытая кружка с горьким запахом.",
    "shared_drinks": "Напитки на кухне были в общем доступе.",
    "victim_drink": "В комнате Ильи найден недопитый напиток с горьким привкусом.",
    "phone_logs": "В телефоне Ильи есть недавний звонок Марии.",
    "room_disturbance": "В комнате заметны следы недавнего беспорядка.",
    "project_notes": "В бумагах Ильи есть записи о проекте и конкурсе на грант.",
    "corridor_argument": "Жильцы коридора подтверждают, что вечером у комнаты был спор.",
    "corridor_drink_trace": "У двери комнаты найден липкий след от напитка.",
    "door_no_break": "На двери комнаты нет следов взлома.",
    "window_napkin": "На подоконнике найдена салфетка с запахом энергетика.",
    "kitchen_camera_maria": "Камера кухни показывает Марию рядом с напитками.",
    "corridor_camera_nikita": "Камера коридора показывает Никиту у двери комнаты.",
    "shower_bitter_smell": "В душевой найден стакан с едва заметным горьким запахом.",
    "shower_wrapper": "У стока в душевой застрял размокший клочок упаковки от таблеток.",
    "shower_wet_trace": "В душевой замечен недавний след воды и спешной уборки.",
    "library_bookmark": "В библиотеке найдено подтверждение, что Никита не провёл там весь вечер.",
    "library_log_gap": "В библиотечном журнале есть временной провал в алиби Никиты.",
    "library_project_print": "В библиотеке сохранилась распечатка проекта с пометками Марии и Ильи.",
}

FLAG_TO_CLUE_KEY = {
    "found_energy_drinks": "kitchen_table",
    "found_pill_package": "pill_package",
    "found_rinsed_mug": "rinsed_mug",
    "checked_fridge": "shared_drinks",
    "found_drink": "victim_drink",
    "found_phone_logs": "phone_logs",
    "found_room_disturbance": "room_disturbance",
    "found_project_notes": "project_notes",
    "heard_argument": "corridor_argument",
    "found_corridor_trace": "corridor_drink_trace",
    "checked_door": "door_no_break",
    "checked_window": "window_napkin",
    "saw_maria_on_kitchen_camera": "kitchen_camera_maria",
    "saw_nikita_in_corridor": "corridor_camera_nikita",
    "found_shower_glass": "shower_bitter_smell",
    "found_shower_wrapper": "shower_wrapper",
    "found_shower_trace": "shower_wet_trace",
    "found_library_bookmark": "library_bookmark",
    "found_library_gap": "library_log_gap",
    "found_library_project": "library_project_print",
}

INTERROGATION_QUESTIONS = {
    "alina": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "kitchen_seen": {"text": "Видели ли вы кого-нибудь на кухне?", "requires": ["visited_kitchen"]},
        "shower": {"text": "Вы были в душевой вечером?", "requires": ["visited_shower"]},
    },
    "timur": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
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
        "project": {"text": "Вы знали о напряжении вокруг проекта?", "requires": ["found_project_notes"]},
    },
    "nikita": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "room": {"text": "Вы были в комнате в тот момент?", "requires": []},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "energy": {"text": "Вы брали энергетики на кухне?", "requires": ["found_energy_drinks"]},
        "drink": {"text": "Кто приносил Илье напиток?", "requires": ["found_drink"]},
        "corridor_camera": {
            "text": "Камера показывает, что вы были у комнаты. Почему вы не сказали об этом?",
            "requires": ["saw_corridor_camera", "saw_nikita_in_corridor"],
        },
        "library": {"text": "Вы точно всё время были в библиотеке?", "requires": ["visited_library"]},
        "library_gap": {"text": "Почему в библиотечном журнале провал во времени?", "requires": ["found_library_gap"]},
    },
    "danil": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "patrol": {"text": "Вы обходили этаж вечером?", "requires": []},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "energy": {"text": "Кто обычно берёт энергетики на кухне?", "requires": ["found_energy_drinks"]},
        "corridor_camera": {
            "text": "Камера показывает, что вы проходили мимо комнаты. Почему вы это не упомянули?",
            "requires": ["saw_corridor_camera", "saw_danil_in_corridor"],
        },
        "shower": {"text": "Кто мог быть в душевой после происшествия?", "requires": ["visited_shower"]},
    },
    "maria": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "study": {"text": "Вы работали с ним по учёбе?", "requires": []},
        "heard_noise": {"text": "Вы слышали шум вечером?", "requires": ["heard_noise"]},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "kitchen_visit": {"text": "Вы заходили на кухню вечером?", "requires": ["visited_kitchen"]},
        "kitchen_seen": {"text": "Видели ли вы кого-нибудь на кухне?", "requires": ["visited_kitchen"]},
        "phone": {"text": "Илья кому-нибудь звонил перед смертью?", "requires": ["found_phone"]},
        "call": {"text": "Илья звонил вам вечером?", "requires": ["found_phone_logs"]},
        "drink": {"text": "Кто приносил Илье напиток?", "requires": ["found_drink"]},
        "camera_kitchen": {
            "text": "Камера показывает, что вы были на кухне. Что вы там делали?",
            "requires": ["saw_kitchen_camera", "saw_maria_on_kitchen_camera"],
        },
        "project": {"text": "Вы конфликтовали из-за гранта?", "requires": ["found_project_notes"]},
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
        "case_finished": False,
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
        "accusation_suspect": None,
        "selected_evidence": [],
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


def reset_case_state(user_id: int) -> None:
    user_state[user_id] = default_state()
    user_state[user_id]["case_started"] = True
    save_state(user_id)


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


def add_clue(user_id: int, clue_text: str) -> None:
    state = get_state(user_id)
    if clue_text not in state["found_clues"]:
        state["found_clues"].append(clue_text)
        save_state(user_id)


def add_clue_by_key(user_id: int, clue_key: str) -> None:
    clue_text = CLUE_TEXTS.get(clue_key)
    if clue_text:
        add_clue(user_id, clue_text)


def has_flags(user_id: int, required_flags: list[str]) -> bool:
    if not required_flags:
        return True
    state = get_state(user_id)
    current_flags = set(state.get("flags", []))
    return all(flag in current_flags for flag in required_flags)


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


def accusation_available_evidence(user_id: int) -> list[tuple[str, str]]:
    state = get_state(user_id)
    evidence = []
    for flag, clue_key in FLAG_TO_CLUE_KEY.items():
        if flag in state["flags"]:
            evidence.append((flag, CLUE_TEXTS[clue_key]))
    return evidence


def toggle_selected_evidence(user_id: int, evidence_flag: str) -> None:
    state = get_state(user_id)
    selected = state["selected_evidence"]
    if evidence_flag in selected:
        selected.remove(evidence_flag)
    else:
        selected.append(evidence_flag)
    save_state(user_id)


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
        [InlineKeyboardButton("Душевая", callback_data="location:shower")],
        [InlineKeyboardButton("Библиотека", callback_data="location:library")],
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
    elif location_key == "shower":
        keyboard = [
            [InlineKeyboardButton("Осмотреть полку", callback_data="spot:shower:shelf")],
            [InlineKeyboardButton("Проверить слив", callback_data="spot:shower:drain")],
            [InlineKeyboardButton("Осмотреть кабину", callback_data="spot:shower:cabin")],
            [InlineKeyboardButton("Проверить умывальник", callback_data="spot:shower:sink")],
            [InlineKeyboardButton("Назад к локациям", callback_data="locations")],
        ]
    elif location_key == "library":
        keyboard = [
            [InlineKeyboardButton("Проверить столы", callback_data="spot:library:tables")],
            [InlineKeyboardButton("Посмотреть журнал посещений", callback_data="spot:library:log")],
            [InlineKeyboardButton("Осмотреть принтер", callback_data="spot:library:printer")],
            [InlineKeyboardButton("Поговорить с дежурной", callback_data="spot:library:librarian")],
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


def build_accusation_suspects_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"accuse_suspect:{key}")]
        for name, key in SUSPECT_ORDER
    ]
    keyboard.append([InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")])
    return InlineKeyboardMarkup(keyboard)


def build_accusation_evidence_markup(user_id: int) -> InlineKeyboardMarkup:
    state = get_state(user_id)
    selected = set(state.get("selected_evidence", []))
    available = accusation_available_evidence(user_id)

    keyboard = []
    for evidence_flag, title in available:
        prefix = "✅ " if evidence_flag in selected else "☑️ "
        keyboard.append([
            InlineKeyboardButton(
                f"{prefix}{title}",
                callback_data=f"toggle_evidence:{evidence_flag}"
            )
        ])

    keyboard.append([InlineKeyboardButton("Подтвердить обвинение", callback_data="confirm_accusation")])
    keyboard.append([InlineKeyboardButton("Выбрать другого подозреваемого", callback_data="accuse")])
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
    state = get_state(user_id)
    if state.get("case_finished"):
        await safe_show_text_screen(
            query,
            context,
            "Это дело уже завершено.\n\n"
            "Вы можете начать новое расследование из главного меню.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Назад в меню", callback_data="main_menu")]]
            ),
        )
        return

    await safe_show_text_screen(
        query,
        context,
        "Вы заходите в холл общежития. Расследование продолжается.\n\n"
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


def accusation_result_text(user_id: int) -> str:
    state = get_state(user_id)
    chosen_suspect = state.get("accusation_suspect")
    chosen_evidence = set(state.get("selected_evidence", []))
    strong_count = len(chosen_evidence & STRONG_EVIDENCE_FLAGS)

    if chosen_suspect == CORRECT_SUSPECT and strong_count >= MIN_STRONG_EVIDENCE_TO_WIN:
        return (
            "Вы собираете показания, сопоставляете улики и окончательно выстраиваете цепочку событий.\n\n"
            "Мария скрыла звонок с Ильёй, была на кухне рядом с напитками, а линия с таблетками и напитком слишком плотно сходится именно к ней.\n\n"
            "Под давлением доказательств она ломается. Дело раскрыто.\n\n"
            "🏆 Победа"
        )

    if chosen_suspect == CORRECT_SUSPECT and strong_count < MIN_STRONG_EVIDENCE_TO_WIN:
        return (
            "Вы выбрали правильного человека, но собранных доказательств пока недостаточно.\n\n"
            "Подозрение выглядит обоснованным, но цепочка всё ещё слишком слабая для уверенного обвинения.\n\n"
            "❌ Поражение, не хватило сильных улик"
        )

    return (
        "Обвинение звучит уверенно, но цепочка не выдерживает проверки.\n\n"
        "Настоящий виновник ускользает, а дело остаётся незакрытым.\n\n"
        "❌ Поражение, обвинён не тот человек"
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
        reset_case_state(user_id)
        await safe_show_text_screen(
            query,
            context,
            "Вы заходите в холл общежития. Сейчас начнётся расследование.\n\n"
            "Перед вами длинный коридор, общая кухня, душевая, библиотека и слишком много людей, которым есть что скрывать.",
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
                "Здесь слышали шум, кто-то проходил мимо в нужное время, а жильцы готовы делиться воспоминаниями.\n\n"
                "Выберите, что осмотреть:"
            )
        elif location_key == "shower":
            add_flag(user_id, "visited_shower")
            text = (
                "Вы заходите в душевую.\n\n"
                "Здесь влажно, кто-то недавно спешно пользовался умывальником, а у слива что-то застряло.\n\n"
                "Выберите, что осмотреть:"
            )
        elif location_key == "library":
            add_flag(user_id, "visited_library")
            text = (
                "Вы приходите в библиотеку.\n\n"
                "На первый взгляд тут тихо, но записи посещений и рабочие места могут разрушить чьё-то алиби.\n\n"
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

        first_time = not was_spot_searched(user_id, full_spot_key)

        if not spend_move_if_first_time(user_id, full_spot_key):
            await safe_show_text_screen(
                query,
                context,
                "Ходы закончились. Пора переходить к обвинению.",
                reply_markup=build_investigation_menu_markup(),
            )
            return

        if not first_time:
            await safe_show_text_screen(
                query,
                context,
                "Вы уже внимательно осматривали это место.\n\n"
                "Новой информации здесь пока нет.\n\n"
                f"{moves_line(user_id)}",
                reply_markup=build_location_actions_markup(location_key),
            )
            return

        text = "Ничего важного."
        reply_markup = build_location_actions_markup(location_key)

        if location_key == "kitchen":
            add_flag(user_id, "visited_kitchen")

            if spot_key == "table":
                add_flag(user_id, "found_energy_drinks")
                add_clue_by_key(user_id, "kitchen_table")
                add_note(user_id, "На кухонном столе найдены энергетики. Теперь можно спрашивать, кто пил их вечером.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди кружек и упаковок стоят открытые банки энергетика. На поверхности липкий след, будто что-то пролили наспех.\n\n"
                    "Теперь открылись вопросы про энергетики."
                )

            elif spot_key == "trash":
                add_flag(user_id, "found_pill_package")
                add_clue_by_key(user_id, "pill_package")
                add_note(user_id, "В мусорном ведре найдена упаковка от таблеток. Это может быть связано с причиной смерти.")
                text = (
                    "Вы проверяете мусорное ведро.\n\n"
                    "Под салфетками и пустыми упаковками лежит смятая блистерная упаковка. В ней не хватает двух таблеток.\n\n"
                    "Это уже серьёзная улика."
                )

            elif spot_key == "sink":
                add_flag(user_id, "found_rinsed_mug")
                add_clue_by_key(user_id, "rinsed_mug")
                add_note(user_id, "В раковине найдена плохо промытая кружка. Возможно, кто-то пытался скрыть следы напитка.")
                text = (
                    "Вы осматриваете раковину.\n\n"
                    "Внутри стоит кружка, которую явно сполоснули наспех. От неё идёт слабый горький запах.\n\n"
                    "Версия с напитком выглядит серьёзнее."
                )

            elif spot_key == "fridge":
                add_flag(user_id, "checked_fridge")
                add_clue_by_key(user_id, "shared_drinks")
                add_note(user_id, "Напитки на кухне были в общем доступе. Это важно для версии с подмешиванием.")
                text = (
                    "Вы проверяете холодильник.\n\n"
                    "Внутри стоят общие напитки, вода и ещё несколько банок. Доступ к ним явно был у всех.\n\n"
                    "Это не даёт имени, но расширяет круг тех, кто мог подмешать что-то в напиток."
                )

        elif location_key == "room":
            if spot_key == "desk":
                add_flag(user_id, "found_drink")
                add_clue_by_key(user_id, "victim_drink")
                add_note(user_id, "В комнате найден недопитый напиток Ильи. Теперь можно спрашивать, кто его приносил.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди тетрадей и зарядки стоит недопитый напиток. Запах сладкий, но во вкусе явно чувствовалась бы горечь.\n\n"
                    "Теперь открылись вопросы про напиток жертвы."
                )

            elif spot_key == "phone":
                add_flag(user_id, "found_phone")
                add_flag(user_id, "found_phone_logs")
                add_clue_by_key(user_id, "phone_logs")
                add_note(user_id, "В телефоне Ильи найден недавний вызов Марии. Теперь можно спрашивать её об этом напрямую.")
                text = (
                    "Вы проверяете телефон.\n\n"
                    "В журнале вызовов есть несколько свежих записей. Один из последних звонков связан с Марией.\n\n"
                    "Теперь у Марии открылся вопрос про звонок."
                )

            elif spot_key == "bedside":
                add_flag(user_id, "found_room_disturbance")
                add_clue_by_key(user_id, "room_disturbance")
                add_note(user_id, "В комнате заметны следы недавнего беспорядка. Версия о конфликте усиливается.")
                text = (
                    "Вы осматриваете кровать и тумбу.\n\n"
                    "Вещи лежат неровно, одна из книг упала на пол, а на тумбе будто что-то резко сдвинули.\n\n"
                    "Похоже, в комнате действительно был напряжённый разговор."
                )

            elif spot_key == "papers":
                add_flag(user_id, "found_project_notes")
                add_clue_by_key(user_id, "project_notes")
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
                add_clue_by_key(user_id, "corridor_argument")
                add_note(user_id, "Жильцы подтверждают, что вечером у комнаты Ильи был спор. Теперь можно задавать прямые вопросы о шуме и ссоре.")
                text = (
                    "Вы разговариваете с жильцами.\n\n"
                    "Несколько человек вспоминают, что вечером у комнаты Ильи действительно звучали раздражённые голоса.\n\n"
                    "Теперь открылись вопросы про шум и спор."
                )

            elif spot_key == "floor":
                add_flag(user_id, "found_corridor_trace")
                add_clue_by_key(user_id, "corridor_drink_trace")
                add_note(user_id, "У комнаты найден след от напитка. Это связывает коридор с версией о подмешивании.")
                text = (
                    "Вы осматриваете пол у комнаты.\n\n"
                    "У порога заметен старый липкий след. Кто-то, похоже, нёс напиток и пролил немного по дороге.\n\n"
                    "Это делает маршрут от кухни до комнаты ещё важнее."
                )

            elif spot_key == "door":
                add_flag(user_id, "checked_door")
                add_clue_by_key(user_id, "door_no_break")
                add_note(user_id, "На двери нет следов взлома. Значит, жертва либо знала гостя, либо не ждала угрозы.")
                text = (
                    "Вы осматриваете дверь.\n\n"
                    "Замок цел, следов взлома нет. Похоже, Илья сам открыл дверь или вообще не опасался того, кто пришёл.\n\n"
                    "Это сужает круг сценариев."
                )

            elif spot_key == "window":
                add_flag(user_id, "checked_window")
                add_clue_by_key(user_id, "window_napkin")
                add_note(user_id, "На подоконнике найдена салфетка с запахом энергетика. Кто-то задерживался здесь с напитком.")
                text = (
                    "Вы проверяете подоконник.\n\n"
                    "Среди мелкого мусора лежит смятая салфетка. От неё едва заметно пахнет сладким энергетиком.\n\n"
                    "Кто-то явно стоял здесь с напитком в руках."
                )

        elif location_key == "shower":
            add_flag(user_id, "visited_shower")

            if spot_key == "shelf":
                add_flag(user_id, "found_shower_glass")
                add_clue_by_key(user_id, "shower_bitter_smell")
                add_note(user_id, "В душевой найден стакан с горьким запахом. Возможно, здесь пытались избавиться от следов.")
                text = (
                    "Вы осматриваете полку.\n\n"
                    "Среди чужих флаконов и мыла стоит пластиковый стакан. От него идёт едва заметный горький запах.\n\n"
                    "Похоже, кто-то пытался смыть следы."
                )

            elif spot_key == "drain":
                add_flag(user_id, "found_shower_wrapper")
                add_clue_by_key(user_id, "shower_wrapper")
                add_note(user_id, "У слива найден размокший клочок упаковки от таблеток. Кто-то явно пытался избавиться от него.")
                text = (
                    "Вы проверяете слив.\n\n"
                    "В решётке застрял размокший кусок упаковки. По форме он слишком похож на часть блистера от таблеток.\n\n"
                    "Это хорошо стыкуется с находкой на кухне."
                )

            elif spot_key == "cabin":
                add_flag(user_id, "found_shower_trace")
                add_clue_by_key(user_id, "shower_wet_trace")
                add_note(user_id, "В душевой видны следы поспешной уборки. Кто-то был здесь уже после происшествия.")
                text = (
                    "Вы осматриваете кабину.\n\n"
                    "На плитке ещё заметны разводы, будто здесь спешно что-то смывали. Следы воды слишком свежие.\n\n"
                    "Кто-то явно торопился."
                )

            elif spot_key == "sink":
                add_flag(user_id, "checked_shower_sink")
                add_note(user_id, "Умывальник в душевой чистый, но запах химии перебивает другие следы.")
                text = (
                    "Вы осматриваете умывальник.\n\n"
                    "Всё выглядит слишком чисто, даже подозрительно. Здесь недавно использовали чистящее средство.\n\n"
                    "Прямой улики нет, но ощущение нехорошее."
                )

        elif location_key == "library":
            add_flag(user_id, "visited_library")

            if spot_key == "tables":
                add_flag(user_id, "found_library_bookmark")
                add_clue_by_key(user_id, "library_bookmark")
                add_note(user_id, "На одном из столов в библиотеке найден след, указывающий, что Никита не провёл здесь весь вечер.")
                text = (
                    "Вы проверяете столы.\n\n"
                    "На одном месте осталась закладка и брошенный лист с пометками. По словам дежурной, Никита сидел там недолго и быстро ушёл.\n\n"
                    "Его алиби начинает шататься."
                )

            elif spot_key == "log":
                add_flag(user_id, "found_library_gap")
                add_clue_by_key(user_id, "library_log_gap")
                add_note(user_id, "В библиотечном журнале есть провал во времени. Никита не мог быть там весь вечер, как утверждает.")
                text = (
                    "Вы листаете журнал посещений.\n\n"
                    "Время входа и отметки не складываются. Получается, что Никита не провёл в библиотеке столько времени, сколько говорил.\n\n"
                    "Теперь можно давить на его алиби."
                )

            elif spot_key == "printer":
                add_flag(user_id, "found_library_project")
                add_clue_by_key(user_id, "library_project_print")
                add_note(user_id, "В библиотеке найдена распечатка проекта с пометками Марии и Ильи. Напряжение вокруг учёбы было реальным.")
                text = (
                    "Вы осматриваете принтер и стопку забытых листов.\n\n"
                    "Среди них лежит распечатка проекта с правками и пометками Марии и Ильи.\n\n"
                    "Учебный конфликт теперь выглядит намного серьёзнее."
                )

            elif spot_key == "librarian":
                add_flag(user_id, "talked_librarian")
                add_note(user_id, "Дежурная помнит, что Никита приходил в библиотеку, но надолго не задержался.")
                text = (
                    "Вы разговариваете с дежурной.\n\n"
                    "Она помнит Никиту, но говорит, что он быстро пришёл и так же быстро ушёл. Для спокойной долгой подготовки это странно.\n\n"
                    "Его версия всё слабее."
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
            add_clue_by_key(user_id, "kitchen_camera_maria")
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
            add_clue_by_key(user_id, "corridor_camera_nikita")
            add_note(user_id, "На записи коридора видно Никиту рядом с комнатой Ильи. Его алиби начинает трещать.")

            await safe_show_text_screen(
                query,
                context,
                "Вы просматриваете камеру коридора.\n\n"
                "Никита появляется рядом с дверью комнаты Ильи незадолго до происшествия. Это расходится с его версией про библиотеку.\n\n"
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
            answer = f"{name} уже отвечал на этот вопрос.\n\nОн не хочет повторяться."
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
                elif question == "heard_noise":
                    answer = "Алина кивает.\n\nДа, на этаже было неспокойно. Кто-то явно говорил на повышенных тонах."
                elif question == "heard_argument":
                    answer = "Алина говорит осторожно.\n\nЭто был короткий спор. Я не могу точно назвать всех, но голосов было больше одного."
                elif question == "kitchen_visit":
                    answer = "Алина отвечает после паузы.\n\nДа, я заходила налить воды, но надолго не оставалась."
                elif question == "kitchen_seen":
                    answer = "Алина вспоминает.\n\nКто-то крутился у холодильника, но я не вглядывалась."
                elif question == "shower":
                    answer = "Алина отвечает чуть быстрее.\n\nДа, я действительно была в душевой позже вечером."

            elif suspect_key == "timur":
                if question == "where":
                    answer = "Тимур отвечает спокойно.\n\nЯ был у себя, потом ненадолго выходил."
                elif question == "last_seen":
                    answer = "Тимур вздыхает.\n\nМы виделись днём. Вечером я только проходил мимо."
                elif question == "relation":
                    answer = "Тимур отвечает глухо.\n\nМы были друзьями. Иногда спорили по учёбе."
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
                elif question == "project":
                    answer = "Тимур отвечает после паузы.\n\nЯ знал, что вокруг проекта у них было напряжение. Но это было скорее между Ильёй и Марией."

            elif suspect_key == "nikita":
                if question == "where":
                    answer = "Никита отвечает резко.\n\nЯ был в библиотеке."
                elif question == "last_seen":
                    answer = "Никита отводит взгляд.\n\nМы виделись у комнаты раньше вечером."
                elif question == "relation":
                    answer = "Никита усмехается.\n\nМы делили комнату. Иногда ругались."
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
                elif question == "library":
                    answer = "Никита отвечает жёстко.\n\nДа, я был в библиотеке. Что ещё вы хотите услышать."
                elif question == "library_gap":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита злится.\n\nЯ выходил ненадолго. Это не делает меня убийцей."

            elif suspect_key == "danil":
                if question == "where":
                    answer = "Данил отвечает уверенно.\n\nЯ обходил этаж."
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
                elif question == "shower":
                    answer = "Данил задумывается.\n\nПосле всего шума туда кто-то действительно мог зайти, чтобы быстро привести себя в порядок."

            elif suspect_key == "maria":
                if question == "where":
                    answer = "Мария отвечает спокойно.\n\nЯ была у себя в комнате."
                elif question == "last_seen":
                    answer = "Мария говорит тихо.\n\nПоследний раз видела его днём, после пары."
                elif question == "relation":
                    answer = "Мария опускает глаза.\n\nМы учились вместе, иногда обсуждали задания."
                elif question == "study":
                    answer = "Мария кивает.\n\nДа, у нас был общий проект."
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
                elif question == "drink":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария отвечает тише.\n\nЯ не приносила ему напиток. Я только заходила на кухню."
                elif question == "camera_kitchen":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария сжимает пальцы.\n\nЯ действительно была на кухне. Брала воду и стояла там дольше, чем собиралась."
                elif question == "project":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария холодеет.\n\nДа, между нами было напряжение из-за проекта и гранта. Но это не значит, что я хотела его смерти."
                elif question == "poison":
                    worsen_trust_state(user_id, "maria", TRUST_CLOSED)
                    answer = "Мария бледнеет.\n\nНет. Я ничего не добавляла... Я просто не хотела, чтобы всплыл мой разговор с ним."

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
        available = accusation_available_evidence(user_id)
        if not available:
            await safe_show_text_screen(
                query,
                context,
                "Пока у вас слишком мало улик для обвинения.\n\n"
                "Сначала осмотрите локации и камеры.",
                reply_markup=build_investigation_menu_markup(),
            )
            return

        state["accusation_suspect"] = None
        state["selected_evidence"] = []
        save_state(user_id)

        await safe_show_text_screen(
            query,
            context,
            "Вы подходите к самому опасному шагу расследования.\n\n"
            "Сначала выберите подозреваемого:",
            reply_markup=build_accusation_suspects_markup(),
        )

    elif query.data.startswith("accuse_suspect:"):
        suspect_key = query.data.split(":", 1)[1].strip()
        state["accusation_suspect"] = suspect_key
        state["selected_evidence"] = []
        save_state(user_id)

        suspect_name = SUSPECTS[suspect_key]["name"]

        await safe_show_text_screen(
            query,
            context,
            f"Вы выбрали подозреваемого: {suspect_name}\n\n"
            "Теперь отметьте доказательства, которые хотите предъявить.\n"
            f"Для уверенного обвинения лучше собрать не меньше {MIN_STRONG_EVIDENCE_TO_WIN} сильных улик.",
            reply_markup=build_accusation_evidence_markup(user_id),
        )

    elif query.data.startswith("toggle_evidence:"):
        evidence_flag = query.data.split(":", 1)[1].strip()
        toggle_selected_evidence(user_id, evidence_flag)

        suspect_key = state.get("accusation_suspect")
        suspect_name = SUSPECTS[suspect_key]["name"] if suspect_key else "не выбран"

        selected_count = len(get_state(user_id).get("selected_evidence", []))
        await safe_show_text_screen(
            query,
            context,
            f"Подозреваемый: {suspect_name}\n\n"
            f"Выбрано доказательств: {selected_count}\n"
            f"Для победы достаточно {MIN_STRONG_EVIDENCE_TO_WIN} сильных улик и правильного подозреваемого.\n\n"
            "Отметьте нужные улики и подтвердите обвинение.",
            reply_markup=build_accusation_evidence_markup(user_id),
        )

    elif query.data == "confirm_accusation":
        if not state.get("accusation_suspect"):
            await safe_show_text_screen(
                query,
                context,
                "Сначала выберите подозреваемого.",
                reply_markup=build_accusation_suspects_markup(),
            )
            return

        state["case_finished"] = True
        save_state(user_id)

        result_text = accusation_result_text(user_id)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Начать новое дело", callback_data="new_case")],
            [InlineKeyboardButton("В меню", callback_data="main_menu")],
        ])

        await safe_show_text_screen(
            query,
            context,
            result_text,
            reply_markup=reply_markup,
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