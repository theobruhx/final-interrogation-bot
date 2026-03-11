import os
import json
import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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

START_MOVES = 24

TRUST_NEUTRAL = "neutral"
TRUST_CAREFUL = "careful"
TRUST_CLOSED = "closed"

CORRECT_SUSPECT = "maria"
TIME_OF_DEATH = "22:45"

SUSPECT_PHOTOS = {
    "alina": "pic/suspects/Alina.png",
    "danil": "pic/suspects/Danil.png",
    "maria": "pic/suspects/Maria.png",
    "nikita": "pic/suspects/Nikita.png",
    "timur": "pic/suspects/Timur.png",
}

LOCATION_PHOTOS = {
    "kitchen": "pic/locations/kitchen.png",
    "room": "pic/locations/dorm_room.png",
    "corridor": "pic/locations/corridor.png",
    "shower": "pic/locations/shower.png",
    "library": "pic/locations/library.png",
}

SPOT_PHOTOS = {
    "kitchen:table": "pic/kitchen/knife.png",
    "kitchen:trash": "pic/kitchen/trash.png",
    "kitchen:sink": "pic/kitchen/kitchen_sink.png",
    "kitchen:fridge": "pic/kitchen/refrigerator.png",

    "room:desk": "pic/dorm_room/desk.png",
    "room:phone": "pic/dorm_room/phone.png",
    "room:bedside": "pic/dorm_room/earring.png",
    "room:papers": "pic/dorm_room/workspace.png",

    "library:log": "pic/logbook.png",
}

CAMERA_MENU_PHOTO = "pic/cctv.png"
JOURNAL_PHOTO = "pic/logbook.png"
ACCUSE_PHOTO = "pic/handcuffs.png"

STRONG_EVIDENCE_FLAGS = {
    "found_shower_wrapper",
    "found_phone_logs",
    "found_drink",
    "saw_maria_kitchen_22_23",
}

MIN_STRONG_EVIDENCE_TO_WIN = 3

RULES_TEXT = (
    "Правила игры\n\n"
    "Перед вами детективная история с ограниченным числом ходов. "
    f"На одно дело у вас есть {START_MOVES} хода.\n\n"
    "Ходы тратятся на осмотр локаций, просмотр камер по временным промежуткам и новые действия расследования. "
    "Журнал, досье и папку с уликами можно открывать бесплатно.\n\n"
    f"Судмедэксперт предварительно определил время смерти Ильи, {TIME_OF_DEATH}. "
    "Поэтому особенно важно сверять улики с камерами и смотреть, у кого в это время есть алиби.\n\n"
    "Часть вопросов открывается только после того, как вы находите новую информацию. "
    "Сначала собирайте факты, потом возвращайтесь к подозреваемым.\n\n"
    "У каждого подозреваемого есть своё состояние. Если вы слишком рано давите, "
    "персонаж станет отвечать суше.\n\n"
    "Чтобы выиграть, нужно выбрать правильного подозреваемого и предъявить достаточно сильных улик."
)

