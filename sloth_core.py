# Файл: sloth_core.py
"""
Ядро интеграции с Gemini (Google AI / Vertex AI) для Sloth.

Что изменил по сравнению с твоей версией:
- БОЛЬШЕ НЕ ЗАДАЁТСЯ max_output_tokens → отдаём модели право писать максимум.
- Добавлен thinking budget (бюджет на размышления), если доступен:
  * При наличии нового SDK google-genai: через GenerateContentConfig(thinking_config=ThinkingConfig(...))
  * В Vertex AI: через GenerationConfig(thinking_config=ThinkingConfig(...))
  * В старом google.generativeai thinking недоступен — печатаю предупредительный лог.
- Ответ собираю надёжно (response.text, либо parts), usage считываю бережно с запасными ветками.

Примечание:
- Значение бюджетa размышлений по умолчанию взял 24576 токенов, т.к. это безопасный высокий предел,
  совместимый с 2.5-серией в большинстве конфигураций. Можно переопределить env SLOTH_THINKING_BUDGET.
"""

import os
from typing import Any, Dict
from colors import Colors
import config as sloth_config

# --- Попытка использовать новый Google GenAI SDK (предпочтительно) ---
HAS_GOOGLE_GENAI = False
try:
    from google import genai as genai_new
    from google.genai.types import GenerateContentConfig, ThinkingConfig
    HAS_GOOGLE_GENAI = True
except Exception:
    genai_new = None
    GenerateContentConfig = None
    ThinkingConfig = None
    HAS_GOOGLE_GENAI = False

# --- Старый SDK (fallback, без thinking budget) ---
HAS_LEGACY_GENAI = False
try:
    import google.generativeai as genai_legacy
    HAS_LEGACY_GENAI = True
except Exception:
    genai_legacy = None
    HAS_LEGACY_GENAI = False

# --- Vertex AI SDK ---
import vertexai
from vertexai.generative_models import GenerativeModel, HarmCategory, HarmBlockThreshold
# Эти импорты могут отсутствовать в старых версиях пакета; обрабатываем мягко
try:
    from vertexai.generative_models import GenerationConfig as VertexGenerationConfig  # тип конфигурации
except Exception:
    VertexGenerationConfig = None
try:
    from vertexai.generative_models import ThinkingConfig as VertexThinkingConfig     # thinking конфиг
except Exception:
    VertexThinkingConfig = None

# --- НАСТРОЙКИ ЯДРА ---
def _pick_cfg(path: str, env_name: str, default: Any) -> Any:
    v = sloth_config.get(path, None)
    if v is not None and v != "":
        return v
    ev = os.getenv(env_name)
    if ev is not None and ev != "":
        return ev
    return default

# ВАЖНО: ключ и проект ТОЛЬКО из конфигурации (без ENV/дефолтов)
GOOGLE_API_KEY = sloth_config.get("google.api_key", None)
GOOGLE_CLOUD_PROJECT = sloth_config.get("google.cloud_project", None)
GOOGLE_CLOUD_LOCATION = _pick_cfg("google.cloud_location", "GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = _pick_cfg("model.name", "SLOTH_MODEL_NAME", "gemini-2.5-pro")
CONTEXT_PREP_MODEL_NAME = _pick_cfg("model.context_prep_name", "SLOTH_CONTEXT_PREP_MODEL", "gemini-2.5-flash")
API_TIMEOUT_SECONDS = int(_pick_cfg("api.timeout_seconds", "SLOTH_API_TIMEOUT", "600"))

# ВАЖНО: максимальный бюджет размышлений.
THINKING_BUDGET_TOKENS = int(_pick_cfg("thinking.budget_tokens", "SLOTH_THINKING_BUDGET", "24576"))

# Команды-исключения для bash
ALLOWED_COMMANDS = (
    "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./",
    # Расширение для миграций и современных менеджеров
    "prisma", "bunx", "bun"
)

def _normalize_pricing(pricing: Dict[str, Any]) -> Dict[str, Any]:
    def to_num(x: Any) -> Any:
        if isinstance(x, str) and x.lower() == "inf":
            return float('inf')
        return x
    out: Dict[str, Any] = {}
    for model, mp in (pricing or {}).items():
        m_out: Dict[str, Any] = {}
        for io_key in ("input", "output"):
            tiers = ((mp or {}).get(io_key, {}) or {}).get("tiers", [])
            norm_tiers = []
            for tier in tiers:
                if not isinstance(tier, dict):
                    continue
                up_to = to_num(tier.get("up_to"))
                price = float(tier.get("price")) if tier.get("price") is not None else None
                norm_tiers.append({"up_to": up_to, "price": price})
            m_out[io_key] = {"tiers": norm_tiers}
        out[model] = m_out
    return out

_DEFAULT_MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input": {"tiers": [{"up_to": 200000, "price": 1.25}, {"up_to": float('inf'), "price": 2.50}]},
        "output": {"tiers": [{"up_to": 200000, "price": 10.00}, {"up_to": float('inf'), "price": 15.00}]}
    },
    "gemini-2.5-flash": {
        # Public references (May 2025): ~$0.15 / 1M input, ~$0.60 / 1M output (reasoning off)
        "input": {"tiers": [{"up_to": float('inf'), "price": 0.15}]},
        "output": {"tiers": [{"up_to": float('inf'), "price": 0.60}]}
    },
    "gemini-2.5-flash-lite": {
        # Public references (May 2025): ~$0.10 / 1M input, ~$0.40 / 1M output
        "input": {"tiers": [{"up_to": float('inf'), "price": 0.10}]},
        "output": {"tiers": [{"up_to": float('inf'), "price": 0.40}]}
    },
    "gemini-1.5-pro-latest": {
        "input": {"tiers": [{"up_to": float('inf'), "price": 3.50}]},
        "output": {"tiers": [{"up_to": float('inf'), "price": 10.50}]}
    }
}

