# Файл: sloth_core.py
import vertexai
from vertexai.generative_models import GenerativeModel, HarmCategory, HarmBlockThreshold
import google.generativeai as genai
import os
from colors import Colors

# --- НАСТРОЙКИ ЯДРА ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyA9kQwlc_fWpgQ64qG6yDJkis7PsgxljCw")
GOOGLE_CLOUD_PROJECT = "useful-gearbox-464618-v3"
GOOGLE_CLOUD_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro"
API_TIMEOUT_SECONDS = 600
ALLOWED_COMMANDS = (
    "sed", "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./", "cat"
)

MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input": {
            "tiers": [
                {"up_to": 200000, "price": 1.25},
                {"up_to": float('inf'), "price": 2.50}
            ]
        },
        "output": {
            "tiers": [
                {"up_to": 200000, "price": 10.00},
                {"up_to": float('inf'), "price": 15.00}
            ]
        }
    },
    "gemini-1.5-pro-latest": {
        "input": { "tiers": [{"up_to": float('inf'), "price": 3.50}] },
        "output": { "tiers": [{"up_to": float('inf'), "price": 10.50}] }
    }
}

# --- Глобальные переменные состояния API, управляемые ядром ---
model = None
ACTIVE_API_SERVICE = "N/A"
GOOGLE_AI_HAS_FAILED_THIS_SESSION = False

