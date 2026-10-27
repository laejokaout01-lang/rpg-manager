from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DEFAULT_DB_PATH = INSTANCE_DIR / "rpg_manager.sqlite3"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("RPG_MANAGER_SECRET_KEY", "local-rpg-manager-key-change-if-needed")
app.config["DATABASE"] = os.environ.get("RPG_MANAGER_DATABASE", str(DEFAULT_DB_PATH))

ALLOWED_FIELD_TYPES = {"text", "textarea", "number", "date", "select", "multiselect", "checkbox"}
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

DEFAULT_TEMPLATE_INSTRUCTION = r'''Ты помогаешь составить шаблон карточки для локального приложения RPG Manager.

Я опишу сеттинг, назначение карточки и нужные сведения. На основе описания создай структуру шаблона. Не придумывай игровые данные конкретного персонажа — создай только пустую форму для будущих записей.

ТРЕБОВАНИЯ К РЕЗУЛЬТАТУ
1. Верни только корректный JSON, без Markdown-ограждений, пояснений до или после JSON.
2. Используй формат и версию, указанные в примере ниже.
3. Не делай шаблон чрезмерно подробным. Добавляй только поля, полезные для описанного назначения. Подробные описания оформляй текстовыми разделами.
4. Для каждого поля укажи уникальный key латиницей: начинать с буквы, далее можно использовать латинские буквы, цифры, дефис и подчёркивание. Не используй пробелы.
5. У каждого поля должны быть key, label, type и required. required — true или false.
6. Допустимые типы полей: text, textarea, number, date, select, multiselect, checkbox.
7. Для select и multiselect добавляй options — массив строк с вариантами выбора. Для остальных типов options не нужен.
8. Текстовые разделы указывай в sections. У каждого раздела должны быть key и title. Разделы предназначены для свободного текста.
9. key всех полей и разделов должен быть уникальным внутри одного шаблона.
10. name — короткое название шаблона; description — краткое пояснение его назначения.
11. Если шаблону нужен автоматический расчёт возраста, для поля даты рождения добавь role: "birth_date", а для поля возраста — role: "age". Это необязательное назначение. Для возраста используй тип number. Для даты рождения используй date, если известна полная дата; если известен только год или нужен свободный формат, используй text.
12. Не добавляй служебные поля базы данных, ID записей или дату создания шаблона: приложение управляет этим самостоятельно.

ТОЧНЫЙ ФОРМАТ
{
  "format": "rpg_manager_template",
  "version": 1,
  "name": "Название шаблона",
  "description": "Для чего предназначен шаблон",
  "fields": [
    {
      "key": "full_name",
      "label": "Полное имя",
      "type": "text",
      "required": true
    },
    {
      "key": "status",
      "label": "Статус",
      "type": "select",
      "required": false,
      "options": ["Неизвестен", "Активен", "Умер"]
    },
    {
      "key": "birth_date",
      "label": "Дата рождения",
      "type": "date",
      "required": false,
      "role": "birth_date"
    },
    {
      "key": "age",
      "label": "Возраст",
      "type": "number",
      "required": false,
      "role": "age"
    }
  ],
  "sections": [
    {
      "key": "biography",
      "title": "Биография"
    },
    {
      "key": "relationships",
      "title": "Семья и связи"
    }
  ]
}

Теперь создай шаблон по моему описанию. Если в моём запросе не хватает важных деталей, выбери разумную минимальную структуру без лишних полей.'''

DEFAULT_TEMPLATE_SCHEMA = {
    "format": "rpg_manager_template",
    "version": 1,
    "name": "Базовая карточка NPC",
    "description": "Небольшой универсальный шаблон, который можно использовать как есть или копировать и изменять.",
    "fields": [
        {"key": "full_name", "label": "Полное имя", "type": "text", "required": True},
        {"key": "aliases", "label": "Другие имена", "type": "text", "required": False},
        {"key": "birth_date", "label": "Дата рождения (дата или год)", "type": "text", "required": False, "role": "birth_date"},
        {"key": "age", "label": "Возраст", "type": "number", "required": False, "role": "age"},
        {"key": "status", "label": "Статус", "type": "text", "required": False},
    ],
    "sections": [
        {"key": "appearance", "title": "Внешность"},
        {"key": "personality", "title": "Характер и поведение"},
        {"key": "biography", "title": "Биография"},
        {"key": "relationships", "title": "Семья и связи"},
        {"key": "notes", "title": "Дополнительные сведения"},
    ],
}

