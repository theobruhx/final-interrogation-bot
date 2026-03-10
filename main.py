import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
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
SAVES_DIR = Path("saves")
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
    "У каждого подозреваемого есть своё состояние. Если вы слишком рано давите или обвиняете без оснований, "
    "персонаж это запомнит и станет отвечать суше.\n\n"
    "Чтобы закончить дело, нужно выбрать подозреваемого и предъявить доказательства."
)

HELP_TEXT = (
    "Помощь\n\n"
    "Нажмите «Начать расследование», чтобы перейти к делу.\n\n"
    "Внутри расследования следите за ходами, собирайте факты, проверяйте алиби и допрашивайте подозреваемых.\n\n"
    "Если запутаетесь, откройте журнал. Туда записываются только важные сведения по делу."
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
        "where": "Где вы были?",
        "noise": "Слышали шум?",
        "relation": "Отношения с Ильёй?",
        "visit": "Были у Ильи?",
    },
    "timur": {
        "where": "Где вы были?",
        "noise": "Слышали шум?",
        "relation": "Отношения с Ильёй?",
        "argument": "Вы спорили?",
    },
    "nikita": {
        "where": "Где вы были?",
        "relation": "Отношения с Ильёй?",
        "room": "Вы были в комнате?",
        "argument": "Вы ругались?",
    },
    "danil": {
        "where": "Где вы были?",
        "noise": "Слышали шум?",
        "relation": "Отношения с Ильёй?",
        "patrol": "Обходили этаж?",
    },
    "maria": {
        "where": "Где вы были?",
        "relation": "Отношения с Ильёй?",
        "study": "Учились вместе?",
        "call": "Он вам звонил?",
    },
}

user_state = {}


def ensure_saves_dir() -> None:
    SAVES_DIR.mkdir(parents=True, exist_ok=True)


def save_path(user_id: int) -> Path:
    return SAVES_DIR / f"user_{user_id}.json"


def default_state() -> dict:
    return {
        "case_started": False,
        "moves_left": START_MOVES,
        "trust_state": {key: TRUST_NEUTRAL for _, key in SUSPECT_ORDER},
        "found_clues": [],
        "viewed_cameras": [],
        "visited_locations": [],
        "journal": [],
        "interrogated": [],
        "asked_questions": {key: [] for _, key in SUSPECT_ORDER},
    }


def load_state(user_id: int) -> dict | None:
    ensure_saves_dir()
    path = save_path(user_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(user_id: int) -> None:
    ensure_saves_dir()
    path = save_path(user_id)
    path.write_text(
        json.dumps(user_state[user_id], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def spend_move(user_id: int) -> bool:
    state = get_state(user_id)
    if state["moves_left"] <= 0:
        return False
    state["moves_left"] -= 1
    save_state(user_id)
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


def build_interrogation_suspects_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"interrogate:{key}")]
        for name, key in SUSPECT_ORDER
    ]
    keyboard.append([InlineKeyboardButton("Назад в расследование", callback_data="back_to_investigation")])
    return InlineKeyboardMarkup(keyboard)


def build_questions_markup(suspect_key: str) -> InlineKeyboardMarkup:
    questions = INTERROGATION_QUESTIONS[suspect_key]
    keyboard = []

    for key, text in questions.items():
        keyboard.append([InlineKeyboardButton(text, callback_data=f"ask:{suspect_key}:{key}")])

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
        "Вы заходите в холл общежития. Сейчас начнётся расследование, приготовьте свои записные книжки.\n\n"
        f"{moves_line(user_id)}",
        reply_markup=build_investigation_menu_markup(),
    )


