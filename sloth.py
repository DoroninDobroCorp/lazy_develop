import vertexai
from vertexai.generative_models import GenerativeModel, HarmCategory, HarmBlockThreshold
import google.generativeai as genai
import os
import subprocess
import time
import re
import platform
import sys
import hashlib
import json

# --- Класс для цветов в консоли (Палитра "Nordic Calm") ---
class Colors:
    FAIL = '\033[38;2;191;97;106m'      # Красный (Aurora Red)
    OKGREEN = '\033[38;2;163;190;140m'   # Зеленый (Aurora Green)
    WARNING = '\033[38;2;235;203;139m'   # Желтый (Aurora Yellow)
    OKBLUE = '\033[38;2;94;129;172m'     # Голубой (Polar Night Blue)
    HEADER = '\033[38;2;180;142;173m'   # Пурпурный (Aurora Purple)
    CYAN = '\033[38;2;136;192;208m'     # Бирюзовый (Aurora Cyan)
    ENDC = '\033[0m'                    # Сброс
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GREY = '\033[38;2;106;114;128m'      # Серый для второстепенной информации

# --- НАСТРОЙКИ ---
# ИЗМЕНЕНО: Вставлен ваш новый API ключ.
GOOGLE_API_KEY = "AIzaSyA9kQwlc_fWpgQ64qG6yDJkis7PsgxljCw"

GOOGLE_CLOUD_PROJECT = "useful-gearbox-464618-v3"
GOOGLE_CLOUD_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro"

CONTEXT_SCRIPT = 'AskGpt.py'
CONTEXT_FILE = 'message_1.txt'
HISTORY_FILE = 'sloth_history.json'
ALLOWED_COMMANDS = (
    "sed", "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./", "cat"
)
MAX_ITERATIONS = 15
API_TIMEOUT_SECONDS = 600

# --- Глобальные переменные для модели ---
model = None
ACTIVE_API_SERVICE = "N/A"
GOOGLE_AI_HAS_FAILED_THIS_SESSION = False