MODEL_PRICING = _normalize_pricing(sloth_config.get("model_pricing", _DEFAULT_MODEL_PRICING) or _DEFAULT_MODEL_PRICING)

# --- Глобальные переменные состояния API ---
model = None  # в режиме google-genai здесь будет client, в остальных — объект модели
ACTIVE_API_SERVICE = "N/A"
GOOGLE_AI_HAS_FAILED_THIS_SESSION = False
_last_request_log_key = None  # защита от дублирования логов запроса в рамках одной итерации

# Базовая генерационная конфигурация — БЕЗ max_output_tokens!
GENERATION_TEMPERATURE = float(_pick_cfg("generation.temperature", "SLOTH_TEMPERATURE", "1"))
GENERATION_TOP_P = float(_pick_cfg("generation.top_p", "SLOTH_TOP_P", "1"))
GENERATION_TOP_K = int(float(_pick_cfg("generation.top_k", "SLOTH_TOP_K", "1")))

def _log_generation_params():
    print(
        f"{Colors.CYAN}🔧 ЛОГ: Параметры генерации:"
        f" temperature={GENERATION_TEMPERATURE}, top_p={GENERATION_TOP_P}, top_k={GENERATION_TOP_K}."
        f" max_output_tokens НЕ задан намеренно.{Colors.ENDC}"
    )
    print(
        f"{Colors.CYAN}🧩 ЛОГ: Бюджет размышлений (thinking_budget) = {THINKING_BUDGET_TOKENS} токенов, если поддерживается SDK/модель.{Colors.ENDC}"
    )