NAV_ITEMS = [
    {"key": "home", "label": "Обзор", "icon": "⌂", "href": "/"},
    {"key": "characters", "label": "Персонажи", "icon": "♙", "href": "/characters"},
    {"key": "games", "label": "Игры и сеттинги", "icon": "▣", "href": "/games"},
    {"key": "templates", "label": "Шаблоны карточек", "icon": "▤", "href": "/templates"},
    {"key": "template_instruction", "label": "Инструкция для ИИ", "icon": "✎", "href": "/settings/template-instruction"},
    {"key": "events", "label": "События", "icon": "◷", "href": "/events"},
    {"key": "projects", "label": "Проекты", "icon": "▱", "href": "/projects"},
    {"key": "lore", "label": "Справочники и лор", "icon": "▥", "href": "/lore"},
    {"key": "prompt", "label": "Конструктор промпта", "icon": "▧", "href": "/prompt"},
    {"key": "history", "label": "История игры", "icon": "↺", "href": "/history"},
]

SECTIONS = {
    "events": {"title": "События", "description": "Здесь будет хронология игровых событий."},
    "projects": {"title": "Проекты", "description": "Здесь будут проекты и сюжетные линии."},
    "lore": {"title": "Справочники и лор", "description": "Здесь будут материалы мира и справочная информация."},
    "prompt": {"title": "Конструктор промпта", "description": "Здесь будет собираться итоговый запрос для ИИ-ГМа."},
    "history": {"title": "История игры", "description": "Здесь будут храниться запросы и ответы ИИ-ГМа."},
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database_path = Path(app.config["DATABASE"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(_exception: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                schema_json TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                setting_name TEXT NOT NULL DEFAULT '',
                current_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS game_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                source_template_id INTEGER,
                name TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                FOREIGN KEY (source_template_id) REFERENCES templates(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                game_template_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
                FOREIGN KEY (game_template_id) REFERENCES game_templates(id) ON DELETE RESTRICT
            );
            CREATE INDEX IF NOT EXISTS idx_game_templates_game ON game_templates(game_id);
            CREATE INDEX IF NOT EXISTS idx_characters_game ON characters(game_id);
            """
        )
        has_templates = db.execute("SELECT COUNT(*) AS amount FROM templates").fetchone()["amount"]
        if not has_templates:
            timestamp = now_iso()
            db.execute(
                "INSERT INTO templates (name, description, schema_json, is_builtin, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (
                    DEFAULT_TEMPLATE_SCHEMA["name"],
                    DEFAULT_TEMPLATE_SCHEMA["description"],
                    json.dumps(DEFAULT_TEMPLATE_SCHEMA, ensure_ascii=False, indent=2),
                    timestamp,
                    timestamp,
                ),
            )
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("template_instruction", DEFAULT_TEMPLATE_INSTRUCTION, now_iso()),
        )
        db.commit()


def validate_schema(raw: Any) -> dict[str, Any]:
    """Normalize and validate a template JSON object before saving it."""
    if not isinstance(raw, dict):
        raise ValueError("В корне JSON должен находиться объект, а не список или строка.")
    if isinstance(raw.get("template"), dict):
        raw = raw["template"]
    name = raw.get("name")
    description = raw.get("description", "")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Укажи название шаблона в поле name.")
    if len(name.strip()) > 120:
        raise ValueError("Название шаблона не должно превышать 120 символов.")
    if not isinstance(description, str):
        raise ValueError("Поле description должно быть строкой.")
    if len(description) > 1000:
        raise ValueError("Описание не должно превышать 1000 символов.")

    fields = raw.get("fields", [])
    sections = raw.get("sections", [])
    if not isinstance(fields, list) or not isinstance(sections, list):
        raise ValueError("Поля fields и sections должны быть массивами.")
    if len(fields) > 100 or len(sections) > 100:
        raise ValueError("В одном шаблоне допускается не более 100 полей и 100 разделов.")

    normalized_fields: list[dict[str, Any]] = []
    normalized_sections: list[dict[str, Any]] = []
    used_keys: set[str] = set()

    for index, item in enumerate(fields, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Поле №{index}: ожидался JSON-объект.")
        key = item.get("key")
        label = item.get("label")
        field_type = item.get("type", "text")
        required = item.get("required", False)
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Поле №{index}: key должен начинаться с латинской буквы и содержать только латинские буквы, цифры, дефис или подчёркивание.")
        if key in used_keys:
            raise ValueError(f"Ключ «{key}» повторяется. Ключи полей и разделов должны быть уникальными.")
        used_keys.add(key)
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Поле «{key}»: укажи непустое название label.")
        if field_type not in ALLOWED_FIELD_TYPES:
            raise ValueError(f"Поле «{label}»: неизвестный тип «{field_type}».")
        if not isinstance(required, bool):
            raise ValueError(f"Поле «{label}»: required должен быть true или false.")
        normalized: dict[str, Any] = {
            "key": key,
            "label": label.strip(),
            "type": field_type,
            "required": required,
        }
        if field_type in {"select", "multiselect"}:
            options = item.get("options", [])
            if isinstance(options, str):
                options = [part.strip() for part in options.split(",") if part.strip()]
            if not isinstance(options, list) or any(not isinstance(option, str) for option in options):
                raise ValueError(f"Поле «{label}»: options должен быть массивом текстовых вариантов.")
            options = [option.strip() for option in options if option.strip()]
            if not options:
                raise ValueError(f"Поле «{label}»: для типа {field_type} добавь хотя бы один вариант в options.")
            if len(options) > 100:
                raise ValueError(f"Поле «{label}»: слишком много вариантов выбора.")
            normalized["options"] = options
        role = item.get("role")
        if role not in (None, "", "birth_date", "age"):
            raise ValueError(f"Поле «{label}»: role может быть только birth_date или age.")
        if role == "birth_date" and field_type not in {"date", "text", "number"}:
            raise ValueError(f"Поле «{label}»: назначение birth_date можно использовать с типом date, text или number.")
        if role == "age" and field_type not in {"number", "text"}:
            raise ValueError(f"Поле «{label}»: назначение age можно использовать с типом number или text.")
        if role:
            normalized["role"] = role
        normalized_fields.append(normalized)

    roles = [field.get("role") for field in normalized_fields if field.get("role")]
    if roles.count("birth_date") > 1 or roles.count("age") > 1:
        raise ValueError("В шаблоне можно отметить не более одного поля как birth_date и не более одного поля как age.")

    for index, item in enumerate(sections, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Раздел №{index}: ожидался JSON-объект.")
        key = item.get("key")
        title = item.get("title", item.get("label"))
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Раздел №{index}: некорректный key.")
        if key in used_keys:
            raise ValueError(f"Ключ «{key}» повторяется. Ключи полей и разделов должны быть уникальными.")
        used_keys.add(key)
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Раздел «{key}»: укажи непустой заголовок title.")
        normalized_sections.append({"key": key, "title": title.strip()})

    return {
        "format": "rpg_manager_template",
        "version": 1,
        "name": name.strip(),
        "description": description.strip(),
        "fields": normalized_fields,
        "sections": normalized_sections,
    }


def parse_json_input(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Не удалось прочитать JSON: строка {exc.lineno}, столбец {exc.colno}. Проверь запятые, кавычки и скобки.") from exc
    return validate_schema(raw)


def get_template(template_id: int) -> sqlite3.Row:
    template = get_db().execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if template is None:
        abort(404)
    return template


def get_game(game_id: int) -> sqlite3.Row:
    game = get_db().execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        abort(404)
    return game


def get_game_template(game_template_id: int, game_id: int | None = None) -> sqlite3.Row:
    if game_id is None:
        row = get_db().execute("SELECT * FROM game_templates WHERE id = ?", (game_template_id,)).fetchone()
    else:
        row = get_db().execute("SELECT * FROM game_templates WHERE id = ? AND game_id = ?", (game_template_id, game_id)).fetchone()
    if row is None:
        abort(404)
    return row


def schema_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        return validate_schema(json.loads(row["schema_json"]))
    except (ValueError, json.JSONDecodeError):
        abort(500, description="Сохранённый шаблон повреждён. Откройте его через резервную копию JSON или восстановите запись.")


def render_template_editor(
    template_row: sqlite3.Row,
    schema: dict[str, Any],
    error: str | None = None,
    mode: str = "library",
    game: sqlite3.Row | None = None,
):
    return render_template(
        "template_edit.html",
        active_page="templates" if mode == "library" else "games",
        template=template_row,
        schema=schema,
        error=error,
        mode=mode,
        game=game,
    )


@app.context_processor
def inject_navigation():
    return {"nav_items": NAV_ITEMS}


@app.get("/")
def index():
    db = get_db()
    stats = {
        "templates": db.execute("SELECT COUNT(*) AS n FROM templates").fetchone()["n"],
        "games": db.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"],
        "characters": db.execute("SELECT COUNT(*) AS n FROM characters").fetchone()["n"],
    }
    recent_games = db.execute(
        """SELECT g.*,
             (SELECT COUNT(*) FROM characters c WHERE c.game_id = g.id) AS character_count,
             (SELECT COUNT(*) FROM game_templates gt WHERE gt.game_id = g.id) AS template_count
           FROM games g ORDER BY g.id DESC LIMIT 4"""
    ).fetchall()
    return render_template("index.html", active_page="home", stats=stats, recent_games=recent_games)


# Template library
@app.get("/templates")
def templates_list():
    rows = get_db().execute(
        """SELECT t.*, (SELECT COUNT(*) FROM game_templates gt WHERE gt.source_template_id = t.id) AS game_usage
           FROM templates t ORDER BY t.is_builtin DESC, t.name COLLATE NOCASE"""
    ).fetchall()
    return render_template("templates_list.html", active_page="templates", templates=rows)


@app.get("/templates/new")
def template_new():
    sample = {
        "format": "rpg_manager_template",
        "version": 1,
        "name": "Новый шаблон NPC",
        "description": "Краткое описание назначения шаблона.",
        "fields": [{"key": "full_name", "label": "Полное имя", "type": "text", "required": True}],
        "sections": [{"key": "biography", "title": "Биография"}],
    }
    return render_template("template_new.html", active_page="templates", error=None, json_text="", sample_json=json.dumps(sample, ensure_ascii=False, indent=2))


@app.post("/templates/blank")
def template_blank():
    timestamp = now_iso()
    schema = {
        "format": "rpg_manager_template",
        "version": 1,
        "name": "Новый шаблон",
        "description": "",
        "fields": [],
        "sections": [],
    }
    db = get_db()
    cursor = db.execute(
        "INSERT INTO templates (name, description, schema_json, is_builtin, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (schema["name"], "", json.dumps(schema, ensure_ascii=False, indent=2), timestamp, timestamp),
    )
    db.commit()
    flash("Создан пустой шаблон. Добавь нужные поля и разделы.", "success")
    return redirect(url_for("template_edit", template_id=cursor.lastrowid))


@app.post("/templates/import")
def template_import():
    json_text = request.form.get("schema_json", "")
    try:
        schema = parse_json_input(json_text)
    except ValueError as exc:
        sample = {
            "format": "rpg_manager_template", "version": 1, "name": "Новый шаблон NPC", "description": "",
            "fields": [{"key": "full_name", "label": "Полное имя", "type": "text", "required": True}],
            "sections": [{"key": "biography", "title": "Биография"}],
        }
        return render_template("template_new.html", active_page="templates", error=str(exc), json_text=json_text, sample_json=json.dumps(sample, ensure_ascii=False, indent=2)), 400
    timestamp = now_iso()
    db = get_db()
    cursor = db.execute(
        "INSERT INTO templates (name, description, schema_json, is_builtin, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (schema["name"], schema["description"], json.dumps(schema, ensure_ascii=False, indent=2), timestamp, timestamp),
    )
    db.commit()
    flash(f"Шаблон «{schema['name']}» импортирован и сохранён.", "success")
    return redirect(url_for("template_edit", template_id=cursor.lastrowid))


@app.get("/templates/<int:template_id>/edit")
def template_edit(template_id: int):
    row = get_template(template_id)
    return render_template_editor(row, schema_from_row(row))


@app.post("/templates/<int:template_id>/edit")
def template_update(template_id: int):
    row = get_template(template_id)
    payload = request.form.get("schema_payload", "")
    try:
        schema = parse_json_input(payload)
    except ValueError as exc:
        try:
            partial = json.loads(payload)
            if not isinstance(partial, dict):
                partial = schema_from_row(row)
        except (json.JSONDecodeError, TypeError):
            partial = schema_from_row(row)
        return render_template_editor(row, partial, str(exc)), 400
    timestamp = now_iso()
    get_db().execute(
        "UPDATE templates SET name = ?, description = ?, schema_json = ?, updated_at = ? WHERE id = ?",
        (schema["name"], schema["description"], json.dumps(schema, ensure_ascii=False, indent=2), timestamp, template_id),
    )
    get_db().commit()
    flash("Шаблон сохранён.", "success")
    return redirect(url_for("template_edit", template_id=template_id))


@app.post("/templates/<int:template_id>/duplicate")
def template_duplicate(template_id: int):
    row = get_template(template_id)
    schema = schema_from_row(row)
    new_name = f"{schema['name']} — копия"
    schema["name"] = new_name
    timestamp = now_iso()
    db = get_db()
    cursor = db.execute(
        "INSERT INTO templates (name, description, schema_json, is_builtin, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (new_name, schema["description"], json.dumps(schema, ensure_ascii=False, indent=2), timestamp, timestamp),
    )
    db.commit()
    flash("Создана независимая копия шаблона. Исходный шаблон не изменён.", "success")
    return redirect(url_for("template_edit", template_id=cursor.lastrowid))


@app.post("/templates/<int:template_id>/delete")
def template_delete(template_id: int):
    row = get_template(template_id)
    if row["is_builtin"]:
        flash("Базовый шаблон нельзя удалить. Его можно скопировать и изменить.", "error")
        return redirect(url_for("templates_list"))
    game_usage = get_db().execute("SELECT COUNT(*) AS n FROM game_templates WHERE source_template_id = ?", (template_id,)).fetchone()["n"]
    get_db().execute("DELETE FROM templates WHERE id = ?", (template_id,))
    get_db().commit()
    if game_usage:
        flash(f"Шаблон удалён из библиотеки. Сохранённые копии в {game_usage} игровом(ых) наборе(ах) не изменены.", "success")
    else:
        flash("Шаблон удалён.", "success")
    return redirect(url_for("templates_list"))


@app.get("/templates/<int:template_id>/export")
def template_export(template_id: int):
    row = get_template(template_id)
    schema = schema_from_row(row)
    content = json.dumps(schema, ensure_ascii=False, indent=2)
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="rpg-template-{template_id}.json"'},
    )


# Editable AI instruction
@app.get("/settings/template-instruction")
def template_instruction():
    row = get_db().execute("SELECT value FROM settings WHERE key = 'template_instruction'").fetchone()
    instruction = row["value"] if row else DEFAULT_TEMPLATE_INSTRUCTION
    return render_template("template_instruction.html", active_page="template_instruction", instruction=instruction, default_instruction=DEFAULT_TEMPLATE_INSTRUCTION)


@app.post("/settings/template-instruction")
def template_instruction_save():
    instruction = request.form.get("instruction", "").strip()
    if not instruction:
        flash("Инструкция не может быть пустой. Можно восстановить исходный текст.", "error")
        return redirect(url_for("template_instruction"))
    if len(instruction) > 100_000:
        flash("Инструкция слишком длинная (максимум 100 000 символов).", "error")
        return redirect(url_for("template_instruction"))
    get_db().execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('template_instruction', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (instruction, now_iso()),
    )
    get_db().commit()
    flash("Инструкция сохранена в локальной базе данных.", "success")
    return redirect(url_for("template_instruction"))


@app.post("/settings/template-instruction/reset")
def template_instruction_reset():
    get_db().execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('template_instruction', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (DEFAULT_TEMPLATE_INSTRUCTION, now_iso()),
    )
    get_db().commit()
    flash("Исходная инструкция восстановлена.", "success")
    return redirect(url_for("template_instruction"))


def valid_world_date(value: str) -> bool:
    value = (value or "").strip()
    try:
        if re.fullmatch(r"\d{4}", value):
            return 1 <= int(value) <= 9999
        if re.fullmatch(r"\d{4}-\d{2}", value):
            datetime.strptime(value, "%Y-%m")
            return True
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            datetime.strptime(value, "%Y-%m-%d")
            return True
    except ValueError:
        return False
    return False


def parse_birth_value(value: Any) -> tuple[int, int | None, int | None] | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        return (year, None, None) if 1 <= year <= 9999 else None
    for pattern, fmt in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y")):
        if re.fullmatch(pattern, text):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.year, parsed.month, parsed.day
            except ValueError:
                return None
    return None


def age_as_of(birth_value: Any, world_date: str) -> int | None:
    birth = parse_birth_value(birth_value)
    if birth is None or not valid_world_date(world_date):
        return None
    birth_year, birth_month, birth_day = birth
    if len(world_date) == 4:
        return int(world_date) - birth_year
    if len(world_date) == 7:
        current_year, current_month = map(int, world_date.split("-"))
        age = current_year - birth_year
        if birth_month is not None and current_month < birth_month:
            age -= 1
        return age
    current = datetime.strptime(world_date, "%Y-%m-%d").date()
    age = current.year - birth_year
    if birth_month is not None and birth_day is not None and (current.month, current.day) < (birth_month, birth_day):
        age -= 1
    return age


def update_character_age_values(schema: dict[str, Any], data: dict[str, Any], world_date: str) -> bool:
    """Apply age calculation only to fields explicitly tagged with roles in the template."""
    if not world_date:
        return False
    fields = schema.get("fields", [])
    birth_field = next((field for field in fields if field.get("role") == "birth_date"), None)
    age_field = next((field for field in fields if field.get("role") == "age"), None)
    if not birth_field or not age_field:
        return False
    values = data.setdefault("fields", {})
    calculated = age_as_of(values.get(birth_field["key"]), world_date)
    if calculated is None or calculated < 0:
        return False
    previous = values.get(age_field["key"])
    values[age_field["key"]] = calculated
    return previous != calculated


def recalculate_ages_for_game(game_id: int, world_date: str) -> int:
    db = get_db()
    changed_count = 0
    linked_templates = db.execute("SELECT * FROM game_templates WHERE game_id = ?", (game_id,)).fetchall()
    for game_template in linked_templates:
        schema = schema_from_row(game_template)
        if not any(field.get("role") == "birth_date" for field in schema["fields"]) or not any(field.get("role") == "age" for field in schema["fields"]):
            continue
        cards = db.execute("SELECT id, data_json FROM characters WHERE game_template_id = ?", (game_template["id"],)).fetchall()
        for card in cards:
            try:
                data = json.loads(card["data_json"])
            except json.JSONDecodeError:
                continue
            if update_character_age_values(schema, data, world_date):
                db.execute("UPDATE characters SET data_json = ?, updated_at = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), now_iso(), card["id"]))
                changed_count += 1
    db.commit()
    return changed_count


# Games and schema snapshots
@app.get("/games")
def games_list():
    games = get_db().execute(
        """SELECT g.*,
             (SELECT COUNT(*) FROM characters c WHERE c.game_id = g.id) AS character_count,
             (SELECT COUNT(*) FROM game_templates gt WHERE gt.game_id = g.id) AS template_count
           FROM games g ORDER BY g.id DESC"""
    ).fetchall()
    return render_template("games_list.html", active_page="games", games=games)


@app.post("/games")
def game_create():
    name = request.form.get("name", "").strip()
    setting_name = request.form.get("setting_name", "").strip()
    current_date = request.form.get("current_date", "").strip()
    if not name:
        flash("Укажи название игры.", "error")
        return redirect(url_for("games_list"))
    if len(name) > 160 or len(setting_name) > 160:
        flash("Название игры и сеттинга не должны превышать 160 символов.", "error")
        return redirect(url_for("games_list"))
    if current_date and not valid_world_date(current_date):
        flash("Дату мира укажи в реальном формате ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД.", "error")
        return redirect(url_for("games_list"))
    cursor = get_db().execute(
        "INSERT INTO games (name, setting_name, current_date, created_at) VALUES (?, ?, ?, ?)",
        (name, setting_name, current_date, now_iso()),
    )
    get_db().commit()
    flash("Игра создана. Добавь к ней нужные шаблоны карточек.", "success")
    return redirect(url_for("game_detail", game_id=cursor.lastrowid))


@app.post("/games/<int:game_id>/date")
def game_update_date(game_id: int):
    game = get_game(game_id)
    current_date = request.form.get("current_date", "").strip()
    if current_date and not valid_world_date(current_date):
        flash("Дату мира укажи в реальном формате ГГГГ, ГГГГ-ММ или ГГГГ-ММ-ДД.", "error")
        return redirect(url_for("game_detail", game_id=game_id))
    get_db().execute("UPDATE games SET current_date = ? WHERE id = ?", (current_date, game_id))
    get_db().commit()
    updated = recalculate_ages_for_game(game_id, current_date) if current_date else 0
    if current_date:
        flash(f"Дата мира обновлена на {current_date}. Автоматически пересчитано возрастов: {updated}.", "success")
    else:
        flash("Дата мира очищена. Возраст больше не пересчитывается автоматически, пока дата не задана.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.get("/games/<int:game_id>")
def game_detail(game_id: int):
    game = get_game(game_id)
    db = get_db()
    linked_templates = db.execute("SELECT * FROM game_templates WHERE game_id = ? ORDER BY name COLLATE NOCASE", (game_id,)).fetchall()
    characters = db.execute(
        "SELECT c.*, gt.name AS template_name FROM characters c JOIN game_templates gt ON gt.id = c.game_template_id WHERE c.game_id = ? ORDER BY c.name COLLATE NOCASE",
        (game_id,),
    ).fetchall()
    available_templates = db.execute(
        """SELECT * FROM templates t WHERE NOT EXISTS (
             SELECT 1 FROM game_templates gt WHERE gt.game_id = ? AND gt.source_template_id = t.id
           ) ORDER BY t.is_builtin DESC, t.name COLLATE NOCASE""",
        (game_id,),
    ).fetchall()
    return render_template(
        "game_detail.html",
        active_page="games",
        game=game,
        linked_templates=linked_templates,
        characters=characters,
        available_templates=available_templates,
    )


@app.post("/games/<int:game_id>/templates/add")
def game_add_template(game_id: int):
    get_game(game_id)
    try:
        source_id = int(request.form.get("template_id", ""))
    except ValueError:
        flash("Выбери шаблон из библиотеки.", "error")
        return redirect(url_for("game_detail", game_id=game_id))
    source = get_template(source_id)
    db = get_db()
    exists = db.execute("SELECT id FROM game_templates WHERE game_id = ? AND source_template_id = ?", (game_id, source_id)).fetchone()
    if exists:
        flash("Этот шаблон уже добавлен в игру.", "error")
        return redirect(url_for("game_detail", game_id=game_id))
    schema = schema_from_row(source)
    db.execute(
        "INSERT INTO game_templates (game_id, source_template_id, name, schema_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (game_id, source_id, schema["name"], json.dumps(schema, ensure_ascii=False, indent=2), now_iso()),
    )
    db.commit()
    flash(f"Шаблон «{schema['name']}» добавлен в игру как отдельная копия структуры.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.post("/games/<int:game_id>/templates/<int:game_template_id>/remove")
def game_remove_template(game_id: int, game_template_id: int):
    get_game(game_id)
    linked = get_game_template(game_template_id, game_id)
    used_count = get_db().execute("SELECT COUNT(*) AS n FROM characters WHERE game_template_id = ?", (game_template_id,)).fetchone()["n"]
    if used_count:
        flash(f"Нельзя убрать этот шаблон: на его основе создано карточек: {used_count}. Сначала удалите эти карточки.", "error")
    else:
        get_db().execute("DELETE FROM game_templates WHERE id = ?", (linked["id"],))
        get_db().commit()
        flash("Шаблон убран из игры. Шаблон в общей библиотеке не изменён.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.get("/games/<int:game_id>/templates/<int:game_template_id>/edit")
def game_template_edit(game_id: int, game_template_id: int):
    game = get_game(game_id)
    game_template = get_game_template(game_template_id, game_id)
    return render_template_editor(game_template, schema_from_row(game_template), mode="game", game=game)


@app.post("/games/<int:game_id>/templates/<int:game_template_id>/edit")
def game_template_update(game_id: int, game_template_id: int):
    game = get_game(game_id)
    game_template = get_game_template(game_template_id, game_id)
    payload = request.form.get("schema_payload", "")
    try:
        schema = parse_json_input(payload)
    except ValueError as exc:
        try:
            partial = json.loads(payload)
            if not isinstance(partial, dict):
                partial = schema_from_row(game_template)
        except (json.JSONDecodeError, TypeError):
            partial = schema_from_row(game_template)
        return render_template_editor(game_template, partial, str(exc), mode="game", game=game), 400
    get_db().execute(
        "UPDATE game_templates SET name = ?, schema_json = ? WHERE id = ? AND game_id = ?",
        (schema["name"], json.dumps(schema, ensure_ascii=False, indent=2), game_template_id, game_id),
    )
    get_db().commit()
    flash("Структура шаблона обновлена в этой игре. Новые поля появятся в карточках этого типа; пустые значения можно заполнить при следующем редактировании.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.get("/games/<int:game_id>/templates/<int:game_template_id>/export")
def game_template_export(game_id: int, game_template_id: int):
    game = get_game(game_id)
    row = get_game_template(game_template_id, game_id)
    schema = schema_from_row(row)
    content = json.dumps(schema, ensure_ascii=False, indent=2)
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="rpg-game-{game_id}-template-{game_template_id}.json"'},
    )


# Character cards (based on a game's frozen template schema)
def render_character_editor(game: sqlite3.Row, game_template: sqlite3.Row, card: sqlite3.Row | None = None, data: dict[str, Any] | None = None, error: str | None = None):
    schema = schema_from_row(game_template)
    if data is None:
        data = {"fields": {}, "sections": {}}
    return render_template(
        "character_edit.html",
        active_page="characters",
        game=game,
        game_template=game_template,
        schema=schema,
        card=card,
        data=data,
        error=error,
    )


def clean_character_values(schema: dict[str, Any], form) -> tuple[dict[str, Any], str | None]:
    fields: dict[str, Any] = {}
    sections: dict[str, str] = {}
    errors: list[str] = []
    for field in schema["fields"]:
        key = field["key"]
        input_name = f"field_{key}"
        field_type = field["type"]
        if field_type == "checkbox":
            value: Any = form.get(input_name) == "on"
        elif field_type == "multiselect":
            value = form.getlist(input_name)
        else:
            value = form.get(input_name, "").strip()
        if field["required"] and (value is False or value == "" or value == []):
            errors.append(f"Заполни обязательное поле «{field['label']}».")
        if field_type == "select" and value and value not in field.get("options", []):
            errors.append(f"Недопустимый вариант в поле «{field['label']}».")
        if field_type == "multiselect" and any(option not in field.get("options", []) for option in value):
            errors.append(f"Недопустимый вариант в поле «{field['label']}».")
        fields[key] = value
    for section in schema["sections"]:
        sections[section["key"]] = form.get(f"section_{section['key']}", "").strip()
    data = {"fields": fields, "sections": sections}
    if errors:
        return data, " ".join(errors)
    return data, None


def character_display_name(schema: dict[str, Any], data: dict[str, Any]) -> str:
    values = data.get("fields", {})
    for candidate_key in ("full_name", "name", "character_name"):
        value = values.get(candidate_key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    for field in schema["fields"]:
        value = values.get(field["key"])
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return "Безымянный персонаж"


@app.get("/characters")
def characters_list():
    rows = get_db().execute(
        """SELECT c.*, g.name AS game_name, gt.name AS template_name
           FROM characters c JOIN games g ON g.id = c.game_id
           JOIN game_templates gt ON gt.id = c.game_template_id
           ORDER BY c.id DESC"""
    ).fetchall()
    return render_template("characters_list.html", active_page="characters", characters=rows)


@app.get("/games/<int:game_id>/characters/new")
def character_new(game_id: int):
    game = get_game(game_id)
    db = get_db()
    templates = db.execute("SELECT * FROM game_templates WHERE game_id = ? ORDER BY name COLLATE NOCASE", (game_id,)).fetchall()
    if not templates:
        flash("Сначала добавь хотя бы один шаблон в эту игру.", "error")
        return redirect(url_for("game_detail", game_id=game_id))
    requested_id = request.args.get("template_id", type=int)
    if requested_id is None:
        if len(templates) == 1:
            return redirect(url_for("character_new", game_id=game_id, template_id=templates[0]["id"]))
        return render_template("choose_character_template.html", active_page="characters", game=game, templates=templates)
    game_template = get_game_template(requested_id, game_id)
    return render_character_editor(game, game_template)


@app.post("/games/<int:game_id>/characters/new")
def character_create(game_id: int):
    game = get_game(game_id)
    try:
        game_template_id = int(request.form.get("game_template_id", ""))
    except ValueError:
        abort(400, description="Не выбран шаблон карточки.")
    game_template = get_game_template(game_template_id, game_id)
    schema = schema_from_row(game_template)
    data, error = clean_character_values(schema, request.form)
    if error:
        return render_character_editor(game, game_template, data=data, error=error), 400
    update_character_age_values(schema, data, game["current_date"])
    timestamp = now_iso()
    name = character_display_name(schema, data)
    cursor = get_db().execute(
        "INSERT INTO characters (game_id, game_template_id, name, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, game_template_id, name, json.dumps(data, ensure_ascii=False), timestamp, timestamp),
    )
    get_db().commit()
    flash(f"Карточка «{name}» создана.", "success")
    return redirect(url_for("character_edit", game_id=game_id, character_id=cursor.lastrowid))


@app.get("/games/<int:game_id>/characters/<int:character_id>/edit")
def character_edit(game_id: int, character_id: int):
    game = get_game(game_id)
    card = get_db().execute("SELECT * FROM characters WHERE id = ? AND game_id = ?", (character_id, game_id)).fetchone()
    if card is None:
        abort(404)
    game_template = get_game_template(card["game_template_id"], game_id)
    try:
        data = json.loads(card["data_json"])
    except json.JSONDecodeError:
        data = {"fields": {}, "sections": {}}
    return render_character_editor(game, game_template, card, data)


@app.post("/games/<int:game_id>/characters/<int:character_id>/edit")
def character_update(game_id: int, character_id: int):
    game = get_game(game_id)
    card = get_db().execute("SELECT * FROM characters WHERE id = ? AND game_id = ?", (character_id, game_id)).fetchone()
    if card is None:
        abort(404)
    game_template = get_game_template(card["game_template_id"], game_id)
    schema = schema_from_row(game_template)
    data, error = clean_character_values(schema, request.form)
    if error:
        return render_character_editor(game, game_template, card, data, error), 400
    update_character_age_values(schema, data, game["current_date"])
    name = character_display_name(schema, data)
    get_db().execute(
        "UPDATE characters SET name = ?, data_json = ?, updated_at = ? WHERE id = ?",
        (name, json.dumps(data, ensure_ascii=False), now_iso(), character_id),
    )
    get_db().commit()
    flash("Карточка сохранена.", "success")
    return redirect(url_for("character_edit", game_id=game_id, character_id=character_id))


@app.post("/games/<int:game_id>/characters/<int:character_id>/delete")
def character_delete(game_id: int, character_id: int):
    get_game(game_id)
    card = get_db().execute("SELECT id FROM characters WHERE id = ? AND game_id = ?", (character_id, game_id)).fetchone()
    if card is None:
        abort(404)
    get_db().execute("DELETE FROM characters WHERE id = ?", (character_id,))
    get_db().commit()
    flash("Карточка персонажа удалена.", "success")
    return redirect(url_for("game_detail", game_id=game_id))


@app.get("/<section_key>")
def section(section_key: str):
    section_info = SECTIONS.get(section_key)
    if section_info is None:
        abort(404)
    return render_template("section.html", active_page=section_key, section=section_info)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
