"""Reads the posting calendar (agenda/*.yaml) and publishes what is due."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import yaml

PLATFORMS = {"instagram": {"post", "carrossel", "reels", "stories"}, "tiktok": {"video"}}
MAX_ATTEMPTS = 3


class AgendaError(ValueError):
    pass


@dataclass
class Item:
    id: str
    when: datetime
    platform: str
    kind: str
    files: list[str]
    caption: str = ""
    brand_organic: bool | None = None
    source: str = ""

    @classmethod
    def parse(cls, raw: dict, tz: ZoneInfo, source: str = "") -> "Item":
        where = f"{source}: item {raw.get('id', '?')}"
        for key in ("id", "quando", "plataforma", "tipo"):
            if not raw.get(key):
                raise AgendaError(f"{where} sem o campo '{key}'")
        platform = str(raw["plataforma"]).lower()
        kind = str(raw["tipo"]).lower()
        if platform not in PLATFORMS:
            raise AgendaError(f"{where}: plataforma '{platform}' invalida (use instagram ou tiktok)")
        if kind not in PLATFORMS[platform]:
            raise AgendaError(f"{where}: tipo '{kind}' invalido para {platform} {sorted(PLATFORMS[platform])}")
        files = raw.get("arquivos") or ([raw["arquivo"]] if raw.get("arquivo") else [])
        if not files:
            raise AgendaError(f"{where} sem 'arquivo' (ou 'arquivos' no carrossel)")
        when = raw["quando"]
        if isinstance(when, str):
            try:
                when = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M")
            except ValueError as exc:
                raise AgendaError(f"{where}: 'quando' deve ser 'AAAA-MM-DD HH:MM'") from exc
        if not isinstance(when, datetime):
            raise AgendaError(f"{where}: 'quando' deve ser 'AAAA-MM-DD HH:MM'")
        if when.tzinfo is None:
            when = when.replace(tzinfo=tz)
        return cls(
            id=str(raw["id"]),
            when=when,
            platform=platform,
            kind=kind,
            files=[str(f) for f in files],
            caption=str(raw.get("legenda") or "").strip(),
            brand_organic=raw.get("conteudo_comercial"),
            source=source,
        )


def load_agenda(folder: Path, tz: ZoneInfo) -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    for path in sorted(folder.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if isinstance(data, dict):
            data = data.get("posts") or []
        for raw in data:
            item = Item.parse(raw, tz, path.name)
            if item.id in seen:
                raise AgendaError(f"id repetido na agenda: {item.id}")
            seen.add(item.id)
            items.append(item)
    return sorted(items, key=lambda i: i.when)


@dataclass
class State:
    path: Path
    published: dict = field(default_factory=dict)
    failures: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "State":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            return cls(path, data.get("publicados", {}), data.get("falhas", {}))
        return cls(path)

    def save(self) -> None:
        self.path.write_text(
            json.dumps({"publicados": self.published, "falhas": self.failures}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class Publisher(Protocol):
    def __call__(self, item: Item) -> str: ...


def due_items(items: list[Item], state: State, now: datetime, late_window: timedelta) -> list[Item]:
    due = []
    for item in items:
        if item.id in state.published:
            continue
        if state.failures.get(item.id, {}).get("tentativas", 0) >= MAX_ATTEMPTS:
            continue
        if item.when <= now and now - item.when <= late_window:
            due.append(item)
    return due


def run(
    items: list[Item],
    state: State,
    publish: Publisher,
    now: datetime,
    late_window: timedelta,
    log: Callable[[str], None] = print,
    is_ready: Callable[[Item], bool] = lambda item: True,
) -> int:
    """Publish every due item. Returns the number of failures.

    Items whose media is not there yet (``is_ready`` false) are skipped without
    counting as a failure, so they go out as soon as the file is added.
    """
    failures = 0
    for item in due_items(items, state, now, late_window):
        label = f"[{item.platform}/{item.kind}] {item.id}"
        if not is_ready(item):
            log(f"AGUARDANDO ARQUIVO {label}: {', '.join(item.files)}")
            continue
        try:
            result = publish(item)
        except Exception as exc:  # keep going with the other posts
            failures += 1
            entry = state.failures.setdefault(item.id, {"tentativas": 0})
            entry["tentativas"] += 1
            entry["ultimo_erro"] = str(exc)[:500]
            entry["em"] = now.isoformat(timespec="minutes")
            log(f"ERRO {label}: {exc}")
        else:
            state.published[item.id] = {"em": now.isoformat(timespec="minutes"), "resultado": result}
            state.failures.pop(item.id, None)
            log(f"OK   {label} -> {result}")
        state.save()
    return failures
