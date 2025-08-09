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
from colors import Colors

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
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyA9kQwlc_fWpgQ64qG6yDJkis7PsgxljCw")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "useful-gearbox-464618-v3")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = os.getenv("SLOTH_MODEL_NAME", "gemini-2.5-pro")
API_TIMEOUT_SECONDS = int(os.getenv("SLOTH_API_TIMEOUT", "600"))

# ВАЖНО: максимальный бюджет размышлений. Можно переопределить через env SLOTH_THINKING_BUDGET
THINKING_BUDGET_TOKENS = int(os.getenv("SLOTH_THINKING_BUDGET", "24576"))

# Команды-исключения для bash
ALLOWED_COMMANDS = (
    "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./"
)

MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input": {"tiers": [{"up_to": 200000, "price": 1.25}, {"up_to": float('inf'), "price": 2.50}]},
        "output": {"tiers": [{"up_to": 200000, "price": 10.00}, {"up_to": float('inf'), "price": 15.00}]}
    },
    "gemini-1.5-pro-latest": {
        "input": {"tiers": [{"up_to": float('inf'), "price": 3.50}]},
        "output": {"tiers": [{"up_to": float('inf'), "price": 10.50}]}
    }
}

# --- Глобальные переменные состояния API ---
model = None  # в режиме google-genai здесь будет client, в остальных — объект модели
ACTIVE_API_SERVICE = "N/A"
GOOGLE_AI_HAS_FAILED_THIS_SESSION = False

# Базовая генерационная конфигурация — БЕЗ max_output_tokens!
GENERATION_TEMPERATURE = float(os.getenv("SLOTH_TEMPERATURE", "1"))
GENERATION_TOP_P = float(os.getenv("SLOTH_TOP_P", "1"))
GENERATION_TOP_K = int(float(os.getenv("SLOTH_TOP_K", "1")))

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

def send_request_to_model(model_instance, active_service, prompt_text, iteration_count=0):
    """Возвращает словарь с текстом ответа и информацией о токенах."""
    global GOOGLE_AI_HAS_FAILED_THIS_SESSION

    try:
        log_header = f"[Итерация {iteration_count}]" if iteration_count > 0 else "[Этап планирования]"
        print(f"{Colors.CYAN}🧠 ЛОГ: {log_header} Готовлю запрос в модель ({active_service}).{Colors.ENDC}")
        print(f"{Colors.CYAN}⏳ ЛОГ: Отправляю запрос... (таймаут: {API_TIMEOUT_SECONDS} сек){Colors.ENDC}")

        if active_service == "Google GenAI SDK":
            # Новый клиент + thinking_config
            cfg = GenerateContentConfig(
                temperature=GENERATION_TEMPERATURE,
                top_p=GENERATION_TOP_P,
                top_k=GENERATION_TOP_K,
                # критично: не задаём max_output_tokens
                thinking_config=ThinkingConfig(thinking_budget=THINKING_BUDGET_TOKENS),
            )
            response = model_instance.models.generate_content(
                model=MODEL_NAME,
                contents=prompt_text,
                config=cfg,
            )
            text, in_tok, out_tok = _extract_text_and_usage_from_genai_response(response)

        elif active_service == "Google AI (Legacy SDK)":
            # Старый generativeai; thinking тут недоступен, max_output_tokens не задаем
            request_options = {"timeout": API_TIMEOUT_SECONDS}
            response = model_instance.generate_content(prompt_text, request_options=request_options)
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