def initialize_model():
    """Инициализирует и возвращает модель Gemini."""
    global model, ACTIVE_API_SERVICE, GOOGLE_AI_HAS_FAILED_THIS_SESSION

    print(f"{Colors.CYAN}⚙️  ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}{Colors.ENDC}")
    generation_config = {"temperature": 1, "top_p": 1, "top_k": 1, "max_output_tokens": 32768}

    if not GOOGLE_AI_HAS_FAILED_THIS_SESSION and GOOGLE_API_KEY:
        print(f"{Colors.CYAN}🔑 ЛОГ: Пробую приоритетный сервис: Google AI (API Key)...{Colors.ENDC}")
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            model = genai.GenerativeModel(
                model_name=MODEL_NAME,
                generation_config=generation_config,
                safety_settings={'HARM_CATEGORY_HARASSMENT': 'block_medium_and_above', 'HARM_CATEGORY_HATE_SPEECH': 'block_medium_and_above', 'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'block_medium_and_above', 'HARM_CATEGORY_DANGEROUS_CONTENT': 'block_none'}
            )
            model.generate_content("test", request_options={"timeout": 60})
            ACTIVE_API_SERVICE = "Google AI (API Key)"
            print(f"{Colors.OKGREEN}✅ ЛОГ: Успешно инициализировано через {ACTIVE_API_SERVICE}.{Colors.ENDC}")
            return
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось инициализировать через Google AI API Key: {e}{Colors.ENDC}")
            print(f"{Colors.CYAN}🔄 ЛОГ: Переключаюсь на запасной вариант (Vertex AI)...{Colors.ENDC}")
            GOOGLE_AI_HAS_FAILED_THIS_SESSION = True
            model = None

    if GOOGLE_AI_HAS_FAILED_THIS_SESSION:
         print(f"{Colors.CYAN}🔩 ЛОГ: Попытка инициализации через Vertex AI...{Colors.ENDC}")
    else:
         print(f"{Colors.CYAN}🔑 ЛОГ: API ключ не указан. Использую Vertex AI.{Colors.ENDC}")

    try:
        vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)
        model = GenerativeModel(
             model_name=MODEL_NAME,
             generation_config=generation_config,
             safety_settings={HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
        )
        ACTIVE_API_SERVICE = "Vertex AI"
        print(f"{Colors.OKGREEN}✅ ЛОГ: Vertex AI SDK успешно инициализирован.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель: {e}{Colors.ENDC}")
        model = None
        ACTIVE_API_SERVICE = "N/A"

def get_active_service_details():
    """Возвращает текущую модель и сервис для CLI."""
    return model, ACTIVE_API_SERVICE

def send_request_to_model(model_instance, active_service, prompt_text, iteration_count=0):
    """Возвращает словарь с текстом ответа и информацией о токенах."""
    global GOOGLE_AI_HAS_FAILED_THIS_SESSION
    try:
        log_header = f"[Итерация {iteration_count}]" if iteration_count > 0 else "[Этап планирования]"
        print(f"{Colors.CYAN}🧠 ЛОГ: {log_header} Готовлю запрос в модель ({active_service}).{Colors.ENDC}")
        print(f"{Colors.CYAN}⏳ ЛОГ: Отправляю запрос... (таймаут: {API_TIMEOUT_SECONDS} сек){Colors.ENDC}")
        
        response = None
        if active_service == "Google AI (API Key)":
            request_options = {"timeout": API_TIMEOUT_SECONDS}
            response = model_instance.generate_content(prompt_text, request_options=request_options)
        elif active_service == "Vertex AI":
            response = model_instance.generate_content(prompt_text)
        else:
            raise ValueError(f"Неизвестный сервис API: {active_service}")
        
        if not response: 
            raise ValueError("Ответ от модели пустой.")
            
        print(f"{Colors.OKGREEN}✅ ЛОГ: Ответ от модели получен успешно.{Colors.ENDC}")
        
        return {
            "text": response.text,
            "input_tokens": response.usage_metadata.prompt_token_count,
            "output_tokens": response.usage_metadata.candidates_token_count
        }
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА при запросе к API ({active_service}): {e}{Colors.ENDC}")
        error_str = str(e).lower()
        if active_service == "Google AI (API Key)" and ("quota" in error_str or "rate limit" in error_str):
            print(f"{Colors.FAIL}🚨 ЛОГ: ОБНАРУЖЕНА ОШИБКА КВОТЫ!{Colors.ENDC}")
            print(f"{Colors.CYAN}   - Перманентно (на эту сессию) переключаюсь на Vertex AI...{Colors.ENDC}")
            GOOGLE_AI_HAS_FAILED_THIS_SESSION = True
            initialize_model()
        return None

def get_command_rules(stage='execution'):
    """
    Возвращает правила в зависимости от этапа (планирование или исполнение).
    """
    base_rules = f"""
**ГЛОБАЛЬНЫЕ ПРАВИЛА:**

1.  **Рабочая Директория:** Все команды выполняются из **корня проекта**. **ЗАПРЕЩЕНО** использовать `cd`. Для доступа к файлам в подпапках всегда указывай полный относительный путь (например, `backend/src/app.ts` или `./backend/start.sh`).

2.  **Полнота Кода:** **ЗАПРЕЩЕНО** использовать плейсхолдеры, многоточия (...) или комментарии (`// ... остальной код`) для сокращения блоков кода в ```bash```. Всегда предоставляй полный, готовый к выполнению код.

3.  **Разрешенные Команды:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

4.  **Фокус и Прагматизм:** Твоя главная цель — решить **исходную задачу** пользователя. Не занимайся перфекционизмом: не исправляй стиль кода и не делай рефакторинг, не связанный с задачей.
"""

    if stage == 'execution':
        return f"""
Ты — AI-ассистент в автоматизированной системе. Твоя задача — анализировать код и генерировать shell-команды для его изменения.

**ПРАВИЛА ЭТАПА ИСПОЛНЕНИЯ:**

1.  **Стратегия Изменений:**
    *   **Точечные правки (`sed`):** Используй `sed` **только для простых, однострочных** замен. Команды `sed` помещай в блок ```bash ... ```.
    *   **Полная перезапись файла:** Для любых многострочных или сложных изменений **ЗАПРЕЩЕНО** использовать `cat`. Вместо этого используй специальный блок ```write_file path/to/your/file.py ... ```. Содержимое файла должно идти сразу после пути.

2.  **Перезапись Файлов (Высокий риск!):**
    *   **ВНИМАНИЕ:** При использовании `write_file` ты должен быть ПРЕДЕЛЬНО АККУРАТЕН. Всегда включай в блок **полное и корректное** содержимое файла.
    *   **Стратегия "Один за раз":** Если твоя задача требует полной перезаписи **нескольких** больших файлов, изменяй **только один файл за одну итерацию**.

3.  **Формат Ответа:**
    *   **Действия:** Если нужны правки, твой ответ **ОБЯЗАН** содержать ОДИН из блоков действий (`bash` или `write_file`) и СРАЗУ ПОСЛЕ него блок `summary`:
        1.  **Для точечных правок:** Блок ```bash ... ``` с командами `sed`.
        2.  **Для полной перезаписи:** Блок ```write_file path/to/file.py ... ``` с полным содержимым файла.
        3.  И сразу после блока действий — блок с кратким описанием стратегии: ```summary ... ```.
    *   **Завершение:** Если задача решена, напиши **только** `ГОТОВО`. После этого слова добавь блок ```done_summary ... ```. Если нужны ручные действия (например, `npm start`), добавь их в блок ```manual```.
{base_rules}
"""

    if stage == 'planning':
        return f"""
Ты — AI-планировщик. Твоя первая и главная задача — проанализировать запрос пользователя и убедиться, что он полностью понятен.

**ПРАВИЛА ЭТАПА ПЛАНИРОВАНИЯ:**

1.  **Анализ Задачи:** Внимательно изучи задачу пользователя и предоставленный **сокращенный** контекст проекта (только структура и сигнатуры).
2.  **Два Пути Развития:**
    *   **Путь А: Задача НЕПОНЯТНА.** Если задача сформулирована нечетко, неполно или требует дополнительной информации, которую нельзя найти в коде — **задай уточняющие вопросы пользователю**. Твой ответ должен содержать **только** блок ```clarification ... ``` с вопросами. Не придумывай план и не запрашивай файлы.
    *   **Путь Б: Задача ПОНЯТНА.** Если ты полностью уверен, что понимаешь, что нужно сделать, переходи к планированию. Твой ответ **ОБЯЗАН** содержать ДВА блока:
        1.  **План Действий:** ```plan ... ```. Опиши пошаговый план решения задачи. План должен быть детальным.
        2.  **Список Файлов:** ```files ... ```. Перечисли **все** файлы, которые, по твоему мнению, понадобятся для реализации этого плана. Указывай пути к файлам от корня проекта, каждый файл на новой строке. Не экономь! Твоя задача качество - запроси все что может понадобиться для понимания или может редактироваться!!! Это важно - приоритет КАЧЕСТВО!
3.  **Запреты:** На этом этапе **ЗАПРЕЩЕНО** генерировать ```bash``` или ```summary```. Твоя цель — либо задать вопросы, либо составить план и запросить файлы.
{base_rules}
"""

def get_clarification_and_planning_prompt(context, task):
    """
    НОВЫЙ ПРОМПТ: Для самого первого шага в интеллектуальном режиме.
    """
    rules = get_command_rules(stage='planning')
    return f"""{rules}

--- КОНТЕКСТ ПРОЕКТА (СОКРАЩЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

--- ЗАДАЧА ПОЛЬЗОВАТЕЛЯ ---
{task}
--- КОНЕЦ ЗАДАЧИ ---

Проанализируй задачу и контекст. Следуй правилам этапа планирования: либо запроси уточнения (`clarification`), либо предоставь план (`plan`) и список файлов (`files`).
"""

def get_initial_prompt(context, task, fix_history=None):
    """
    Этот промпт теперь используется для начала **этапа исполнения**.
    """
    history_prompt_section = ""
    if fix_history:
        history_prompt_section = f"""
--- ИСТОРИЯ ПРЕДЫДУЩЕГО РЕШЕНИЯ, КОТОРОЕ ОКАЗАЛОСЬ НЕВЕРНЫМ ---
{fix_history}
--- КОНЕЦ ИСТОРИИ ---
Проанализируй свою прошлую ошибку и начни заново.
"""
    return f"{get_command_rules(stage='execution')}\n{history_prompt_section}\n--- КОНТЕКСТ ПРОЕКТА (ПОЛНЫЙ ИЛИ ЧАСТИЧНЫЙ) ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---\nЗадача: {task}\nПроанализируй задачу и предоставь ответ, строго следуя правилам исполнения."

def get_review_prompt(context, goal, iteration_count, attempt_history):
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"\n**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):** Ты уже сделал несколько шагов. Пожалуйста, проанализируй проблему более комплексно.\n"
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
**ВАЖНО:** Предыдущий шаг выполнен. Код ниже — это **обновленное состояние** проекта.

**Твоя задача — ВЕРИФИКАЦИЯ:**
1.  Проанализируй **текущий** код, учитывая **всю историю твоих действий**.
2.  Если исходная цель достигнута, напиши `ГОТОВО`.
3.  Если цель НЕ достигнута, предоставь следующий блок команд и `summary`.

--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

Напоминаю ИСХОДНУЮ ЦЕЛЬ: {goal}
"""

def get_error_fixing_prompt(failed_command, error_message, goal, context, iteration_count, attempt_history):
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"\n**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):** Ты сделал несколько шагов, и сейчас произошла ошибка. Проанализируй проблему более комплексно.\n"
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
**ВАЖНО:** Твоя задача — исправить ошибку, которая только что произошла. Не пиши 'ГОТОВО'.

--- ДАННЫЕ О ТЕКУЩЕЙ ОШИБКЕ ---
КОМАНДА: {failed_command}
СООБЩЕНИЕ (stderr): {error_message}
--- КОНЕЦ ДАННЫХ ОБ ОШИБКЕ ---

Исходная ЦЕЛЬ была: {goal}

Проанализируй **текущую ошибку в контексте всей истории** и предоставь **исправленный блок команд** и `summary`.

--- КОНТЕКСТ, ГДЕ ПРОИЗОШЛА ОШИБКА ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
"""