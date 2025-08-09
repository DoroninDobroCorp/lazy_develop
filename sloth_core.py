# Файл: sloth_core.py
import vertexai
from vertexai.generative_models import GenerativeModel, HarmCategory, HarmBlockThreshold
import google.generativeai as genai
import os
from colors import Colors

# --- НАСТРОЙКИ ЯДРА ---
# Читаем ключ из переменных окружения, если он там есть. Иначе используем "захардкоженный".
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyA9kQwlc_fWpgQ64qG6yDJkis7PsgxljCw")
GOOGLE_CLOUD_PROJECT = "useful-gearbox-464618-v3"
GOOGLE_CLOUD_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro"
API_TIMEOUT_SECONDS = 600
ALLOWED_COMMANDS = (
    "sed", "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./", "cat"
)

# Прайс-лист с многоуровневой структурой.
# Цены указаны в долларах США за 1 МИЛЛИОН токенов.
MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input": {
            "tiers": [
                {"up_to": 200000, "price": 1.25},
                {"up_to": float('inf'), "price": 2.50}
            ]
        },
        "output": {
            # Цена за выход зависит от общего количества токенов в промпте (вход)
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

def send_request_to_model(model_instance, active_service, prompt_text, iteration_count):
    """Возвращает словарь с текстом ответа и информацией о токенах."""
    global GOOGLE_AI_HAS_FAILED_THIS_SESSION
    try:
        print(f"{Colors.CYAN}🧠 ЛОГ: [Итерация {iteration_count}] Готовлю запрос в модель ({active_service}).{Colors.ENDC}")
        # Здесь можно добавить логику для сохранения промпта в debug-файл
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
        
        # Возвращаем не просто текст, а словарь с деталями
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
            initialize_model() # Переинициализируем модель немедленно
        return None

def get_command_rules():
    return f"""
Ты — AI-ассистент в автоматизированной системе. Твоя задача — анализировать код и генерировать shell-команды для его изменения.

**КЛЮЧЕВЫЕ ПРАВИЛА:**

1.  **СТРАТЕГИЯ ИЗМЕНЕНИЙ:**
    *   **Точечные правки (`sed`):** Используй `sed` **только для простых, однострочных** замен, которые не содержат сложных спецсимволов.
    *   **Полная перезапись (`cat`):** Используй `cat <<'EOF' > path/to/file.txt ... EOF`, если нужно изменить **сигнатуру функции, JSX-разметку, несколько строк кода подряд или строки со сложными кавычками/символами**. Это предпочтительный метод для сложного рефакторинга. **Не пытайся использовать `sed` для этих целей!**

2.  **ПЕРЕЗАПИСЬ ФАЙЛОВ (Высокий риск!):**
    *   **ВНИМАНИЕ:** При использовании `cat` ты должен быть ПРЕДЕЛЬНО АККУРАТЕН. Всегда включай в блок `EOF` **полное и корректное** содержимое файла, сохраняя исходное форматирование.
    *   **СТРАТЕГИЯ "ОДИН БОЛЬШОЙ ЗА РАЗ":** Если твоя задача требует полной перезаписи **нескольких** больших файлов, изменяй **только один файл за одну итерацию**.

3.  **ФОРМАТ ОТВЕТА — ЭТО ЗАКОН:**
    *   **Действия:** Если нужны правки, твой ответ **ОБЯЗАН** содержать ДВА блока:
        1. Блок команд, обернутый в ```bash ... ```.
        2. Сразу после него — блок с кратким описанием твоей стратегии, обернутый в ```summary ... ```.
    *   **Завершение:**
        *   Если задача полностью решена и **не требует ручных действий от человека**, напиши **только** `ГОТОВО`. После этого слова добавь блок ```done_summary ... ``` с кратким перечнем ключевых шагов, которые привели к решению.
        *   Если после твоих правок **человеку нужно выполнить команды** (например, `npm start`), сначала напиши `ГОТОВО`, затем добавь блок ```done_summary ... ```, и только потом — блок ```manual ... ``` с инструкциями.

4.  **ФОКУС И ПРАГМАТИЗМ:**
    *   Твоя главная цель — решить **исходную задачу** пользователя. Как только функциональность заработает, напиши `ГОТОВО`.
    *   **Не занимайся перфекционизмом:** не исправляй стиль кода, не делай рефакторинг и не исправляй другие проблемы, не связанные с задачей, если они не являются прямой причиной сбоя.

5.  **РАЗРЕШЕННЫЕ КОМАНДЫ:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

6.  **ПОЛНОТА КОДА:** **ЗАПРЕЩЕНО** использовать плейсхолдеры, многоточия (...) или комментарии (`// ... остальной код`) для сокращения блоков кода. Всегда предоставляй полный, готовый к выполнению код.
"""

def get_initial_prompt(context, task, fix_history=None):
    history_prompt_section = ""
    if fix_history:
        history_prompt_section = f"""
--- ИСТОРИЯ ПРЕДЫДУЩЕГО РЕШЕНИЯ, КОТОРОЕ ОКАЗАЛОСЬ НЕВЕРНЫМ ---
Ты уже пытался решить эту задачу и сообщил 'ГОТОВО', но это было ошибкой.
Вот краткое изложение твоих предыдущих действий:
{fix_history}
--- КОНЕЦ ИСТОРИИ ---
Проанализируй свою прошлую ошибку, новую информацию от пользователя и начни заново.
"""
    return f"{get_command_rules()}\n{history_prompt_section}\n--- КОНТЕКСТ ПРОЕКТА ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---\nЗадача: {task}\nПроанализируй задачу и предоставь ответ, строго следуя правилам."

def get_review_prompt(context, goal, iteration_count, attempt_history):
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"""
**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):**
Ты уже сделал несколько шагов. Пожалуйста, проанализируй проблему более комплексно.
"""
    history_info = ""
    if attempt_history:
        history_info = (
            "--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК ---\n"
            "Вот что ты уже сделал. Проанализируй всю историю (и успехи, и неудачи), чтобы выработать следующий шаг.\n\n"
            + "\n---\n".join(attempt_history) +
            "\n\n--- КОНЕЦ ИСТОРИИ ---\n"
        )
    return f"""{get_command_rules()}
{iteration_info}
{history_info}
**ВАЖНО:** Предыдущий шаг выполнен. Код ниже — это **обновленное состояние** проекта.

**Твоя задача — ВЕРИФИКАЦИЯ:**
1.  Проанализируй **текущий** код, учитывая **всю историю твоих действий**.
2.  Если исходная цель достигнута, напиши `ГОТОВО`. Не ищи дополнительных улучшений.
3.  Если цель НЕ достигнута, предоставь следующий блок команд и описание (`summary`) для следующего шага.

--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

Напоминаю ИСХОДНУЮ ЦЕЛЬ: {goal}
"""

def get_error_fixing_prompt(failed_command, error_message, goal, context, iteration_count, attempt_history):
    iteration_info = ""
    if iteration_count >= 4:
        iteration_info = f"""
**ОСОБОЕ ВНИМАНИЕ (Итерация {iteration_count}):**
Ты уже сделал несколько шагов, и сейчас произошла ошибка. Пожалуйста, проанализируй проблему более комплексно.
"""
    history_info = ""
    if attempt_history:
        history_info = (
            "--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК ---\n"
            "Вот что ты уже сделал. Проанализируй всю историю (и успехи, и неудачи), чтобы понять, почему текущая команда провалилась.\n\n"
            + "\n---\n".join(attempt_history) +
            "\n--- КОНЕЦ ИСТОРИИ ---\n"
        )

    return f"""{get_command_rules()}
{iteration_info}
{history_info}
**ВАЖНО:** Твоя задача — исправить ошибку, которая только что произошла. Не пиши 'ГОТОВО'.

--- ДАННЫЕ О ТЕКУЩЕЙ ОШИБКЕ ---
КОМАНДА: {failed_command}
СООБЩЕНИЕ (stderr): {error_message}
--- КОНЕЦ ДАННЫХ ОБ ОШИБКЕ ---

Исходная ЦЕЛЬ была: {goal}

Проанализируй **текущую ошибку в контексте всей истории** и предоставь **исправленный блок команд** и описание (`summary`).

--- КОНТЕКСТ, ГДЕ ПРОИЗОШЛА ОШИБКА ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
"""