# -*- coding: utf-8 -*-
"""
Автоматизированный AI-ассистент для написания и исправления кода.
Скрипт интерактивно запрашивает у пользователя цель и опциональный лог ошибки,
а затем итеративно взаимодействует с моделью Gemini для достижения цели.
"""
import vertexai
from vertexai.generative_models import GenerativeModel, HarmCategory, HarmBlockThreshold
import os
import subprocess
import time
import re
import platform
import sys
import hashlib

# --- Класс для цветов в консоли ---
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    CYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# --- НАСТРОЙКИ ---
GOOGLE_CLOUD_PROJECT = "useful-gearbox-464618-v3"
GOOGLE_CLOUD_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro"

CONTEXT_SCRIPT = 'AskGpt.py'
CONTEXT_FILE = 'message_1.txt'
ALLOWED_COMMANDS = (
    "sed", "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./", "cat"
)
MAX_ITERATIONS = 15
API_TIMEOUT_SECONDS = 600

# --- КОНФИГУРАЦИЯ МОДЕЛИ ---
print(f"{Colors.CYAN}⚙️  ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}{Colors.ENDC}")
try:
    vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)
    print(f"{Colors.OKGREEN}✅ ЛОГ: Vertex AI SDK успешно инициализирован для проекта '{GOOGLE_CLOUD_PROJECT}'.{Colors.ENDC}")
except Exception as e:
    print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА инициализации Vertex AI SDK: {e}{Colors.ENDC}")
    print(f"{Colors.WARNING}⚠️  ПОДСКАЗКА: Убедитесь, что вы аутентифицированы. Выполните в терминале: gcloud auth application-default login{Colors.ENDC}")
    sys.exit(1)

generation_config = {
    "temperature": 1, "top_p": 1, "top_k": 1, "max_output_tokens": 32768
}
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = GenerativeModel(
    model_name=MODEL_NAME,
    generation_config=generation_config,
    safety_settings=safety_settings
)
print(f"{Colors.OKGREEN}✅ ЛОГ: Модель '{MODEL_NAME}' создана.{Colors.ENDC}")


# --- БЛОК ПРОМПТ-ШАБЛОНОВ ---

def get_command_rules():
    """Возвращает базовый набор правил для модели."""
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
        *   Если задача полностью решена и **не требует ручных действий от человека**, напиши **только** одно слово: `ГОТОВО`.
        *   Если после твоих правок **человеку нужно выполнить команды** (например, `npm start`), сначала напиши `ГОТОВО`, а затем добавь блок ```manual ... ``` с инструкциями.

4.  **ФОКУС И ПРАГМАТИЗМ:**
    *   Твоя главная цель — решить **исходную задачу** пользователя. Как только функциональность заработает, напиши `ГОТОВО`.
    *   **Не занимайся перфекционизмом:** не исправляй стиль кода, не делай рефакторинг и не исправляй другие проблемы, не связанные с задачей, если они не являются прямой причиной сбоя.

5.  **РАЗРЕШЕННЫЕ КОМАНДЫ:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