def initialize_model():
    """
    Инициализирует модель Gemini.
    Приоритет: Google API Key. Запасной вариант: Vertex AI.
    Запоминает, если Google API Key отказал в текущей сессии.
    """
    global model, ACTIVE_API_SERVICE, GOOGLE_AI_HAS_FAILED_THIS_SESSION

    print(f"{Colors.CYAN}⚙️  ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}{Colors.ENDC}")

    generation_config = {
        "temperature": 1, "top_p": 1, "top_k": 1, "max_output_tokens": 32768
    }

    if not GOOGLE_AI_HAS_FAILED_THIS_SESSION and GOOGLE_API_KEY:
        print(f"{Colors.CYAN}🔑 ЛОГ: Пробую приоритетный сервис: Google AI (API Key)...{Colors.ENDC}")
        try:
            genai.configure(api_key=GOOGLE_API_KEY)
            genai_safety_settings = {
                'HARM_CATEGORY_HARASSMENT': 'block_medium_and_above',
                'HARM_CATEGORY_HATE_SPEECH': 'block_medium_and_above',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'block_medium_and_above',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'block_none'
            }
            model = genai.GenerativeModel(
                model_name=MODEL_NAME,
                generation_config=generation_config,
                safety_settings=genai_safety_settings
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
        vertex_safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        model = GenerativeModel(
            model_name=MODEL_NAME,
            generation_config=generation_config,
            safety_settings=vertex_safety_settings
        )
        ACTIVE_API_SERVICE = "Vertex AI"
        print(f"{Colors.OKGREEN}✅ ЛОГ: Vertex AI SDK успешно инициализирован.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель ни одним из способов: {e}{Colors.ENDC}")
        sys.exit(1)


def send_request_to_model(prompt_text, iteration_count):
    """
    ИСПРАВЛЕНО: Отправляет запрос, обрабатывая различия между API.
    """
    global model, GOOGLE_AI_HAS_FAILED_THIS_SESSION
    try:
        print(f"{Colors.CYAN}🧠 ЛОГ: [Итерация {iteration_count}] Готовлю запрос в модель ({ACTIVE_API_SERVICE}).{Colors.ENDC}")
        save_prompt_for_debugging(prompt_text)
        print(f"{Colors.CYAN}⏳ ЛОГ: Отправляю запрос... (таймаут: {API_TIMEOUT_SECONDS} сек){Colors.ENDC}")
        
        response = None
        if ACTIVE_API_SERVICE == "Google AI (API Key)":
            request_options = {"timeout": API_TIMEOUT_SECONDS}
            response = model.generate_content(prompt_text, request_options=request_options)
        elif ACTIVE_API_SERVICE == "Vertex AI":
            response = model.generate_content(prompt_text)
        else:
            raise ValueError(f"Попытка вызова неизвестного сервиса API: {ACTIVE_API_SERVICE}")

        if not response:
            raise ValueError("Ответ от модели пустой.")

        print(f"{Colors.OKGREEN}✅ ЛОГ: Ответ от модели получен успешно.{Colors.ENDC}")
        return response.text
        
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА при запросе к API ({ACTIVE_API_SERVICE}): {e}{Colors.ENDC}")
        error_str = str(e).lower()
        if ACTIVE_API_SERVICE == "Google AI (API Key)" and ("quota" in error_str or "rate limit" in error_str):
            print(f"{Colors.FAIL}🚨 ЛОГ: ОБНАРУЖЕНА ОШИБКА КВОТЫ!{Colors.ENDC}")
            print(f"{Colors.CYAN}   - Перманентно (на эту сессию) переключаюсь на Vertex AI...{Colors.ENDC}")
            GOOGLE_AI_HAS_FAILED_THIS_SESSION = True
            model = None
            initialize_model()
        return None


def main(is_fix_mode=False):
    """
    ИСПРАВЛЕНО: Основной рабочий цикл с корректным подсчетом итераций.
    """
    user_goal, error_log = get_user_input()
    if not user_goal:
        print(f"{Colors.WARNING}Цель не была указана. Завершение работы.{Colors.ENDC}")
        return "Цель не была указана."
    
    initial_task = user_goal + (f"\n\n--- ЛОГ ОШИБКИ ---\n{error_log}" if error_log else "")
    project_context = get_project_context()
    if not project_context:
        return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить контекст проекта.{Colors.ENDC}"
    
    current_prompt = get_initial_prompt(project_context, initial_task, load_fix_history() if is_fix_mode else None)
    attempt_history = []
    
    iteration_count = 1
    while iteration_count <= MAX_ITERATIONS:
        print(f"\n{Colors.BOLD}{Colors.HEADER}🚀 --- АВТОМАТИЧЕСКАЯ ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} (API: {ACTIVE_API_SERVICE}) ---{Colors.ENDC}")

        answer = send_request_to_model(current_prompt, iteration_count)
        if not answer:
            if model:
                print(f"{Colors.WARNING}🔄 ЛОГ: Ответ от модели не получен, пробую снова...{Colors.ENDC}")
                print(f"{Colors.WARNING}⏸️  ЛОГ: Пауза на 5 секунд перед повторной попыткой...{Colors.ENDC}")
                time.sleep(5)
                continue
            else:
                return "Критическая ошибка: Не удалось получить ответ и нет запасного API."
        
        if answer.strip().upper().startswith("ГОТОВО"):
            done_summary = extract_done_summary_block(answer)
            manual_steps = extract_manual_steps_block(answer)
            final_message = f"{Colors.OKGREEN}✅ Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
            if done_summary:
                save_completion_history(user_goal, done_summary)
                print(f"{Colors.OKGREEN}📄 ИТОГОВОЕ РЕЗЮМЕ:\n{Colors.CYAN}{done_summary}{Colors.ENDC}")
            if manual_steps:
                 final_message += f"\n\n{Colors.WARNING}✋ ТРЕБУЮТСЯ РУЧНЫЕ ДЕЙСТВИЯ:{Colors.ENDC}\n{manual_steps}"
            return final_message

        commands_to_run = extract_todo_block(answer)
        if not commands_to_run:
            print(f"{Colors.FAIL}❌ ЛОГ: Модель вернула ответ без команд. Пробую на следующей итерации.{Colors.ENDC}")
            current_prompt = get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
            iteration_count += 1
            continue

        strategy_description = extract_summary_block(answer) or "Стратегия не описана."
        print(f"\n{Colors.OKBLUE}🔧 Найдены shell-команды для применения:{Colors.ENDC}\n" + "-"*20 + f"\n{commands_to_run}\n" + "-"*20)

        success, failed_command, error_message = apply_shell_commands(commands_to_run)
        project_context = get_project_context()
        if not project_context: return f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"

        history_entry = f"**Итерация {iteration_count}:**\n**Стратегия:** {strategy_description}\n"
        if success:
            history_entry += "**Результат:** УСПЕХ"
            current_prompt = get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
        else:
            history_entry += f"**Результат:** ПРОВАЛ\n**Ошибка:** {error_message}"
            current_prompt = get_error_fixing_prompt(failed_command, error_message, user_goal, project_context, iteration_count + 1, attempt_history)
        
        attempt_history.append(history_entry)
        iteration_count += 1

    return f"{Colors.WARNING}⌛ Достигнут лимит в {MAX_ITERATIONS} итераций. Задача не была завершена.{Colors.ENDC}"


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ПОЛНЫЕ ВЕРСИИ) ---

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