async def show_interrogation_menu(query, context, user_id: int, suspect_key: str) -> None:
    name = SUSPECTS[suspect_key]["name"]
    await safe_show_text_screen(
        query,
        context,
        f"Вы начинаете разговор с {name}.\n\n"
        f"Состояние: {trust_status_text(user_id, suspect_key)}\n"
        f"{moves_line(user_id)}\n\n"
        "Выберите вопрос:",
        reply_markup=build_questions_markup(suspect_key),
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
            "Вы заходите в холл общежития. Сейчас начнётся расследование, приготовьте свои записные книжки.\n\n"
            "Перед вами длинный коридор, закрытые двери и слишком много людей, которым есть что скрывать.",
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
            "Вы осматриваетесь по сторонам и мысленно отмечаете ключевые точки общежития.\n\n"
            "Здесь позже появятся локации для осмотра.",
            reply_markup=build_investigation_menu_markup(),
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
            "Здесь позже появятся временные интервалы и ключевые кадры.",
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
            "Важно не давить слишком рано и не тратить вопросы впустую.\n\n"
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

        if not spend_move(user_id):
            await safe_show_text_screen(
                query,
                context,
                "Ходы закончились. Пора переходить к обвинению.",
                reply_markup=build_investigation_menu_markup(),
            )
            return

        if suspect_key not in state["interrogated"]:
            state["interrogated"].append(suspect_key)
            save_state(user_id)

        await show_interrogation_menu(query, context, user_id, suspect_key)

    elif query.data.startswith("ask:"):
        _, suspect_key, question = query.data.split(":")
        name = SUSPECTS[suspect_key]["name"]

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
                    trust = get_trust_state(user_id, "alina")
                    if trust == TRUST_CLOSED:
                        answer = "Алина скрещивает руки.\n\nЯ уже сказала всё, что хотела. Была на этаже."
                    elif trust == TRUST_CAREFUL:
                        answer = "Алина отвечает осторожно.\n\nЯ была на этаже. Потом ушла по своим делам."
                    else:
                        answer = "Алина отвечает без паузы.\n\nЯ была на этаже, потом пошла в душевую. По пути видела Илью у комнаты, но мы почти не разговаривали."
                        add_note(user_id, "Алина утверждает, что после коридора ушла в душевую.")

                elif question == "noise":
                    trust = get_trust_state(user_id, "alina")
                    if trust == TRUST_CLOSED:
                        answer = "Алина неохотно отвечает.\n\nМожет, что-то и было. Я не вслушивалась."
                    elif trust == TRUST_CAREFUL:
                        answer = "Алина подбирает слова.\n\nКажется, был какой-то шум, но я не уверена, кто именно спорил."
                        add_note(user_id, "Алина слышала шум в коридоре, но не смогла точно назвать участников.")
                    else:
                        answer = "Алина немного расслабляется.\n\nДа, я слышала какой-то спор в коридоре. Голоса были приглушённые, но потом всё быстро стихло."
                        add_note(user_id, "Алина слышала спор в коридоре вечером.")

                elif question == "relation":
                    trust = get_trust_state(user_id, "alina")
                    if trust == TRUST_CLOSED:
                        answer = "Алина смотрит в сторону.\n\nМы почти не общались."
                    elif trust == TRUST_CAREFUL:
                        answer = "Алина отвечает коротко.\n\nОн иногда жаловался на шум. На этом всё."
                        add_note(user_id, "Алина говорит, что Илья жаловался на шум.")
                    else:
                        answer = "Алина пожимает плечами.\n\nНикакие особо. Он пару раз жаловался на шум, но мы почти не разговаривали."
                        add_note(user_id, "Алина утверждает, что почти не общалась с Ильёй.")

                elif question == "visit":
                    worsen_trust_state(user_id, "alina", TRUST_CAREFUL)
                    trust = get_trust_state(user_id, "alina")
                    if trust == TRUST_CLOSED:
                        answer = "Алина смотрит холодно.\n\nЯ не собираюсь обсуждать это в таком тоне."
                    else:
                        answer = "Алина заметно напрягается.\n\nНет. И мне не нравится, как вы это спрашиваете."

            elif suspect_key == "timur":
                if question == "where":
                    answer = "Тимур отвечает спокойно.\n\nЯ был в комнате. Потом выходил на кухню."
                    add_note(user_id, "Тимур утверждает, что вечером выходил на кухню.")

                elif question == "noise":
                    answer = "Тимур качает головой.\n\nЯ не слышал ничего серьёзного."

                elif question == "relation":
                    answer = "Тимур вздыхает.\n\nМы были друзьями. Иногда спорили по учёбе."
                    add_note(user_id, "Тимур говорит, что они с Ильёй были друзьями.")

                elif question == "argument":
                    worsen_trust_state(user_id, "timur", TRUST_CAREFUL)
                    answer = "Тимур хмурится.\n\nМы иногда спорили. Это нормально."

            elif suspect_key == "nikita":
                if question == "where":
                    answer = "Никита отвечает резко.\n\nЯ был в библиотеке."
                    add_note(user_id, "Никита утверждает, что был в библиотеке.")

                elif question == "relation":
                    answer = "Никита усмехается.\n\nМы делили комнату. Иногда ругались."
                    add_note(user_id, "Никита признаёт, что они часто ругались.")

                elif question == "room":
                    worsen_trust_state(user_id, "nikita", TRUST_CAREFUL)
                    answer = "Никита раздражается.\n\nЭто моя комната тоже."

                elif question == "argument":
                    answer = "Никита отводит взгляд.\n\nДа. Иногда."

            elif suspect_key == "danil":
                if question == "where":
                    answer = "Данил отвечает уверенно.\n\nЯ обходил этаж."
                    add_note(user_id, "Данил говорит, что обходил этаж вечером.")

                elif question == "noise":
                    answer = "Данил задумывается.\n\nКажется, был какой-то шум."

                elif question == "relation":
                    answer = "Данил пожимает плечами.\n\nЯ просто следил за порядком."

                elif question == "patrol":
                    answer = "Данил кивает.\n\nДа. Это моя обязанность."

            elif suspect_key == "maria":
                if question == "where":
                    answer = "Мария отвечает спокойно.\n\nЯ была у себя в комнате."

                elif question == "relation":
                    answer = "Мария говорит тихо.\n\nМы учились вместе."
                    add_note(user_id, "Мария училась с Ильёй на одном курсе.")

                elif question == "study":
                    answer = "Мария кивает.\n\nМы работали над одним проектом."
                    add_note(user_id, "Мария говорит, что они с Ильёй работали над одним проектом.")

                elif question == "call":
                    worsen_trust_state(user_id, "maria", TRUST_CAREFUL)
                    answer = "Мария напрягается.\n\nНет. Он мне не звонил."

        await safe_show_text_screen(
            query,
            context,
            answer + f"\n\nСостояние: {trust_status_text(user_id, suspect_key)}",
            reply_markup=build_questions_markup(suspect_key),
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
            "Здесь позже появится выбор подозреваемого и доказательств.",
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