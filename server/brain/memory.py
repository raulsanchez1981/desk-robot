"""Memoria a largo plazo: lo que tu humano le cuenta y merece recordarse entre conversaciones.

El modelo la lleva él mismo con dos herramientas: `remember` (un dato por llamada, escrito para entenderse solo, con
fechas absolutas) y `forget`. Los recuerdos van en el prompt de sistema de cada pregunta (prompt_block), así que
para unos cientos de datos no hace falta buscador ni base de datos. La fecha y la hora van con cada pregunta
(now_note): así "me voy de vacaciones en un mes" se guarda como una fecha y más adelante sabe cuánto falta.

Se guarda en server/memory.json (git-ignored), en este PC. Los recuerdos viajan al proveedor del modelo con cada
pregunta, como la conversación. Es compartida entre personajes. Standard library only.

    {"version": 1, "next_id": 4, "facts": [
      {"id": 1, "text": "Raúl tiene tres gatas.", "about": "Raúl", "date": null, "private": false,
       "saved": "2026-11-16"}, ...]}
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "memory.json"
MAX_FACTS = 300           # de sobra para una casa; por encima se avisa y no se guardan más
MAX_TEXT = 300
_lock = threading.Lock()
# identity.py los rellena al arrancar: quién está delante (None = nadie dado de alta, no se filtra) y su parte del
# prompt. Con gente dada de alta, los recuerdos privados de alguien solo entran cuando esa persona está delante.
audience: Callable[[], set[str] | None] = lambda: None
extra_prompt: Callable[[], str] = lambda: ""
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _empty() -> dict:
    return {"version": 1, "next_id": 1, "facts": []}


def load(path: Path | None = None) -> dict:
    path = path or PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            return data
    except (OSError, ValueError):
        pass
    return _empty()


def _save(data: dict, path: Path | None = None) -> None:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".memory-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _norm(text: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def _clean_date(value) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def remember(args: dict, path: Path | None = None, today: date | None = None) -> str:
    """La herramienta `remember`. Devuelve el texto para el modelo."""
    text = " ".join(str(args.get("fact") or "").split())[:MAX_TEXT]
    if len(text) < 3:
        return "Nothing saved: the fact was empty."
    about = " ".join(str(args.get("about") or "").split())[:40] or None
    when = _clean_date(args.get("date"))
    private = bool(args.get("private"))
    with _lock:
        data = load(path)
        key = _norm(text)
        for f in data["facts"]:
            if _norm(f["text"]) == key:
                f.update(about=about or f.get("about"), date=when or f.get("date"), private=private or f.get("private"))
                _save(data, path)
                return f"Already remembered (#{f['id']}); updated."
        if len(data["facts"]) >= MAX_FACTS:
            return f"Memory is full ({MAX_FACTS} facts): ask your human to let you forget something first."
        fid = data["next_id"]
        data["next_id"] = fid + 1
        data["facts"].append({"id": fid, "text": text, "about": about, "date": when, "private": private,
                              "saved": (today or date.today()).isoformat()})
        _save(data, path)
    print(f"  (memory: saved #{fid}: {text})")
    return f"Saved as memory #{fid}. Confirm it in a few words, in character."


def forget(args: dict, path: Path | None = None) -> str:
    """La herramienta `forget`: por número (#3) o por texto (los recuerdos que lo contienen)."""
    what = str(args.get("fact") or args.get("id") or "").strip()
    if not what:
        return "Nothing forgotten: say which memory."
    with _lock:
        data = load(path)
        m = re.fullmatch(r"#?\s*(\d+)", what)
        if m:
            gone = [f for f in data["facts"] if f["id"] == int(m.group(1))]
        else:
            key = _norm(what)
            gone = [f for f in data["facts"] if key and (key in _norm(f["text"]) or _norm(f["text"]) in key)]
        if not gone:
            return "No memory matches that; nothing forgotten."
        ids = {f["id"] for f in gone}
        data["facts"] = [f for f in data["facts"] if f["id"] not in ids]
        _save(data, path)
    for f in gone:
        print(f"  (memory: forgot #{f['id']}: {f['text']})")
    return f"Forgotten: {'; '.join(f['text'] for f in gone)}"


def now_note(now: datetime | None = None) -> str:
    """La fecha y la hora, para cada pregunta."""
    now = now or datetime.now()
    return f"(Now: {_DAYS[now.weekday()]} {now.strftime('%Y-%m-%d %H:%M')}.)"


def prompt_block(path: Path | None = None, human: str = "") -> str:
    """Los recuerdos y cómo usarlos, para el final del prompt de sistema. human: cómo se llama su humano."""
    who = human if human and human.lower() != "friend" else         "your human, whose name you don't know yet: write \"mi humano\" / \"my human\""
    present = audience()
    facts = [f for f in load(path)["facts"]
             if present is None or not f.get("private") or _norm(f.get("about") or "") in present]
    if facts:
        lines = []
        for f in facts:
            extra = [x for x in (f"about {f['about']}" if f.get("about") else "",
                                 f"date {f['date']}" if f.get("date") else "",
                                 "private" if f.get("private") else "") if x]
            lines.append(f"- #{f['id']} {f['text']}" + (f" ({', '.join(extra)})" if extra else ""))
        known = "\n".join(lines)
    else:
        known = "(nothing yet)"
    return f"""

Your long-term memory (things your human told you, kept between conversations and shared by every character):
{known}

Memory rules:
- Saving and forgetting are silent: never talk about memory, saving, dates you worked out or how you store things.
Just react to what your human said, in character, in a few words.
- Use these naturally when they are relevant; never recite the list or mention memory numbers.
- When your human tells you something lasting about themselves, their family, their pets, their plans, dates or
preferences ("I have three cats", "my daughter is called Ana", "I'm going on holiday in a month"), save it with
`remember`: one fact per call, short, written so it makes sense on its own later, in the third person with names
(your human is {who}; never write "the user"), with the person or pet it is about, and with an absolute date
(YYYY-MM-DD) for anything in time, worked out from today's date. Never put relative times ("in a month", "tomorrow")
in a memory: they stop being true. Don't save small talk, moods of the moment or things you can see.
- When they correct or cancel something, `forget` the old memory and `remember` the new one. When they ask you to
forget something, do it. When they ask what you know about them, tell them in a sentence or two.
- If they say something is private or secret, save it with private true and only mention it to them.
- Never save passwords, card numbers, codes or other secrets of that kind, even if asked.
- Each question comes with the current date and time: use it for anything about time (how long until a date)."""         + extra_prompt()


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save one lasting fact your human told you (about them, family, pets, plans, dates, "
                           "preferences) to your long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The fact, short and self-contained, in your human's "
                             "language, with absolute dates. E.g. \"Raúl tiene tres gatas.\""},
                    "about": {"type": "string", "description": "Who it is about (a person or pet name), if anyone."},
                    "date": {"type": "string", "description": "YYYY-MM-DD, for a fact about a day (a trip, a "
                             "birthday)."},
                    "private": {"type": "boolean", "description": "true only if your human said to keep it private."},
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove a memory: when your human corrects or cancels something, or asks you to forget it.",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string", "description": "The memory's number (#3) or its words."}},
                "required": ["fact"],
            },
        },
    },
]
QUICK = {"remember", "forget"}