def get_project_context():
    print(f"{Colors.CYAN}🔄 ЛОГ: Обновляю контекст проекта...{Colors.ENDC}")
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_to_run_path = os.path.join(script_dir, CONTEXT_SCRIPT)
        context_file_path = os.path.join(script_dir, CONTEXT_FILE)

        if os.path.exists(context_file_path): os.remove(context_file_path)

        subprocess.run(['python3', script_to_run_path], check=True, capture_output=True, text=True, encoding='utf-8')

        with open(context_file_path, 'r', encoding='utf-8') as f:
            context_data = f.read()

        print(f"{Colors.OKGREEN}✅ ЛОГ: Контекст успешно обновлен. Размер: {len(context_data)} символов.{Colors.ENDC}")
        return context_data
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}{Colors.ENDC}")
        return None

def extract_todo_block(text):
    match = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    if match: return match.group(1).strip()
    return None

def extract_summary_block(text):
    match = re.search(r"```summary\s*(.*?)\s*```", text, re.DOTALL)
    if match: return match.group(1).strip()
    return None

def extract_manual_steps_block(text):
    match = re.search(r"```manual\s*(.*?)\s*```", text, re.DOTALL)
    if match: return match.group(1).strip()
    return None

def extract_done_summary_block(text):
    match = re.search(r"```done_summary\s*(.*?)\s*```", text, re.DOTALL)
    if match: return match.group(1).strip()
    return None

def get_file_hash(filepath):
    if not os.path.exists(filepath) or os.path.isdir(filepath): return None
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()

def apply_shell_commands(commands_str):
    print(f"{Colors.OKBLUE}  [Детали] Вход в apply_shell_commands().{Colors.ENDC}")

    filepaths = re.findall(r'[\w\/\-\.]+\.[\w]+', commands_str)
    hashes_before = {fp: get_file_hash(fp) for fp in filepaths if os.path.exists(fp) and not os.path.isdir(fp)}

    try:
        is_macos = platform.system() == "Darwin"
        commands_str_adapted = re.sub(r"sed -i ", "sed -i '.bak' ", commands_str) if is_macos else commands_str

        full_command = f"set -e\n{commands_str_adapted}"

        print(f"{Colors.WARNING}⚡️ ЛОГ: Выполняю блок команд (с set -e):\n---\n{full_command}\n---{Colors.ENDC}")
        result = subprocess.run(['bash', '-c', full_command], capture_output=True, text=True, encoding='utf-8')

        if result.returncode != 0:
            error_msg = f"Команда завершилась с ненулевым кодом выхода ({result.returncode}).\nОшибка (STDERR): {result.stderr.strip()}"
            print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА при выполнении блока команд.\n{error_msg}{Colors.ENDC}")
            return False, commands_str, result.stderr.strip() or "Команда провалилась без вывода в stderr."

        if result.stderr:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ (STDERR от успешной команды):\n{result.stderr.strip()}{Colors.ENDC}")

        if is_macos: subprocess.run("find . -name '*.bak' -delete", shell=True, check=True)

        hashes_after = {fp: get_file_hash(fp) for fp in hashes_before.keys()}

        if hashes_before and all(hashes_before.get(fp) == hashes_after.get(fp) for fp in hashes_before):
            error_msg = "Команда выполнилась успешно, но не изменила ни одного из целевых файлов. Вероятно, шаблон (например, в sed) не был найден или путь к файлу неверен."
            final_error_message = result.stderr.strip() if result.stderr else error_msg
            print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА ЛОГИКИ: {error_msg}{Colors.ENDC}")
            if result.stderr: print(f"Причина из STDERR: {final_error_message}")
            return False, commands_str, final_error_message

        print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен и изменил файлы.{Colors.ENDC}")
        return True, None, None
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Непредвиденная ОШИБКА в apply_shell_commands: {e}{Colors.ENDC}")
        return False, commands_str, str(e)

def extract_filepath_from_command(command):
    parts = command.split()
    for part in reversed(parts):
        if part in ['-c', '-e', '<<']: continue
        clean_part = part.strip("'\"")
        if ('/' in clean_part or '.' in clean_part) and os.path.exists(clean_part):
            return clean_part
    return None

def save_prompt_for_debugging(prompt_text):
    try:
        with open("sloth_debug_prompt.txt", "w", encoding='utf-8') as f:
            f.write(prompt_text)
        print(f"{Colors.OKBLUE}   - Отладочная информация: Полный промпт сохранен в 'sloth_debug_prompt.txt'.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.WARNING}   - ВНИМАНИЕ: Не удалось сохранить отладочный файл промпта: {e}{Colors.ENDC}")