def initialize_model():
    """Инициализирует модель и выбирает доступный сервис с приоритетом:
    1) Google GenAI SDK (api key) → thinking_config доступен
    2) Старый google.generativeai (api key) → thinking_config недоступен
    3) Vertex AI SDK (ADC/Service Account) → thinking_config доступен
    """
    global model, ACTIVE_API_SERVICE, GOOGLE_AI_HAS_FAILED_THIS_SESSION

    print(f"{Colors.CYAN}⚙️  ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}{Colors.ENDC}")
    _log_generation_params()

    # --- Приоритет: новый Google GenAI SDK (api key) ---
    if GOOGLE_API_KEY and HAS_GOOGLE_GENAI and not GOOGLE_AI_HAS_FAILED_THIS_SESSION:
        print(f"{Colors.CYAN}🔑 ЛОГ: Пробую Google GenAI SDK (по API-ключу).{Colors.ENDC}")
        try:
            model = genai_new.Client(api_key=GOOGLE_API_KEY)
            # Тестовый короткий вызов (не задаём max_output_tokens)
            _ = model.models.generate_content(
                model=MODEL_NAME,
                contents="ping"
            )
            ACTIVE_API_SERVICE = "Google GenAI SDK"
            print(f"{Colors.OKGREEN}✅ ЛОГ: Успешно инициализировано через {ACTIVE_API_SERVICE}.{Colors.ENDC}")
            return
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Сбой инициализации GenAI SDK: {e}{Colors.ENDC}")
            GOOGLE_AI_HAS_FAILED_THIS_SESSION = True
            model = None

    # --- Fallback: старый google.generativeai (api key) ---
    if GOOGLE_API_KEY and HAS_LEGACY_GENAI and not model:
        print(f"{Colors.CYAN}🔑 ЛОГ: Пробую старый google.generativeai (API Key).{Colors.ENDC}")
        try:
            genai_legacy.configure(api_key=GOOGLE_API_KEY)
            # ВАЖНО: generation_config без max_output_tokens
            generation_config = {
                "temperature": GENERATION_TEMPERATURE,
                "top_p": GENERATION_TOP_P,
                "top_k": GENERATION_TOP_K,
            }
            model = genai_legacy.GenerativeModel(
                model_name=MODEL_NAME,
                generation_config=generation_config,
                safety_settings={
                    'HARM_CATEGORY_HARASSMENT': 'block_medium_and_above',
                    'HARM_CATEGORY_HATE_SPEECH': 'block_medium_and_above',
                    'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'block_medium_and_above',
                    'HARM_CATEGORY_DANGEROUS_CONTENT': 'block_none',
                }
            )
            # Пробный вызов
            model.generate_content("test", request_options={"timeout": 60})
            ACTIVE_API_SERVICE = "Google AI (Legacy SDK)"
            print(f"{Colors.OKGREEN}✅ ЛОГ: Инициализация через {ACTIVE_API_SERVICE} успешна.{Colors.ENDC}")
            print(f"{Colors.WARNING}ℹ️  ЛОГ: В этом режиме thinking_budget недоступен. Рекомендую установить 'google-genai'.{Colors.ENDC}")
            return
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось инициализировать старый SDK: {e}{Colors.ENDC}")
            model = None

    # --- Резерв: Vertex AI (ADC/Service Account) ---
    print(f"{Colors.CYAN}🔩 ЛОГ: Пытаюсь инициализировать через Vertex AI SDK...{Colors.ENDC}")
    try:
        vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)

        # Собираем конфиг без max_output_tokens
        vertex_gen_conf = {
            "temperature": GENERATION_TEMPERATURE,
            "top_p": GENERATION_TOP_P,
            "top_k": GENERATION_TOP_K,
        }

        # Добавим thinking_config, если класс доступен в установленной версии SDK
        if VertexThinkingConfig is not None:
            try:
                vertex_gen_conf = VertexGenerationConfig(
                    temperature=GENERATION_TEMPERATURE,
                    top_p=GENERATION_TOP_P,
                    top_k=GENERATION_TOP_K,
                    thinking_config=VertexThinkingConfig(thinking_budget=THINKING_BUDGET_TOKENS),
                )
            except Exception:
                # Если типизированный конфиг недоступен, передадим словарь (некоторые версии принимают dict)
                vertex_gen_conf = {
                    "temperature": GENERATION_TEMPERATURE,
                    "top_p": GENERATION_TOP_P,
                    "top_k": GENERATION_TOP_K,
                    "thinking_config": {"thinking_budget": THINKING_BUDGET_TOKENS},
                }

        model = GenerativeModel(
            model_name=MODEL_NAME,
            generation_config=vertex_gen_conf,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        ACTIVE_API_SERVICE = "Vertex AI"
        # Пробный вызов
        _ = model.generate_content("ping")
        print(f"{Colors.OKGREEN}✅ ЛОГ: Vertex AI SDK успешно инициализирован.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель: {e}{Colors.ENDC}")
        model = None
        ACTIVE_API_SERVICE = "N/A"

def get_active_service_details():
    """Возвращает текущую модель/клиент и имя активного сервиса."""
    return model, ACTIVE_API_SERVICE

def _extract_text_and_usage_from_genai_response(resp):
    # Пытаемся взять текст максимально надёжно
    full_text = getattr(resp, "text", None)
    if not full_text:
        try:
            # google-genai иногда возвращает candidates
            cands = getattr(resp, "candidates", None) or []
            parts_text = []
            for c in cands:
                try:
                    ct = getattr(c, "content", None)
                    if ct and getattr(ct, "parts", None):
                        for p in ct.parts:
                            t = getattr(p, "text", None)
                            if t:
                                parts_text.append(t)
                except Exception:
                    pass
            full_text = "".join(parts_text) if parts_text else ""
        except Exception:
            full_text = ""

    # usage
    prompt_tokens = 0
    output_tokens = 0
    try:
        um = getattr(resp, "usage_metadata", None)
        if um:
            prompt_tokens = getattr(um, "prompt_token_count", getattr(um, "input_tokens", 0)) or 0
            output_tokens = getattr(um, "candidates_token_count", getattr(um, "output_tokens", 0)) or 0
    except Exception:
        pass
    return full_text, prompt_tokens, output_tokens

def send_request_to_model(model_instance, active_service, prompt_text, iteration_count=0, model_name_override=None):
    """Возвращает словарь с текстом ответа и информацией о токенах."""
    global GOOGLE_AI_HAS_FAILED_THIS_SESSION, _last_request_log_key

    try:
        log_header = f"[Итерация {iteration_count}]" if iteration_count > 0 else "[Этап планирования]"
        # Анти-дубль: печатаем только если ключ логов поменялся
        log_key = (iteration_count, active_service)
        if _last_request_log_key != log_key:
            print(f"{Colors.CYAN}🧠 ЛОГ: {log_header} Готовлю запрос в модель ({active_service}).{Colors.ENDC}")
            print(f"{Colors.CYAN}⏳ ЛОГ: Отправляю запрос... (таймаут: {API_TIMEOUT_SECONDS} сек){Colors.ENDC}")
            _last_request_log_key = log_key

        # Выбор модели: либо override, либо основной MODEL_NAME
        _model_to_use = model_name_override or MODEL_NAME

        if active_service == "Google GenAI SDK":
            # Новый клиент + thinking_config
            cfg = GenerateContentConfig(
                temperature=GENERATION_TEMPERATURE,
                top_p=GENERATION_TOP_P,
                top_k=GENERATION_TOP_K,
                # критично: не задаём max_output_tokens
                thinking_config=ThinkingConfig(thinking_budget=THINKING_BUDGET_TOKENS),
            )
            print(f"  model={_model_to_use}")
            print(f"  top_k={GENERATION_TOP_K}")
            print(f"  thinking_budget={THINKING_BUDGET_TOKENS}")
            response = model_instance.models.generate_content(
                model=_model_to_use,
                contents=prompt_text,
                config=cfg,
            )
            text, in_tok, out_tok = _extract_text_and_usage_from_genai_response(response)

        elif active_service == "Google AI (Legacy SDK)":
            # Старый generativeai; thinking тут недоступен, max_output_tokens не задаем
            request_options = {"timeout": API_TIMEOUT_SECONDS}
            response = model_instance.generate_content(prompt_text, request_options={"timeout": API_TIMEOUT_SECONDS})
            # Склейка ответа
            text = getattr(response, "text", None)
            if not text:
                try:
                    text = "".join(part.text for part in response.parts)
                except Exception:
                    text = str(response)
            # usage
            in_tok = 0
            out_tok = 0
            try:
                um = response.usage_metadata
                in_tok = getattr(um, "prompt_token_count", 0) or 0
                out_tok = getattr(um, "candidates_token_count", 0) or 0
            except Exception:
                pass

        elif active_service == "Vertex AI":
            response = model_instance.generate_content(prompt_text)
            text = getattr(response, "text", None)
            if not text:
                try:
                    text = "".join(part.text for part in response.parts)
                except Exception:
                    text = str(response)
            in_tok = 0
            out_tok = 0
            try:
                um = response.usage_metadata
                in_tok = getattr(um, "prompt_token_count", 0) or 0
                out_tok = getattr(um, "candidates_token_count", 0) or 0
            except Exception:
                pass

        else:
            raise ValueError(f"Неизвестный сервис API: {active_service}")

        if not text:
            raise ValueError("Ответ от модели пустой.")

        print(f"{Colors.OKGREEN}✅ ЛОГ: Ответ от модели получен успешно.{Colors.ENDC}")
        return {"text": text, "input_tokens": in_tok, "output_tokens": out_tok}

    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА при запросе к API ({active_service}): {e}{Colors.ENDC}")
        # Автопереключение: при сбое GenAI SDK пробуем Vertex
        if active_service == "Google GenAI SDK":
            print(f"{Colors.CYAN}🔄 ЛОГ: Переключаюсь на Vertex AI как резерв...{Colors.ENDC}")
            GOOGLE_AI_HAS_FAILED_THIS_SESSION = True
            initialize_model()
        return None

def get_clarification_and_planning_prompt(context, task, boundary=None):
    """
    Генерирует промпт для этапа планирования.
    """
    boundary_instr = ""
    if boundary:
        boundary_instr = f"""
**Формат write_file с BOUNDARY (обязателен):**
```write_file path="path/to/file" boundary="{boundary}"
<любой контент файла, в т.ч. с внутренними ```
 и ```bash блоками>
{boundary}

Последняя строка ПЕРЕД закрывающим ``` — ровно {boundary}.
"""

    global_rules = fr"""
**ГЛОБАЛЬНЫЕ ПРАВИЛА (ОБЯЗАТЕЛЬНЫ К ИСПОЛНЕНИЮ):**

1.  **ПРАВИЛО ОБЩЕНИЯ: ТЕКСТ ВНЕ БЛОКОВ НЕВИДИМ!**
    *   Мой парсер видит **только** содержимое блоков, начинающихся с ````.
    *   Любой текст, который ты пишешь вне этих блоков (объяснения, приветствия, комментарии), **будет полностью проигнорирован и утерян**. Его никто не увидит.
    *   Если ты хочешь что-то сказать пользователю или мне, используй **специальные блоки**:
        *   Для уточнений: ````clarification ... ````
        *   Для ручных шагов: ````manual ... ````
        *   Для описания своих действий: ````summary ... ```` или ````done_summary ... ````

2.  **ПРАВИЛО ПУТЕЙ (САМОЕ ВАЖНОЕ!):**
    *   Все пути к файлам, которые ты используешь (в блоках `files`, `write_file`, `bash`), ДОЛЖНЫ быть **относительными от корня проекта**.
    *   **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** начинать путь с имени корневой папки проекта. Система автоматически работает из корня проекта.
    *   **Пример:** Если проект находится в папке `/path/to/my-project`, и тебе нужен файл `src/app.js`:
        *   **ПРАВИЛЬНО:** `src/app.js`
        *   **НЕПРАВИЛЬНО:** `my-project/src/app.js`
    *   Запрещено: абсолютные пути (`/...`), `~`, последовательности `..`, обратные слэши \, пробелы в пути, подстановки/переменные.
    *   Путь не должен начинаться с имени корневой папки проекта.
    *   Разрешённые символы в пути: латиница/цифры/`_`/`-`/`.` и разделитель `/`.

3.  **Рабочая Директория:** Все команды выполняются из корня проекта. Разрешён безопасный паттерн `cd <подпапка> && <разрешённая команда>`. **Запрещён** одиночный `cd` или цепочки `cd` без немедленного запуска разрешённой команды.

4.  **Разрешенные Команды:** `{', '.join(ALLOWED_COMMANDS)}`. Также разрешён вариант с префиксом `cd <подпапка> &&` перед этими командами. Команды, не входящие в список, должны быть помещены в блок ```manual```.

5.  **Фокус и Прагматизм:** Твоя главная цель — решить **исходную задачу** пользователя. Не занимайся перфекционизмом: не исправляй стиль кода и не делай рефакторинг, не связанный с задачей.

6.  **ПРАВИЛО ЛОГИРОВАНИЯ (КРИТИЧЕСКИ ВАЖНО):**
     *   Ты можешь и должен добавлять логи (`print`, `console.log` и т.п.) для отладки.
     *   **ЗАПРЕЩЕНО** добавлять ЛЮБОЙ отладочный вывод без точного префикса `[SLOTHLOG]`. Каждый новый лог, который ты пишешь, **ОБЯЗАН** начинаться с `[SLOTHLOG]`.
     *   **Пример ПРАВИЛЬНО:** `print(f"[SLOTHLOG] Variable foo: {{foo}}")`
     *   **Пример НЕПРАВИЛЬНО:** `print(f"Variable foo: {{foo}}")`
     *   Это правило абсолютно, исключений нет.

7.  **СЛУЖЕБНЫЕ МАРКЕРЫ И МЕТА‑ТЕКСТ:**
     *   Маркер границы `{boundary or 'SLOTH_BOUNDARY_*'}` используется ТОЛЬКО для парсинга.
     *   Никогда не вставляй строки с `SLOTH_BOUNDARY` в содержимое файлов или команды `bash`.
     *   Любое попадание `SLOTH_BOUNDARY` в итоговый код или команды — это ошибка, которую нужно немедленно исправить.
     *   Не вставляй в код мета‑комментарии наподобие: “I'll remove the stray ...”/“remove boundary ...”. Пиши только конечное содержимое, без пояснений.
"""

    planning_rules = f"""
Ты — AI-планировщик. Первая задача — убедиться, что исходная задача понятна.

**ПРАВИЛА ПЛАНИРОВАНИЯ:**

1.  Анализируй задачу и **сокращённый** контекст проекта.
2.  Два пути вывода:
    *   Если задача непонятна — верни только блок ```clarification ... ```.
    *   Если задача понятна — верни только блок ```plan ... ```.
3.  В блоке `plan` обязателен поитерационный план (Итерация 1..N):
    *   Для каждой итерации укажи: цель шага, ключевые файлы, оценку объёма («~до 500–600 строк» или «1 крупный файл path»), зависимости, нужна ли проверка (`verify_run`).
    *   Все изменения в одном файле выполняй за одну итерацию полностью — не дроби один файл на несколько итераций.
    *   План должен явно завершаться `verify_run` при завершении всей работы (если команда запуска есть). Если verify-команда отсутствует — итог: `done_summary` без запуска.
4.  На этапе планирования запрещено генерировать ```bash``` или `write_file`.

5.  ОГРАНИЧЕНИЕ ВЫВОДА: держи ответ максимально кратким.
    *   Для clarification — до 5 пунктов, суммарно до ~300 слов.
    *   Для plan — не более 12 пунктов, суммарно до ~500 слов.
    *   Не добавляй ничего вне требуемого блока.

Пример формата плана (шаблон):
```
```plan
Итерация 1/N
- Цель: кратко описать цель шага
- Файлы: path/a, path/b
- Объём: ~до 500–600 строк ИЛИ 1 крупный файл path
- Зависимости: при наличии
- Проверка: verify_run (если команда запуска настроена)
- DoD: критерии готовности шага

Итерация 2/N
- Цель: ...
...

Итерация N/N
- Цель: финализация
- Проверка: финальный verify_run; при успехе done_summary + ГОТОВО
```
```
"""

    return f"""{planning_rules}
{global_rules}
{boundary_instr}

--- КОНТЕКСТ ПРОЕКТА (СОКРАЩЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

--- ЗАДАЧА ПОЛЬЗОВАТЕЛЯ ---
{task}
--- КОНЕЦ ЗАДАЧИ ---

Проанализируй задачу и контекст. Следуй правилам этапа планирования.
"""

def _get_execution_prompt_rules(boundary=None):
    """Возвращает общий набор правил для всех этапов исполнения."""
    b = f"\n\n{boundary}" if boundary else ""
    return f"""
Ты работаешь как строгий исполнитель изменений кода. Форматируй ответ ТОЛЬКО блоками ниже. Не возвращай ничего лишнего.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА И ОГРАНИЧЕНИЯ:
*   Разрешены ТОЛЬКО такие блоки:
    - ```write_file path=\"RELATIVE/PATH\"{b}\n...содержимое файла...\n```
    - ```bash\n...команды...\n```
    - ```verify_run```
    - ```summary```
    - ```done_summary```
    - ```manual```
*   Любой текст вне перечисленных блоков будет проигнорирован.
*   НЕЛЬЗЯ использовать произвольные скрипты/команды вне белого списка.
*   Если действие невозможно выполнить автоматически — верни блок `manual` с чёткими шагами для человека.

АНТИ-ПЕРФЕКЦИОНИЗМ И ИЗБЕЖАНИЕ ЗАЦИКЛИВАНИЯ:
*   Если ты уже правил тот же файл в последней(их) итерации(ях) и нет новых ошибок/логов — НЕ делай микро‑правок. Либо консолидируй полноценный патч сразу, либо возвращай `done_summary` и `ГОТОВО`.
*   Если решаешься изменить файл, сделай это ВНИМАТЕЛЬНО и ВСЕСТОРОННЕ в один проход: учти импорты, вызовы, связанные участки, тесты, конфиги. Не дроби изменение одного файла на несколько итераций.
*   Не выполняй косметические правки без функциональной ценности.
*   Если по логам запуск прошёл без явных ошибок — это успех. Возвращай `done_summary` и `ГОТОВО`.
*   Если считаешь, что это последние правки перед проверкой — ОБЯЗАТЕЛЬНО верни блок `verify_run` в этом же ответе.

ЕСЛИ В ПРОЕКТЕ НЕТ КОМАНДЫ ЗАПУСКА (verify):
*   Не отправляй `verify_run`.
*   Если считаешь, что цель достигнута — верни `done_summary` и слово `ГОТОВО` сразу после правок.
*   Если не уверен — сократи объём правок и распланируй оставшееся на следующие итерации, но без попыток запуска.

ОГРАНИЧЕНИЕ ОБЪЁМА ИЗМЕНЕНИЙ ЗА ИТЕРАЦИЮ (важно для стабильности):
*   В одной итерации присылай суммарно примерно до 500–600 строк изменений.
*   Если нужен большой рефакторинг — присылай один крупный файл за итерацию (даже если он >600 строк). В этой итерации менять следует ТОЛЬКО этот файл; остальные файлы распланируй на следующие итерации.
*   Если правок больше — распиши батчи по итерациям и веди краткий учёт в `summary` (напр.: «Шаг 1/3: обновил контракт. Дальше: роуты, затем фронт.»).
*   Приоритет: критичные/блокирующие изменения — первыми.

ОПРЕДЕЛЕНИЕ ГОТОВНОСТИ (Definition of Done):
*   Считай задачу успешно выполненной и возвращай `done_summary` + слово `ГОТОВО`, если выполнены ВСЕ условия ниже (адаптируй под тип проекта):
    - 1) Verify-команда (или тест/скрипт) отработала без явных ошибок компиляции/рантайма в логах.
    - 2) Для веб/API: ключевой эндпоинт или health-страница отвечает (даже если процесс dev-сервера прерван по таймауту — это не ошибка).
    - 3) Для не‑веб (CLI/библиотеки): короткий smoke‑запуск (`--version`, быстрый тест) завершился без ошибок.
    - 4) Нет нерешённых ошибок в логах запуска.

ПОРЯДОК ВНЕСЕНИЯ ИЗМЕНЕНИЙ (чтобы быстрее прийти к ГОТОВО):
1) Сначала приведи в соответствие контракт и типы: схемы БД/Prisma/DTO/TS‑типы/интерфейсы.
2) Затем обнови серверные контроллеры/роуты/бизнес‑логику под новый контракт.
3) И только потом обновляй фронтенд/клиентов (RTK Query/React/Django templates и т.п.).
4) После успешного verify и отсутствия ошибок — сразу `done_summary`.

ФОРМАТ БЛОКОВ:
*   write_file — перезаписывает файл полностью. Пиши конечное содержимое (без диффов). Если файл отсутствует — он будет создан.
*   bash — набор команд из белого списка, по одной на строке.
*   verify_run — маркер, что после твоих действий следует запустить проверку.

**КАК АНАЛИЗИРОВАТЬ ЛОГИ ЗАПУСКА:**
*   **Ищи явные ошибки:** `Traceback`, `Error`, `SyntaxError`, `failed`, `Cannot find module` и т.п. Если они есть — это провал, нужно исправлять.
*   **Оценивай таймаут ПРАВИЛЬНО:** Если процесс завершился по таймауту (например, `exit code -9` или `124`), но в `STDOUT` или `STDERR` нет явных ошибок компиляции/запуска, **ЭТО СЧИТАЕТСЯ УСПЕХОМ**. Это означает, что процесс (например, dev-сервер) успешно запустился и работал, пока его не прервали. В этом случае, если нет других ошибок, пиши `ГОТОВО`.
*   **Успешный запуск без ошибок:** Если процесс завершился с кодом `0` и в логах нет ошибок, это тоже успех.
"""

def get_initial_prompt(context, task, fix_history=None, boundary=None):
    rules = _get_execution_prompt_rules(boundary)
    history_prompt_section = ""
    if fix_history:
        history_prompt_section = f"""
--- ИСТОРИЯ ПРЕДЫДУЩЕГО РЕШЕНИЯ, КОТОРОЕ ОКАЗАЛОСЬ НЕВЕРНЫМ ---
{fix_history}
--- КОНЕЦ ИСТОРИИ ---
Проанализируй свою прошлую ошибку и начни заново.
"""
    return f"""{rules}
{history_prompt_section}
--- КОНТЕКСТ ПРОЕКТА (ПОЛНЫЙ ИЛИ ЧАСТИЧНЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
Задача: {task}
Проанализируй задачу и предоставь ответ, строго следуя правилам исполнения.
"""

def get_review_prompt(context, goal, iteration_count, attempt_history, boundary=None):
    return f"""{_get_execution_prompt_rules(boundary)}

**ЦЕЛЬ:** Проведи осмотр кода и выполни необходимую доработку минимально достаточным количеством действий. Избегай перфекционизма.

Если цель уже достигнута — верни `done_summary` и `ГОТОВО`.

Если нужна доработка — верни консолидированный набор правок:
*   Один или несколько `write_file` с полноценными изменениями (без микрошагов).
*   По необходимости один `bash`.
*   Обязательно добавь `verify_run` для проверки.

Для само‑контроля добавь вспомогательный блок со списком файлов, которые ты намерен менять на ЭТОЙ итерации (для тебя, он не исполняется):
```files_to_change
path/to/file1
path/to/file2
```
Если список файлов совпадает с предыдущими итерациями и нет новых ошибок — остановись и верни `done_summary`.

--- ПАМЯТКА ПРО ИСТОРИЮ ---
Используй краткую историю предыдущих попыток, чтобы избежать повторов и микро‑изменений:
{attempt_history}

{context}
--- КОНЕЦ КОНТЕКСТА ---

Напоминаю ИСХОДНУЮ ЦЕЛЬ: {goal}
"""

def get_error_fixing_prompt(failed_command, error_message, goal, context, iteration_count, attempt_history, boundary=None):
    rules = _get_execution_prompt_rules(boundary)
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"\n**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):** Произошла ошибка — подумай шире и исправь её надёжно.\n"
    history_info = ""
    if attempt_history:
        history_info = (
            "--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК ---\n" +
            "\n---\n".join(attempt_history) +
            "\n--- КОНЕЦ ИСТОРИИ ---\n"
        )
    return f"""{rules}
{iteration_info}
{history_info}
**ВАЖНО:** Исправь ошибку. Не пиши `ГОТОВО`.

--- ДАННЫЕ ОБ ОШИБКЕ ---
КОМАНДА: {failed_command}
СООБЩЕНИЕ (stderr): {error_message}
--- КОНЕЦ ДАННЫХ ОБ ОШИБКЕ ---

Исходная ЦЕЛЬ была: {goal}

Дай исправленный блок команд и `summary`.

--- КОНТЕКСТ, ГДЕ ПРОИЗОШЛА ОШИБКА ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
"""

def get_log_analysis_prompt(context, goal, history, logs, boundary=None):
    rules = _get_execution_prompt_rules(boundary)
    history_info = ""
    if history:
        history_info = (
            "--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК ---\n" +
            str(history) +
            "\n--- КОНЕЦ ИСТОРИИ ---\n"
        )
    return f"""{rules}

Ты находишься в режиме АНАЛИЗА ЛОГОВ (эту стадию выполняет быстрая модель). Программа запускалась примерно 10 секунд и затем целенаправленно останавливалась. Провалом считаются только:
* явные ошибки (Traceback/Error/SyntaxError/failed/Cannot find module и т.п.),
* или логи, которые свидетельствуют о несоответствии поставленной цели.

В ЭТОЙ СТАДИИ ЗАПРЕЩЕНО вносить изменения в код. Доступны только два исхода:
1) Если цель достигнута — верни блок `done_summary` и напиши слово `ГОТОВО`.
2) Если нет — верни лаконичный `summary` с диагнозом (что не так в логах) и ЧТО должна сделать старшая модель в следующей итерации. Никаких `write_file`/`bash`/`verify_run` здесь не возвращай.

{history_info}
--- ЛОГИ ЗАПУСКА ---
{logs}
--- КОНЕЦ ЛОГОВ ---

--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЁННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

Исходная ЦЕЛЬ: {goal}
"""

def get_context_prep_prompt(context_chunk: str, goal: str, boundary: str | None = None) -> str:
    """
    Генерирует промпт для стадии "Подготовка контекста". Задача модели: НЕ решать цель,
    а ЖАДНО собрать список файлов, которые могут понадобиться для решения или быть изменены.

    Ожидаемый вывод:
    ```files
    path/to/file1
    path/to/file2
    ...
    ```
    Никаких других блоков, по возможности без лишнего текста.
    """
    rules = (
        "Ты выполняешь только стадию подготовки контекста. НЕ решай задачу. "
        "Твоя цель — жадно выбрать все потенциально релевантные файлы. "
        "Если сомневаешься — включай файл. Дальнейшая работа будет на другой модели."
    )
    return f"""{rules}

Исходная ЦЕЛЬ:
{goal}

--- КУСОК КОНТЕКСТА (файлы и содержимое) ---
{context_chunk}
--- КОНЕЦ КОНТЕКСТА ---

Выведи только список путей в блоке ```files```. Пути должны быть относительными к корню проекта.
"""

planning_rules = f"""
Ты — AI-планировщик. Первая задача — убедиться, что исходная задача понятна.

**ПРАВИЛА ПЛАНИРОВАНИЯ:**

1. Анализируй задачу и сокращённый контекст проекта.
2. Два пути:
        *   Для описания своих действий: ````summary ... ```` или ````done_summary ... ````

2.  **ПРАВИЛО ПУТЕЙ (САМОЕ ВАЖНОЕ!):**
    *   Все пути к файлам, которые ты используешь (в блоках `files`, `write_file`, `bash`), ДОЛЖНЫ быть **относительными от корня проекта**.
    *   **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** начинать путь с имени корневой папки проекта. Система автоматически работает из корня проекта.
    *   **Пример:** Если проект находится в папке `/path/to/my-project`, и тебе нужен файл `src/app.js`:
        *   **ПРАВИЛЬНО:** `src/app.js`
        *   **НЕПРАВИЛЬНО:** `my-project/src/app.js`
    *   Для блока `write_file` путь обязан указываться строго в атрибуте: `path="relative/path/to/file"`.
    *   Запрещено: абсолютные пути (`/...`), `~`, последовательности `..`, обратные слэши \, пробелы в пути, подстановки/переменные.
    *   Путь не должен начинаться с имени корневой папки проекта.
    *   Разрешённые символы в пути: латиница/цифры/`_`/`-`/`.` и разделитель `/`.

3.  **Рабочая Директория:** Все команды выполняются из **корня проекта**. **ЗАПРЕЩЕНО** использовать `cd`.

4.  **Разрешенные Команды:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

5.  **Фокус и Прагматизм:** Твоя главная цель — решить **исходную задачу** пользователя. Не занимайся перфекционизмом: не исправляй стиль кода и не делай рефакторинг, не связанный с задачей.

6.  **ПРАВИЛО ЛОГИРОВАНИЯ (КРИТИЧЕСКИ ВАЖНО):**
     *   Ты можешь и должен добавлять логи (`print`, `console.log` и т.п.) для отладки.
     *   **ЗАПРЕЩЕНО** добавлять ЛЮБОЙ отладочный вывод без точного префикса `[SLOTHLOG]`. Каждый новый лог, который ты пишешь, **ОБЯЗАН** начинаться с `[SLOTHLOG]`.
     *   **Пример ПРАВИЛЬНО:** `print(f"[SLOTHLOG] Variable foo: {{foo}}")`
     *   **Пример НЕПРАВИЛЬНО:** `print(f"Variable foo: {{foo}}")`
     *   Это правило абсолютно, исключений нет.
"""

def get_initial_planning_prompt(context, task, boundary=None):
    return f"""{planning_rules}
{global_rules}

--- КОНТЕКСТ ПРОЕКТА (СОКРАЩЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

--- ЗАДАЧА ПОЛЬЗОВАТЕЛЯ ---
{task}
--- КОНЕЦ ЗАДАЧИ ---

Проанализируй задачу и контекст. Следуй правилам этапа планирования.
"""