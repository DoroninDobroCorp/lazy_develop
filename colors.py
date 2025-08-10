"""
Файл: colors.py

Адаптивная цветовая схема для консоли с поддержкой светлых и темных тем.

Как управлять темой:
- SLOTH_THEME=dark | light | mono (по умолчанию: auto→light)
- NO_COLOR (любое значение) — полностью отключает цвета

Палитры подобраны в мягком пастельном стиле с учетом читаемости на светлом и темном фоне.
"""

import os
import sys
import locale


def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


def _supports_truecolor() -> bool:
    """Определяет поддержку 24-битного цвета терминалом.

    Надежный индикатор — переменная COLORTERM=truecolor|24bit.
    На macOS некоторые терминалы не указывают это явно, поэтому
    допускаем ручной оверрайд через SLOTH_COLOR_DEPTH=24.
    """
    ct = (os.getenv("COLORTERM") or "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return True
    if (os.getenv("SLOTH_COLOR_DEPTH") or "").strip() == "24":
        return True
    return False


def _supports_256color() -> bool:
    """Проверяет поддержку 256-цветной палитры.

    Ориентируемся на TERM, а также допускаем ручной оверрайд SLOTH_COLOR_DEPTH=256.
    """
    if (os.getenv("SLOTH_COLOR_DEPTH") or "").strip() == "256":
        return True
    term = (os.getenv("TERM") or "").lower()
    return "256color" in term or "xterm" in term or "screen" in term


def _should_enable_ansi() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("TERM", "").lower() == "dumb":
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _resolve_theme() -> str:
    theme = (os.getenv("SLOTH_THEME") or "auto").strip().lower()
    if theme in ("dark", "light", "mono"):
        return theme
    # Авто-режим: без надежного способа определить фон — по умолчанию используем 'light'
    return "light"


class Colors:
    """ANSI-коды цветов, зависящие от темы и окружения."""

    _ENABLED = _should_enable_ansi()
    _THEME = _resolve_theme()
    _TRUECOLOR = _supports_truecolor()
    _ANSI256 = _supports_256color()

    # Пастельные, но контрастные палитры для 24-bit
    _PALETTE_DARK_24 = {
        "FAIL": _rgb(191, 97, 106),      # мягкий красный
        "OKGREEN": _rgb(163, 190, 140),  # мягкий зеленый
        "WARNING": _rgb(235, 203, 139),  # теплый желтый
        "OKBLUE": _rgb(94, 129, 172),    # холодный синий
        "HEADER": _rgb(180, 142, 173),   # пастельный пурпур
        "CYAN": _rgb(136, 192, 208),     # спокойный циан
        "GREY": _rgb(106, 114, 128),     # нейтральный серый
    }

    _PALETTE_LIGHT_24 = {
        # Больше контраста на светлом фоне — слегка затемненные, но сохраняем пастельный тон
        "FAIL": _rgb(170, 40, 55),       # более глубокий красный
        "OKGREEN": _rgb(88, 133, 96),    # более темный зелёный
        "WARNING": _rgb(152, 110, 0),    # янтарный/охра
        "OKBLUE": _rgb(36, 71, 120),     # темно-голубой
        "HEADER": _rgb(120, 70, 120),    # глубокий пурпур
        "CYAN": _rgb(20, 110, 130),      # темный циан
        "GREY": _rgb(80, 86, 98),        # насыщенный серый
    }

    # Пастельная 256-цветная палитра (приближения к 24-bit значениям)
    def _c256(n: int) -> str:
        return f"\033[38;5;{n}m"

    _PALETTE_DARK_256 = {
        "FAIL": _c256(174),     # мягкий красный
        "OKGREEN": _c256(114),  # мягкий зеленый
        "WARNING": _c256(180),  # теплый желтый
        "OKBLUE": _c256(110),   # холодный синий
        "HEADER": _c256(176),   # пастельный пурпур
        "CYAN": _c256(109),     # спокойный циан
        "GREY": _c256(246),     # нейтральный серый
    }

    _PALETTE_LIGHT_256 = {
        # Чуть более тёмные пастельные оттенки для светлого фона
        "FAIL": _c256(167),
        "OKGREEN": _c256(108),
        "WARNING": _c256(178),
        "OKBLUE": _c256(67),
        "HEADER": _c256(139),
        "CYAN": _c256(73),
        "GREY": _c256(238),  # тёмно-серый для читаемости
    }

    # Безопасная 8-цветная палитра (максимальная совместимость)
    # Важная деталь: на светлой теме делаем GREY = чёрный (30), чтобы не был слишком бледным
    _PALETTE_DARK_8 = {
        "FAIL": "\033[31m",     # red
        "OKGREEN": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "OKBLUE": "\033[34m",   # blue
        "HEADER": "\033[35m",  # magenta
        "CYAN": "\033[36m",    # cyan
        "GREY": "\033[90m",    # bright black (grey)
    }

    _PALETTE_LIGHT_8 = {
        "FAIL": "\033[31m",
        "OKGREEN": "\033[32m",
        "WARNING": "\033[33m",
        "OKBLUE": "\033[34m",
        "HEADER": "\033[35m",
        "CYAN": "\033[36m",
        "GREY": "\033[30m",    # обычный чёрный для лучшей читаемости на белом
    }

    if _ENABLED and _THEME != "mono":
        if _TRUECOLOR:
            _P = _PALETTE_LIGHT_24 if _THEME == "light" else _PALETTE_DARK_24
        elif _ANSI256:
            _P = _PALETTE_LIGHT_256 if _THEME == "light" else _PALETTE_DARK_256
        else:
            _P = _PALETTE_LIGHT_8 if _THEME == "light" else _PALETTE_DARK_8
        FAIL = _P["FAIL"]
        OKGREEN = _P["OKGREEN"]
        WARNING = _P["WARNING"]
        OKBLUE = _P["OKBLUE"]
        HEADER = _P["HEADER"]
        CYAN = _P["CYAN"]
        GREY = _P["GREY"]
        BOLD = "\033[1m"
        UNDERLINE = "\033[4m"
        ENDC = "\033[0m"
    else:
        # Моно режим или цвета отключены
        FAIL = ""
        OKGREEN = ""
        WARNING = ""
        OKBLUE = ""
        HEADER = ""
        CYAN = ""
        GREY = ""
        BOLD = "" if os.getenv("NO_COLOR") else "\033[1m"
        UNDERLINE = "" if os.getenv("NO_COLOR") else "\033[4m"
        ENDC = ""


def _supports_emoji() -> bool:
    """Эвристика поддержки эмодзи.

    - Можно принудительно выключить: SLOTH_EMOJI=0
    - Можно принудительно включить: SLOTH_EMOJI=1
    - По умолчанию: включаем только если кодировка stdout и locale — UTF-8.
    """
    env = os.getenv("SLOTH_EMOJI")
    if env == "0":
        return False
    if env == "1":
        return True
    encs = [getattr(sys.stdout, "encoding", ""), locale.getpreferredencoding(False)]
    return any(e and "utf" in e.lower() for e in encs)


class Symbols:
    """Набор символов с фолбэком на ASCII при отсутствии поддержки эмодзи."""

    _EMOJI = _supports_emoji()

    if _EMOJI:
        CHECK = "✅"
        CROSS = "❌"
        INFO = "ℹ️"
        GEAR = "⚙️"
        SAVE = "💾"
        BLUE_DOT = "🔵"
        ROCKET = "🚀"
        WARNING = "⚠️"
        FLAG = "🏁"
        SPINNER = "🔄"
    else:
        CHECK = "[OK]"
        CROSS = "[ERR]"
        INFO = "[i]"
        GEAR = "[cfg]"
        SAVE = "[save]"
        BLUE_DOT = "[·]"
        ROCKET = ">>"
        WARNING = "[!]"
        FLAG = "[end]"
        SPINNER = "[~]"

# test