def _read_multiline_input(prompt):
    print(prompt)
    lines = []
    empty_line_count = 0
    while empty_line_count < 3:
        try:
            line = input()
            if line:
                lines.append(line)
                empty_line_count = 0
            else:
                empty_line_count += 1
        except EOFError:
            break
    return '\n'.join(lines).strip()

def get_user_input():
    goal_prompt = (
        f"{Colors.HEADER}{Colors.BOLD}👋 Привет! Опиши свою основную цель.{Colors.ENDC}\n"
        f"{Colors.CYAN}💡 Пожалуйста, будь максимально точен и детален. "
        f"Чем лучше ты опишешь проблему и желаемый результат, тем быстрее я смогу помочь.\n"
        f"(Для завершения ввода, нажми Enter 3 раза подряд){Colors.ENDC}"
    )
    user_goal = _read_multiline_input(goal_prompt)

    if not user_goal:
        return None, None

    log_prompt = f"\n{Colors.HEADER}{Colors.BOLD}👍 Отлично. Теперь, если есть лог ошибки, вставь его. Если нет, просто нажми Enter 3 раза.{Colors.ENDC}"
    error_log = _read_multiline_input(log_prompt)

    return user_goal, error_log

def save_completion_history(goal, summary):
    history_data = {"previous_attempts": []}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except json.JSONDecodeError:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Файл истории {HISTORY_FILE} поврежден. Создаю новый.{Colors.ENDC}")

    new_entry = {
        "initial_goal": goal,
        "solution_summary": summary
    }
    history_data.get("previous_attempts", []).insert(0, new_entry)

    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)
        print(f"{Colors.OKGREEN}💾 ЛОГ: История решения сохранена в {HISTORY_FILE}.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось сохранить историю решения: {e}{Colors.ENDC}")

def load_fix_history():
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
        
        attempts = history_data.get("previous_attempts", [])
        if not attempts:
            return None
        
        last_attempt = attempts[0]
        
        text_history = (
            f"Это твоя самая последняя попытка решения, которая оказалась неверной:\n"
            f"  - Поставленная задача: {last_attempt.get('initial_goal', 'N/A')}\n"
            f"  - Твое 'решение': {last_attempt.get('solution_summary', 'N/A')}"
        )
        return text_history
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось загрузить или прочитать файл истории {HISTORY_FILE}: {e}{Colors.ENDC}")
        return None

def notify_user(message):
    print(f"{Colors.OKBLUE}📢 ЛОГ: Отправляю уведомление: {message.replace(Colors.ENDC, '')}{Colors.ENDC}")
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(['afplay', '/System/Library/Sounds/Sosumi.aiff'], check=True, timeout=5)
        elif system == "Linux":
            subprocess.run(['zenity', '--info', '--text', message, '--title', 'Sloth Script', '--timeout=10', '--window-icon=info'], check=True, timeout=10)
        elif system == "Windows":
            command = f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show(\'{message}\', \'Sloth Script\');"'
            subprocess.run(command, shell=True, check=True, timeout=30)
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось отправить системное уведомление. Ошибка: {e}.{Colors.ENDC}")


if __name__ == "__main__":
    is_fix_mode = '--fix' in sys.argv or '-fix' in sys.argv

    if not is_fix_mode and os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
            print(f"{Colors.CYAN}🗑️  ЛОГ: Очищена старая история ({HISTORY_FILE}).{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось удалить файл истории: {e}{Colors.ENDC}")
    
    if os.path.exists("sloth_debug_prompt.txt"):
        os.remove("sloth_debug_prompt.txt")
    if os.path.exists("sloth_debug_bad_response.txt"):
        os.remove("sloth_debug_bad_response.txt")

    initialize_model()
    final_status = "Работа завершена."
    try:
        if model:
            final_status = main(is_fix_mode)
        else:
            final_status = f"{Colors.FAIL}❌ Не удалось запустить основной цикл, так как модель не была инициализирована.{Colors.ENDC}"
    except KeyboardInterrupt:
        final_status = f"{Colors.OKBLUE}🔵 Процесс прерван пользователем.{Colors.ENDC}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        final_status = f"{Colors.FAIL}❌ Скрипт аварийно завершился с ошибкой: {e}{Colors.ENDC}"
    finally:
        print(f"\n{final_status}")
        notify_user(final_status)
        time.sleep(1)
        print(f"\n{Colors.BOLD}🏁 Скрипт завершил работу.{Colors.ENDC}")