6.  **ПОЛНОТА КОДА:** **ЗАПРЕЩЕНО** использовать плейсхолдеры, многоточия (...) или комментарии (`// ... остальной код`) для сокращения блоков кода. Всегда предоставляй полный, готовый к выполнению код.
"""

def get_initial_prompt(context, task):
    """Создает первоначальный промпт для старта работы (с возможным логом ошибки)."""
    return f"{get_command_rules()}\n--- КОНТЕКСТ ПРОЕКТА ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---\nЗадача: {task}\nПроанализируй задачу и предоставь ответ, строго следуя правилам."

def get_review_prompt(context, goal, iteration_count, attempt_history):
    """Создает промпт для верификации, включая полную историю попыток."""
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
            + "\n---\n".join(f"**На итерации {i+1}:**\n{s}" for i, s in enumerate(attempt_history)) +
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
    """Создает промпт для исправления ошибки, включая полную историю попыток."""
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
            + "\n---\n".join(f"**На итерации {i+1}:**\n{s}" for i, s in enumerate(attempt_history)) +
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


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def notify_user(message):
    print(f"{Colors.OKBLUE}📢 ЛОГ: Отправляю уведомление: {message.replace(Colors.ENDC, '')}{Colors.ENDC}")
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(['afplay', '/System/Library/Sounds/Sosumi.aiff'], check=True, timeout=5)
        elif system == "Linux":
            subprocess.run(['zenity', '--info', '--text', message, '--title', 'Sloth Script', '--timeout=10', '--window-icon=info'], check=True, timeout=10)
            subprocess.run(['aplay', '/usr/share/sounds/alsa/Front_Center.wav'], check=True)
        elif system == "Windows":
            command = f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show(\'{message}\', \'Sloth Script\');"'
            subprocess.run(command, shell=True, check=True, timeout=30)
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось отправить системное уведомление. Ошибка: {e}.{Colors.ENDC}")

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

def send_request_to_model(prompt_text, iteration_count):
    try:
        print(f"{Colors.CYAN}🧠 ЛОГ: Отправляю запрос в модель... Размер промпта: ~{len(prompt_text)} символов.{Colors.ENDC}")
        prompt_preview = re.sub(r'--- КОНТЕКСТ ПРОЕКТА.*---(.|\n|\r)*--- КОНЕЦ КОНТЕКСТА ---', '--- КОНТЕКСТ ПРОЕКТА (скрыт) ---', prompt_text, flags=re.DOTALL)
        prompt_preview = re.sub(r'--- СОДЕРЖИМОЕ ФАЙЛА.*---(.|\n|\r)*--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---', '--- СОДЕРЖИМОЕ ФАЙЛА (скрыто) ---', prompt_preview, flags=re.DOTALL)
        prompt_preview = re.sub(r'--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК.*---(.|\n|\r)*--- КОНЕЦ ИСТОРИИ ---', '--- ИСТОРИЯ ПРЕДЫДУЩИХ ПОПЫТОК (скрыта) ---', prompt_preview, flags=re.DOTALL)
        
        print(f"{Colors.OKBLUE}  [Детали] Итерация {iteration_count}. Структура отправляемого промпта:\n---\n{prompt_preview}\n---{Colors.ENDC}")
        
        response = model.generate_content(prompt_text)

        if not response.candidates or response.candidates[0].finish_reason.name != "STOP":
            reason = response.candidates[0].finish_reason.name if response.candidates else "Неизвестно"
            print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА: Ответ от модели не получен или был прерван. Причина: {reason}{Colors.ENDC}")
            return None
        return response.text
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА при запросе к API: {e}{Colors.ENDC}")
        return None

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


# --- ГЛАВНЫЙ ЦИКЛ ---
def main():
    """Основной рабочий цикл скрипта."""
    user_goal, error_log = get_user_input()
    
    if not user_goal:
        raise ValueError("Цель не может быть пустой.")
        
    initial_task = user_goal
    if error_log:
        initial_task += "\n\n--- ЛОГ ОШИБКИ ДЛЯ АНАЛИЗА ---\n" + error_log
    
    project_context = get_project_context()
    if not project_context: raise ConnectionError("Не удалось получить первоначальный контекст проекта.")
    
    current_prompt = get_initial_prompt(project_context, initial_task)
    attempt_history = []

    for iteration_count in range(1, MAX_ITERATIONS + 1):
        print(f"\n{Colors.BOLD}{Colors.HEADER}🚀 --- АВТОМАТИЧЕСКАЯ ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---{Colors.ENDC}")
        
        answer = send_request_to_model(current_prompt, iteration_count)
        if not answer: return "Ошибка: Не удалось получить ответ от модели."

        print(f"\n{Colors.OKGREEN}📦 ПОЛУЧЕН ОТВЕТ МОДЕЛИ:{Colors.ENDC}\n" + "="*20 + f"\n{answer}\n" + "="*20)

        if answer.strip().upper().startswith("ГОТОВО"):
            manual_steps = extract_manual_steps_block(answer)
            final_message = f"{Colors.OKGREEN}✅ Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
            if manual_steps:
                final_message += f"\n\n{Colors.WARNING}✋ ВАЖНО: Требуются следующие ручные действия:{Colors.ENDC}\n" + "-"*20 + f"\n{manual_steps}\n" + "-"*20
            return final_message

        commands_to_run = extract_todo_block(answer)
        if not commands_to_run:
            return f"{Colors.FAIL}Модель не предоставила блок команд и не считает задачу выполненной.{Colors.ENDC}"

        strategy_description = extract_summary_block(answer)
        if not strategy_description:
            strategy_description = f"Применена команда, начинающаяся с `{commands_to_run.splitlines()[0][:80]}...` (описание не предоставлено)"
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Модель не предоставила блок summary. Используется авто-описание.{Colors.ENDC}")
        else:
             print(f"{Colors.CYAN}💡 Стратегия ассистента: '{strategy_description}'{Colors.ENDC}")

        print(f"\n{Colors.OKBLUE}🔧 Найдены shell-команды для применения:{Colors.ENDC}\n" + "-"*20 + f"\n{commands_to_run}\n" + "-"*20)
        
        success, failed_command, error_message = apply_shell_commands(commands_to_run)
        
        project_context = get_project_context()
        if not project_context: return f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"

        if success:
            history_entry = (
                f"**Стратегия:** {strategy_description}\n"
                f"  **Результат:** УСПЕХ"
            )
            attempt_history.append(history_entry)
            print(f"\n{Colors.CYAN}🧐 ЛОГ: Команды успешно применены. Готовлюсь к верификации.{Colors.ENDC}")
            current_prompt = get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
        else:
            history_entry = (
                f"**Стратегия:** {strategy_description}\n"
                f"  **Результат:** ПРОВАЛ\n"
                f"  **Ошибка (stderr):** {error_message}"
            )
            attempt_history.append(history_entry)
            
            print(f"\n{Colors.FAIL}🆘 ЛОГ: Обнаружена ошибка. Готовлю промпт для исправления.{Colors.ENDC}")
            
            filepath = extract_filepath_from_command(failed_command or "")
            error_context = f"--- КОНТЕКСТ ПРОЕКТА ---\n{project_context}\n--- КОНЕЦ КОНТЕКСТА ---"
            if filepath and os.path.exists(filepath) and not os.path.isdir(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                    error_context = f"--- СОДЕРЖИМОЕ ФАЙЛА: {filepath} ---\n{file_content}\n--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---\n\n{error_context}"
                except Exception as e:
                    print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось прочитать файл '{filepath}' для контекста ошибки: {e}{Colors.ENDC}")

            current_prompt = get_error_fixing_prompt(
                failed_command=failed_command, error_message=error_message,
                goal=user_goal, context=error_context, iteration_count=iteration_count + 1, attempt_history=attempt_history)
            
    return f"{Colors.WARNING}⌛ Достигнут лимит в {MAX_ITERATIONS} итераций. Задача не была завершена.{Colors.ENDC}"

if __name__ == "__main__":
    final_status = "Работа завершена."
    try: final_status = main()
    except KeyboardInterrupt: final_status = f"{Colors.OKBLUE}🔵 Процесс прерван пользователем.{Colors.ENDC}"
    except Exception as e:
        print(f"\n{Colors.FAIL}❌ КРИТИЧЕСКАЯ НЕПЕРЕХВАЧЕННАЯ ОШИБКА: {e}{Colors.ENDC}")
        final_status = f"{Colors.FAIL}❌ Скрипт аварийно завершился с ошибкой: {e}{Colors.ENDC}"
    finally:
        print(f"\n{final_status}")
        notify_user(final_status)
        time.sleep(1) 
        print(f"\n{Colors.BOLD}🏁 Скрипт завершил работу.{Colors.ENDC}")