def get_command_rules(stage='execution'):
    """
    Возвращает правила в зависимости от этапа (планирование или исполнение).
    """
    base_rules = f"""
**ГЛОБАЛЬНЫЕ ПРАВИЛА (ОБЯЗАТЕЛЬНЫ К ИСПОЛНЕНИЮ):**

1.  **ПРАВИЛО ПУТЕЙ (САМОЕ ВАЖНОЕ!):**
    *   Все пути к файлам, которые ты используешь (в блоках `files`, `write_file`, `bash`), ДОЛЖНЫ быть **относительными от корня проекта**.
    *   **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** начинать путь с имени корневой папки проекта. Система автоматически работает из корня проекта.
    *   **Пример:** Если проект находится в папке `/path/to/my-project`, и тебе нужен файл `src/app.js`:
        *   **ПРАВИЛЬНО:** `src/app.js`
        *   **НЕПРАВИЛЬНО:** `my-project/src/app.js`

2.  **Рабочая Директория:** Все команды выполняются из **корня проекта**. **ЗАПРЕЩЕНО** использовать `cd`.

3.  **Разрешенные Команды:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

4.  **Фокус и Прагматизм:** Твоя главная цель — решить **исходную задачу** пользователя. Не занимайся перфекционизмом: не исправляй стиль кода и не делай рефакторинг, не связанный с задачей.
"""

    if stage == 'execution':
        return f"""
Ты — AI-ассистент в автоматизированной системе. Твоя задача — анализировать код и генерировать команды для его изменения.

**ПРАВИЛА ЭТАПА ИСПОЛНЕНИЯ:**

1.  **ПРАВИЛО №1: ТОЛЬКО `write_file`**
    *   Для **создания НОВЫХ** или **изменения СУЩЕСТВУЮЩИХ** файлов ты **ОБЯЗАН** использовать **только** блок ```write_file```.
    *   Этот блок полностью перезаписывает файл.

2.  **ПРАВИЛО №2: ПОЛНОТА КОДА (КРИТИЧЕСКИ ВАЖНО!)**
    *   Внутри блока ```write_file``` ты должен предоставить **ПОЛНОЕ СОДЕРЖИМОЕ** файла от первой до последней строчки.
    *   **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** использовать плейсхолдеры, многоточия (`...`), комментарии (`// ... остальной код`) или любые другие способы сокращения кода.

3.  **Формат Ответа:**
    *   **Действия:** Твой ответ **ОБЯЗАН** содержать ОДИН из блоков действий и СРАЗУ ПОСЛЕ него блок `summary`:
        1.  **Для команд терминала:** ```bash ... ```.
        2.  **Для СОЗДАНИЯ/ИЗМЕНЕНИЯ файла:** ```write_file path/to/file.py ... ```.
    *   **Завершение:** Если задача решена, напиши **только** `ГОТОВО`, затем блок ```done_summary ... ```. Для ручных шагов добавь блок ```manual```.

{base_rules}
"""

    if stage == 'planning':
        return f"""
Ты — AI-планировщик. Первая задача — убедиться, что исходная задача понятна.

**ПРАВИЛА ПЛАНИРОВАНИЯ:**

1.  Анализируй задачу и **сокращённый** контекст проекта.
2.  **Два пути**:
    *   Если задача **непонятна** — верни только ```clarification ... ```.
    *   Если задача **понятна** — верни ```plan ... ``` и ```files ... ```.
3.  Запрещено генерировать ```bash``` или `write_file` на этапе планирования.

{base_rules}
"""

def get_clarification_and_planning_prompt(context, task):
    rules = get_command_rules(stage='planning')
    return f"""{rules}

--- КОНТЕКСТ ПРОЕКТА (СОКРАЩЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

--- ЗАДАЧА ПОЛЬЗОВАТЕЛЯ ---
{task}
--- КОНЕЦ ЗАДАЧИ ---

Проанализируй задачу и контекст. Следуй правилам этапа планирования.
"""

def get_initial_prompt(context, task, fix_history=None):
    history_prompt_section = ""
    if fix_history:
        history_prompt_section = f"""
--- ИСТОРИЯ ПРЕДЫДУЩЕГО РЕШЕНИЯ, КОТОРОЕ ОКАЗАЛОСЬ НЕВЕРНЫМ ---
{fix_history}
--- КОНЕЦ ИСТОРИИ ---
Проанализируй свою прошлую ошибку и начни заново.
"""
    return f"""{get_command_rules(stage='execution')}
{history_prompt_section}
--- КОНТЕКСТ ПРОЕКТА (ПОЛНЫЙ ИЛИ ЧАСТИЧНЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
Задача: {task}
Проанализируй задачу и предоставь ответ, строго следуя правилам исполнения.
"""

def get_review_prompt(context, goal, iteration_count, attempt_history):
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"\n**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):** Сделано уже несколько шагов — проанализируй проблему глубже.\n"
    history_info = ""
    if attempt_history:
        history_info = (
            "--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК ---\n" +
            "\n---\n".join(attempt_history) +
            "\n--- КОНЕЦ ИСТОРИИ ---\n"
        )
    return f"""{get_command_rules(stage='execution')}
{iteration_info}
{history_info}
**ВАЖНО:** Предыдущий шаг выполнен. Код ниже — это **обновлённое состояние** проекта.

**Твоя задача — ВЕРИФИКАЦИЯ:**
1) Проанализируй текущий код с учётом истории.
2) Если цель достигнута — напиши `ГОТОВО`.
3) Иначе — дай следующий блок действий и `summary`.

--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЁННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

Напоминаю ИСХОДНУЮ ЦЕЛЬ: {goal}
"""

def get_error_fixing_prompt(failed_command, error_message, goal, context, iteration_count, attempt_history):
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
    return f"""{get_command_rules(stage='execution')}
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