HELP_TEXT = (
    "Помощь\n\n"
    f"Ключевая точка расследования, время смерти Ильи, {TIME_OF_DEATH}.\n\n"
    "Лучше сначала осмотреть ключевые места и камеры по промежуткам времени, а уже потом идти на допрос.\n\n"
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

Алина живёт в общежитии уже второй год. По словам соседей, часто шумит и устраивает поздние встречи с друзьями. Илья неоднократно жаловался на неё коменданту.

В день происшествия Алина находилась на этаже и могла контактировать с Ильёй. Она утверждает, что вечером занималась своими делами и не заходила к нему незадолго до смерти.
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

В ночь происшествия Тимур утверждает, что почти не выходил из комнаты. При этом его имя всплывает рядом с одной из бытовых улик.
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

В день происшествия Никита сначала говорит, что был занят своими делами. Некоторые детали его слов звучат неуверенно, и он раздражается на уточняющие вопросы.
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
    "time_of_death": f"Судмедэксперт определил предварительное время смерти Ильи, {TIME_OF_DEATH}.",
    "knife": "На кухонном столе найден нож с отпечатками Данила.",
    "glass_shard": "В мусорном ведре кухни найден осколок стакана с отпечатками Тимура.",
    "rinsed_mug": "В раковине стоит плохо промытая кружка с горьким запахом.",
    "shared_drinks": "Напитки на кухне были в общем доступе.",
    "victim_drink": "В комнате Ильи найден недопитый напиток с горьким привкусом.",
    "phone_logs": "В телефоне Ильи есть недавний звонок Марии.",
    "alina_earring": "У кровати найдена серьга Алины.",
    "project_notes": "В бумагах Ильи есть записи о проекте и конкурсе на грант.",
    "corridor_argument": "Жильцы коридора подтверждают, что вечером у комнаты был спор.",
    "nikita_shoeprint": "У двери комнаты найден след обуви, совпадающий с обувью Никиты.",
    "door_no_break": "На двери комнаты нет следов взлома.",
    "window_napkin": "На подоконнике найдена салфетка с запахом энергетика.",
    "shower_bitter_smell": "В душевой найден стакан с едва заметным горьким запахом.",
    "shower_wrapper": "У стока в душевой застрял размокший клочок упаковки от таблеток.",
    "shower_wet_trace": "В душевой замечен недавний след воды и спешной уборки.",
    "library_bookmark": "В библиотеке найдено подтверждение, что Никита не был там весь вечер.",
    "library_log_gap": "В библиотечном журнале есть временной провал в алиби Никиты.",
    "library_project_print": "В библиотеке сохранилась распечатка проекта с пометками Марии и Ильи.",
    "camera_corridor_20_21_alina": "Камера коридора с 20:00 до 21:00 показывает Алину у комнаты Ильи.",
    "camera_corridor_21_22_nikita": "Камера коридора с 21:00 до 22:00 показывает Никиту у двери комнаты.",
    "camera_corridor_22_23_timur": "Камера коридора с 22:00 до 23:00 показывает Тимура в момент, когда у него формируется алиби.",
    "camera_kitchen_21_22_danil": "Камера кухни с 21:00 до 22:00 показывает Данила с ножом, когда он делает бутерброд.",
    "camera_kitchen_22_23_maria": "Камера кухни с 22:00 до 23:00 показывает Марию рядом с напитками незадолго до времени смерти.",
}

FLAG_TO_CLUE_KEY = {
    "known_time_of_death": "time_of_death",
    "found_knife": "knife",
    "found_glass_shard": "glass_shard",
    "found_rinsed_mug": "rinsed_mug",
    "checked_fridge": "shared_drinks",
    "found_drink": "victim_drink",
    "found_phone_logs": "phone_logs",
    "found_alina_earring": "alina_earring",
    "found_project_notes": "project_notes",
    "heard_argument": "corridor_argument",
    "found_nikita_shoeprint": "nikita_shoeprint",
    "checked_door": "door_no_break",
    "checked_window": "window_napkin",
    "found_shower_glass": "shower_bitter_smell",
    "found_shower_wrapper": "shower_wrapper",
    "found_shower_trace": "shower_wet_trace",
    "found_library_bookmark": "library_bookmark",
    "found_library_gap": "library_log_gap",
    "found_library_project": "library_project_print",
    "saw_alina_corridor_20_21": "camera_corridor_20_21_alina",
    "saw_nikita_corridor_21_22": "camera_corridor_21_22_nikita",
    "saw_timur_corridor_22_23": "camera_corridor_22_23_timur",
    "saw_danil_kitchen_21_22": "camera_kitchen_21_22_danil",
    "saw_maria_kitchen_22_23": "camera_kitchen_22_23_maria",
}

INTERROGATION_QUESTIONS = {
    "alina": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "earring": {"text": "Почему ваша серьга была у кровати Ильи?", "requires": ["found_alina_earring"]},
        "camera": {
            "text": "Камера показывает вас у комнаты с 20:00 до 21:00. Что вы там делали?",
            "requires": ["saw_corridor_20_21", "saw_alina_corridor_20_21"],
        },
        "shower": {"text": "Вы были в душевой вечером?", "requires": ["visited_shower"]},
    },
    "timur": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "heard_argument": {"text": "Вы слышали спор в коридоре?", "requires": ["heard_argument"]},
        "glass": {"text": "Почему на осколке стакана ваши отпечатки?", "requires": ["found_glass_shard"]},
        "camera": {
            "text": "Камера показывает вас в коридоре в промежутке 22:00–23:00. Объясните.",
            "requires": ["saw_corridor_22_23", "saw_timur_corridor_22_23"],
        },
        "project": {"text": "Вы знали о напряжении вокруг проекта?", "requires": ["found_project_notes"]},
    },
    "nikita": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "room": {"text": "Вы были в комнате в тот момент?", "requires": []},
        "shoeprint": {"text": "Почему след у двери совпадает с вашей обувью?", "requires": ["found_nikita_shoeprint"]},
        "camera": {
            "text": "Камера показывает вас у комнаты с 21:00 до 22:00. Почему вы это не сказали?",
            "requires": ["saw_corridor_21_22", "saw_nikita_corridor_21_22"],
        },
        "library": {"text": "Вы точно всё время были в библиотеке?", "requires": ["visited_library"]},
        "library_gap": {"text": "Почему в библиотечном журнале провал во времени?", "requires": ["found_library_gap"]},
    },
    "danil": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "patrol": {"text": "Вы обходили этаж вечером?", "requires": []},
        "knife": {"text": "Почему на ноже ваши отпечатки?", "requires": ["found_knife"]},
        "camera": {
            "text": "Камера кухни показывает вас с ножом с 21:00 до 22:00. Что вы делали?",
            "requires": ["saw_kitchen_21_22", "saw_danil_kitchen_21_22"],
        },
        "shower": {"text": "Кто мог быть в душевой после происшествия?", "requires": ["visited_shower"]},
    },
    "maria": {
        "where": {"text": "Где вы были вечером?", "requires": []},
        "last_seen": {"text": "Когда вы в последний раз видели Илью?", "requires": []},
        "relation": {"text": "Какие у вас были отношения с Ильёй?", "requires": []},
        "study": {"text": "Вы работали с ним по учёбе?", "requires": []},
        "phone": {"text": "Илья звонил вам вечером?", "requires": ["found_phone_logs"]},
        "drink": {"text": "Кто приносил Илье напиток?", "requires": ["found_drink"]},
        "camera": {
            "text": "Камера кухни показывает вас рядом с напитками с 22:00 до 23:00. Что вы там делали?",
            "requires": ["saw_kitchen_22_23", "saw_maria_kitchen_22_23"],
        },
        "project": {"text": "Вы конфликтовали из-за гранта?", "requires": ["found_project_notes"]},
        "poison": {
            "text": "Вы добавили что-то в напиток Ильи?",
            "requires": ["found_drink", "found_phone_logs", "found_shower_wrapper", "saw_maria_kitchen_22_23"],
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
    user_state[user_id]["flags"].append("known_time_of_death")
    user_state[user_id]["found_clues"].append(CLUE_TEXTS["time_of_death"])
    user_state[user_id]["journal"].append(
        f"Судмедэксперт сообщил предварительное время смерти Ильи, {TIME_OF_DEATH}. "
        "Все алиби нужно проверять относительно этого времени."
    )
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
        [InlineKeyboardButton("Камера кухни", callback_data="camera_select:kitchen")],
        [InlineKeyboardButton("Камера коридора", callback_data="camera_select:corridor")],
        [InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_camera_time_markup(camera_key: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("20:00 - 21:00", callback_data=f"camera:{camera_key}:20_21")],
        [InlineKeyboardButton("21:00 - 22:00", callback_data=f"camera:{camera_key}:21_22")],
        [InlineKeyboardButton("22:00 - 23:00", callback_data=f"camera:{camera_key}:22_23")],
        [InlineKeyboardButton("Назад к камерам", callback_data="cameras")],
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


async def safe_show_photo_screen(query, context, photo_path: str | None, text: str, reply_markup=None, parse_mode=None) -> None:
    if not photo_path or not Path(photo_path).exists():
        await safe_show_text_screen(
            query,
            context,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return

    try:
        if getattr(query.message, "photo", None):
            with Path(photo_path).open("rb") as photo_file:
                media = InputMediaPhoto(
                    media=photo_file,
                    caption=text,
                    parse_mode=parse_mode,
                )
                await query.edit_message_media(
                    media=media,
                    reply_markup=reply_markup,
                )
        else:
            try:
                await query.message.delete()
            except Exception:
                pass

            with Path(photo_path).open("rb") as photo_file:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo_file,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
    except BadRequest:
        try:
            await query.message.delete()
        except Exception:
            pass

        with Path(photo_path).open("rb") as photo_file:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=photo_file,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
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
        f"Время смерти Ильи по предварительным данным, {TIME_OF_DEATH}.\n"
        f"{moves_line(user_id)}",
        reply_markup=build_investigation_menu_markup(),
    )


async def show_interrogation_menu(query, context, user_id: int, suspect_key: str) -> None:
    name = SUSPECTS[suspect_key]["name"]
    available_questions = get_available_questions(user_id, suspect_key)
    photo_path = SUSPECT_PHOTOS.get(suspect_key)

    await safe_show_photo_screen(
        query,
        context,
        photo_path,
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
            "Вы сопоставляете время смерти, записи с камер и найденные улики.\n\n"
            "У каждого из остальных подозреваемых появляется объяснение своей улики или алиби. "
            "Только линия Марии не распадается, звонок, напиток, таблетки и запись с кухни сходятся в одну цепочку.\n\n"
            "Под давлением доказательств Мария ломается. Дело раскрыто.\n\n"
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
            f"Судмедэксперт уже назвал предварительное время смерти Ильи, {TIME_OF_DEATH}.\n"
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
        photo_path = SUSPECT_PHOTOS.get(key)

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Назад к списку", callback_data="suspects")],
            [InlineKeyboardButton("Назад в меню", callback_data="main_menu")],
        ])

        await safe_show_photo_screen(
            query,
            context,
            photo_path,
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
            f"Известное время смерти, {TIME_OF_DEATH}.\n"
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
        photo_path = LOCATION_PHOTOS.get(location_key)

        if location_key == "kitchen":
            add_flag(user_id, "visited_kitchen")
            text = (
                "Вы входите на общую кухню.\n\n"
                "На столе лежит посуда, один нож оставили прямо на столешнице, раковину явно споласкивали наспех, а мусорное ведро переполнено.\n\n"
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
                "Здесь слышали шум, кто-то проходил мимо в важные промежутки времени, а жильцы готовы делиться воспоминаниями.\n\n"
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

        await safe_show_photo_screen(
            query,
            context,
            photo_path,
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
        photo_path = SPOT_PHOTOS.get(full_spot_key)

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
            await safe_show_photo_screen(
                query,
                context,
                photo_path,
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
                add_flag(user_id, "found_knife")
                add_clue_by_key(user_id, "knife")
                add_note(user_id, "На кухонном столе найден нож с отпечатками Данила. Пока это выглядит подозрительно, но нужно сверить с камерами.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди кружек и тарелок лежит кухонный нож. На рукоятке хорошо читаются отпечатки Данила.\n\n"
                    "Это сильная подозрительная улика, но пока не ясно, связана ли она с убийством."
                )

            elif spot_key == "trash":
                add_flag(user_id, "found_glass_shard")
                add_clue_by_key(user_id, "glass_shard")
                add_note(user_id, "В мусорном ведре найден осколок стакана с отпечатками Тимура. Это может указывать на конфликт, но пока слишком рано делать выводы.")
                text = (
                    "Вы проверяете мусорное ведро.\n\n"
                    "Под салфетками и упаковками лежит крупный осколок стакана. На нём различимы отпечатки Тимура.\n\n"
                    "Похоже, стакан разбили незадолго до происшествия."
                )

            elif spot_key == "sink":
                add_flag(user_id, "found_rinsed_mug")
                add_clue_by_key(user_id, "rinsed_mug")
                add_note(user_id, "В раковине найдена плохо промытая кружка. Возможно, кто-то пытался скрыть следы напитка.")
                text = (
                    "Вы осматриваете раковину.\n\n"
                    "Внутри стоит кружка, которую явно сполоснули наспех. От неё идёт слабый горький запах.\n\n"
                    "Версия с напитком начинает выглядеть серьёзнее."
                )

            elif spot_key == "fridge":
                add_flag(user_id, "checked_fridge")
                add_clue_by_key(user_id, "shared_drinks")
                add_note(user_id, "Напитки на кухне были в общем доступе. Это важно для версии с подмешиванием.")
                text = (
                    "Вы проверяете холодильник.\n\n"
                    "Внутри стоят общие напитки, вода и несколько банок. Доступ к ним явно был у всех.\n\n"
                    "Это не называет виновного, но показывает, что подойти к напиткам мог не один человек."
                )

        elif location_key == "room":
            if spot_key == "desk":
                add_flag(user_id, "found_drink")
                add_clue_by_key(user_id, "victim_drink")
                add_note(user_id, "В комнате найден недопитый напиток Ильи. Теперь можно спрашивать, кто его приносил.")
                text = (
                    "Вы осматриваете стол.\n\n"
                    "Среди тетрадей и зарядки стоит недопитый напиток. Запах сладкий, но послевкусие у него заметно горчит.\n\n"
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
                add_flag(user_id, "found_alina_earring")
                add_clue_by_key(user_id, "alina_earring")
                add_note(user_id, "У кровати найдена серьга Алины. Это указывает на то, что она была в комнате, но время её присутствия ещё нужно проверить.")
                text = (
                    "Вы осматриваете кровать и тумбу.\n\n"
                    "Под краем кровати блестит серьга. По описанию соседей и фотографиям из досье, она принадлежит Алине.\n\n"
                    "Теперь у Алины появилась очень неприятная улика."
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
                add_note(user_id, "Жильцы подтверждают, что вечером у комнаты Ильи был спор. Теперь можно задавать прямые вопросы о ссоре.")
                text = (
                    "Вы разговариваете с жильцами.\n\n"
                    "Несколько человек вспоминают, что вечером у комнаты Ильи действительно звучали раздражённые голоса.\n\n"
                    "Теперь открылись вопросы про спор."
                )

            elif spot_key == "floor":
                add_flag(user_id, "found_nikita_shoeprint")
                add_clue_by_key(user_id, "nikita_shoeprint")
                add_note(user_id, "У двери комнаты найден след обуви, совпадающий с обувью Никиты. Это выглядит плохо для него.")
                text = (
                    "Вы осматриваете пол у комнаты.\n\n"
                    "У порога заметен отчётливый след обуви. По рисунку подошвы он совпадает с обувью Никиты.\n\n"
                    "Это важная улика против соседа по комнате."
                )

            elif spot_key == "door":
                add_flag(user_id, "checked_door")
                add_clue_by_key(user_id, "door_no_break")
                add_note(user_id, "На двери нет следов взлома. Значит, Илья либо сам открыл, либо не ждал опасности.")
                text = (
                    "Вы осматриваете дверь.\n\n"
                    "Замок цел, следов взлома нет. Похоже, Илья сам впустил того, кто пришёл, или дверь вообще не закрывали.\n\n"
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
                add_note(user_id, "У слива найден размокший клочок упаковки от таблеток. Это уже прямая линия к версии с отравлением.")
                text = (
                    "Вы проверяете слив.\n\n"
                    "В решётке застрял размокший кусок упаковки. По форме он слишком похож на часть блистера от таблеток.\n\n"
                    "Это одна из самых опасных улик в деле."
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

        await safe_show_photo_screen(
            query,
            context,
            photo_path,
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

        await safe_show_photo_screen(
            query,
            context,
            CAMERA_MENU_PHOTO,
            "Вы подходите к записям с камер наблюдения.\n\n"
            f"Предварительное время смерти, {TIME_OF_DEATH}.\n"
            "Выберите камеру, потом нужный промежуток времени.\n\n"
            f"{moves_line(user_id)}",
            reply_markup=build_cameras_markup(),
        )

    elif query.data.startswith("camera_select:"):
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
        camera_name = "кухни" if camera_key == "kitchen" else "коридора"

        await safe_show_photo_screen(
            query,
            context,
            CAMERA_MENU_PHOTO,
            f"Вы выбираете запись с камеры {camera_name}.\n\n"
            "Укажите временной промежуток:",
            reply_markup=build_camera_time_markup(camera_key),
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

        _, camera_key, slot_key = query.data.split(":")
        view_key = f"{camera_key}:{slot_key}"

        if view_key not in state["viewed_cameras"]:
            if not spend_move(user_id):
                await safe_show_text_screen(
                    query,
                    context,
                    "Ходы закончились. Пора переходить к обвинению.",
                    reply_markup=build_investigation_menu_markup(),
                )
                return

        mark_camera_viewed(user_id, view_key)

        text = "На записи ничего полезного."
        reply_markup = build_camera_time_markup(camera_key)

        if camera_key == "kitchen":
            if slot_key == "20_21":
                add_flag(user_id, "saw_kitchen_20_21")
                text = (
                    "Вы просматриваете камеру кухни за 20:00–21:00.\n\n"
                    "На записи тихо. Кухня почти пустая, в нужные минуты никого не видно.\n\n"
                    "На камерах тишина и пусто."
                )

            elif slot_key == "21_22":
                add_flag(user_id, "saw_kitchen_21_22")
                add_flag(user_id, "saw_danil_kitchen_21_22")
                add_clue_by_key(user_id, "camera_kitchen_21_22_danil")
                add_note(user_id, "Камера кухни за 21:00–22:00 показывает Данила с ножом. Он режет хлеб и делает себе бутерброд.")
                text = (
                    "Вы просматриваете камеру кухни за 21:00–22:00.\n\n"
                    "Около 21:37 Данил заходит на кухню, берёт тот самый нож и режет хлеб. Через пару минут он собирает себе бутерброд и уходит."
                )

            elif slot_key == "22_23":
                add_flag(user_id, "saw_kitchen_22_23")
                add_flag(user_id, "saw_maria_kitchen_22_23")
                add_clue_by_key(user_id, "camera_kitchen_22_23_maria")
                add_note(user_id, f"Камера кухни за 22:00–23:00 показывает Марию у холодильника и рядом с напитками примерно в 22:41–22:44, почти перед временем смерти, {TIME_OF_DEATH}.")
                text = (
                    "Вы просматриваете камеру кухни за 22:00–23:00.\n\n"
                    f"Около 22:41 Мария заходит на кухню. Она задерживается у холодильника и полки с напитками дольше остальных, а затем уходит буквально за несколько минут до времени смерти, {TIME_OF_DEATH}.\n\n"
                    "Теперь линия с напитком выглядит намного опаснее именно для неё."
                )

        elif camera_key == "corridor":
            if slot_key == "20_21":
                add_flag(user_id, "saw_corridor_20_21")
                add_flag(user_id, "saw_alina_corridor_20_21")
                add_clue_by_key(user_id, "camera_corridor_20_21_alina")
                add_note(user_id, "Камера коридора за 20:00–21:00 показывает Алину у комнаты Ильи. Она заходит ненадолго и выходит раньше.")
                text = (
                    "Вы просматриваете камеру коридора за 20:00–21:00.\n\n"
                    "Около 20:18 Алина подходит к комнате Ильи, заходит внутрь на короткое время и уже через пару минут выходит обратно."
                )

            elif slot_key == "21_22":
                add_flag(user_id, "saw_corridor_21_22")
                add_flag(user_id, "saw_nikita_corridor_21_22")
                add_clue_by_key(user_id, "camera_corridor_21_22_nikita")
                add_note(user_id, "Камера коридора за 21:00–22:00 показывает Никиту у комнаты.")
                text = (
                    "Вы просматриваете камеру коридора за 21:00–22:00.\n\n"
                    "Около 21:12 Никита подходит к комнате, возится у двери и ненадолго заходит внутрь, а затем быстро выходит."
                )

            elif slot_key == "22_23":
                add_flag(user_id, "saw_corridor_22_23")
                add_flag(user_id, "saw_timur_corridor_22_23")
                add_clue_by_key(user_id, "camera_corridor_22_23_timur")
                add_note(user_id, f"Камера коридора за 22:00–23:00 показывает Тимура в 22:44 у лестницы, на противоположной стороне от комнаты Ильи. Это даёт ему алиби почти впритык ко времени смерти, {TIME_OF_DEATH}.")
                text = (
                    "Вы просматриваете камеру коридора за 22:00–23:00.\n\n"
                    f"В 22:44 Тимур попадает в кадр у лестницы на дальнем конце коридора. Он идёт от автомата с водой и находится слишком далеко от комнаты Ильи в момент, близкий ко времени смерти, {TIME_OF_DEATH}.\n\n"
                    "Для Тимура это выглядит как серьёзное алиби. После 22:50 коридор снова пустеет.\n\n"
                    "На камерах снова тишина и пусто."
                )

        await safe_show_photo_screen(
            query,
            context,
            CAMERA_MENU_PHOTO,
            text + f"\n\n{moves_line(user_id)}",
            reply_markup=reply_markup,
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
                    answer = "Алина отвечает без паузы.\n\nЯ была на этаже, потом уходила по своим делам."
                elif question == "last_seen":
                    answer = "Алина вспоминает.\n\nЯ видела его раньше вечером, но не перед самой смертью."
                elif question == "relation":
                    answer = "Алина пожимает плечами.\n\nОн пару раз жаловался на шум, но мы почти не общались."
                elif question == "heard_argument":
                    answer = "Алина говорит осторожно.\n\nДа, спор точно был, но я не влезала."
                elif question == "earring":
                    worsen_trust_state(user_id, "alina", TRUST_CAREFUL)
                    answer = "Алина заметно напрягается.\n\nЯ заходила раньше, ещё до всего этого. Наверное, тогда и потеряла серьгу."
                elif question == "camera":
                    answer = "Алина быстро отвечает.\n\nДа, это была я. Я заходила к Илье ещё около восьми вечера, мы коротко поговорили, и я ушла. Это было намного раньше."
                elif question == "shower":
                    answer = "Алина кивает.\n\nДа, позже я действительно была в душевой."

            elif suspect_key == "timur":
                if question == "where":
                    answer = "Тимур отвечает спокойно.\n\nЯ был у себя, потом выходил ненадолго."
                elif question == "last_seen":
                    answer = "Тимур вздыхает.\n\nМы виделись раньше. Перед самой смертью я с ним не пересекался."
                elif question == "relation":
                    answer = "Тимур отвечает глухо.\n\nМы были друзьями. Иногда спорили по учёбе."
                elif question == "heard_argument":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур хмурится.\n\nДа, спор был. Но это ещё не делает меня виноватым."
                elif question == "glass":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур морщится.\n\nЯ разбил стакан на кухне раньше вечером. Порезал палец, выбросил осколки и ушёл."
                elif question == "camera":
                    answer = "Тимур отвечает жёстче.\n\nЯ шёл от автомата с водой. Если камера это показывает в 22:44, значит я физически не мог быть в комнате Ильи в ту минуту."
                elif question == "project":
                    answer = "Тимур отвечает после паузы.\n\nЯ знал, что вокруг проекта у них было напряжение. Но это было скорее между Ильёй и Марией."

            elif suspect_key == "nikita":
                if question == "where":
                    answer = "Никита отвечает резко.\n\nЯ был то в комнате, то выходил. Весь вечер по минутам я вам не восстановлю."
                elif question == "last_seen":
                    answer = "Никита отводит взгляд.\n\nМы виделись у комнаты раньше вечером."
                elif question == "relation":
                    answer = "Никита усмехается.\n\nМы делили комнату. Иногда ругались."
                elif question == "room":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита раздражается.\n\nЭто была и моя комната тоже."
                elif question == "shoeprint":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита хмурится.\n\nКонечно это мог быть мой след, я там живу."
                elif question == "camera":
                    answer = "Никита сдержанно отвечает.\n\nДа, я подходил к комнате раньше. Вот вам и объяснение следа. Но это было до времени смерти."
                elif question == "library":
                    answer = "Никита отвечает суше.\n\nЯ заходил в библиотеку, но не сидел там безвылазно."
                elif question == "library_gap":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита злится.\n\nЯ выходил ненадолго. Это не делает меня убийцей."

            elif suspect_key == "danil":
                if question == "where":
                    answer = "Данил отвечает уверенно.\n\nЯ обходил этаж."
                elif question == "last_seen":
                    answer = "Данил говорит спокойно.\n\nВидел Илью мельком раньше вечером."
                elif question == "relation":
                    answer = "Данил пожимает плечами.\n\nЯ следил за порядком, не больше."
                elif question == "patrol":
                    answer = "Данил кивает.\n\nДа, это моя обязанность."
                elif question == "knife":
                    worsen_trust_state(user_id, "danil", TRUST_CAREFUL)
                    answer = "Данил отвечает ровно.\n\nНож мой, потому что я резал хлеб. Это кухня, а не место преступления."
                elif question == "camera":
                    answer = "Данил спокойно отвечает.\n\nВот и всё. Камера подтверждает, что нож был у меня только потому, что я делал себе бутерброд."
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
                elif question == "phone":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария заметно напрягается.\n\nОн звонил, но это был короткий разговор. Я не думала, что это важно."
                elif question == "drink":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария отвечает тише.\n\nЯ не приносила ему напиток. Я только заходила на кухню."
                elif question == "camera":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = (
                        "Мария сжимает пальцы.\n\n"
                        f"Я действительно была на кухне примерно перед {TIME_OF_DEATH}. "
                        "Брала воду и стояла там дольше, чем собиралась."
                    )
                elif question == "project":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария холодеет.\n\nДа, между нами было напряжение из-за проекта и гранта. Но это не значит, что я хотела его смерти."
                elif question == "poison":
                    worsen_trust_state(user_id, "maria", TRUST_CLOSED)
                    answer = "Мария бледнеет.\n\nНет. Я ничего не добавляла... Я просто не хотела, чтобы всплыл мой разговор с ним."

        photo_path = SUSPECT_PHOTOS.get(suspect_key)
        await safe_show_photo_screen(
            query,
            context,
            photo_path,
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

        await safe_show_photo_screen(
            query,
            context,
            JOURNAL_PHOTO,
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

        await safe_show_photo_screen(
            query,
            context,
            ACCUSE_PHOTO,
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

        await safe_show_photo_screen(
            query,
            context,
            ACCUSE_PHOTO,
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
        await safe_show_photo_screen(
            query,
            context,
            ACCUSE_PHOTO,
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

        await safe_show_photo_screen(
            query,
            context,
            ACCUSE_PHOTO,
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