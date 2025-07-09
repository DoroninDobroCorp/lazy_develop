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
API_TIMEOUT_SECONDS = 600 # Этот параметр больше не используется в вызове API, но оставлен для справки

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
    *   **Точечные правки предпочтительнее:** Для больших файлов старайся использовать `sed` для точечных замен, вставок или удалений строк. Это безопаснее.
    *   **Полная перезапись:** Если точечная правка невозможна или слишком сложна, можно использовать `cat <<'EOF' > path/to/file.txt ... EOF` для полной перезаписи. **В этом случае будь предельно аккуратен, чтобы не удалить случайно другие части файла и сохранить исходное форматирование.**
    *   **ЗАЩИТА ОТ ПОТЕРИ ДАННЫХ (Критически важно!):** Если файл, который ты хочешь изменить, содержит **более 150 строк**, тебе **СТРОГО ЗАПРЕЩЕНО** переписывать его целиком через `cat <<'EOF' > ...`. Для таких файлов ты **ОБЯЗАН** использовать только точечные команды (`sed`) для внесения правок. Это ключевая мера безопасности для предотвращения потери данных.

2.  **ФОРМАТ ОТВЕТА — ЭТО ЗАКОН:**
    *   **Действия:** Если нужны правки, предоставь **только** блок команд, обернутый в ```bash ... ```. Никаких комментариев вне блока.
    *   **Завершение:**
        *   Если задача полностью решена и **не требует ручных действий от человека**, напиши **только** одно слово: `ГОТОВО`.
        *   Если после твоих правок **человеку нужно выполнить команды** (например, `npx`, `prisma`), сначала напиши `ГОТОВО`, а затем добавь блок ```manual ... ``` с инструкциями.

    **Пример ответа с ручными шагами:**
    ```
    ГОТОВО

    ```manual
    # Я внес все необходимые правки в код.
    # Теперь, пожалуйста, выполни эти команды, чтобы завершить настройку:
    npx prisma generate
    npx prisma db push
    ```
    ```

3.  **ФОКУС НА ЗАДАЧЕ:** Концентрируйся строго на выполнении исходной **цели**. Не предлагай исправления для проблем, которые уже решены в предыдущих итерациях. Каждый раз анализируй код заново.

4.  **РАЗРЕШЕННЫЕ КОМАНДЫ:** `{', '.join(ALLOWED_COMMANDS)}`. Команды, не входящие в этот список, должны быть помещены в блок ```manual```.

5.  **СОХРАНЯЙ КОНТЕКСТ:** **Критически важно!** Не вноси изменения в код, не относящиеся напрямую к поставленной задаче. Не исправляй стиль, не делай рефакторинг и не меняй настройки, если это не является причиной исходной ошибки или частью цели. Безопасность и лучшие практики — ответственность пользователя, если они не мешают выполнению задачи.
"""

def get_initial_prompt(context, task):
    """Создает первоначальный промпт для старта работы (с возможным логом ошибки)."""
    return f"{get_command_rules()}\n--- КОНТЕКСТ ПРОЕКТА ---\n{context}\n--- КОНЕЦ КОНТЕКСТА ---\nЗадача: {task}\nПроанализируй задачу и предоставь ответ, строго следуя правилам."

def get_review_prompt(context, goal):
    """
    Создает промпт для верификации. **ВАЖНО: использует только чистую цель, без логов.**
    """
    return f"""{get_command_rules()}
**ВАЖНО:** Предыдущий шаг выполнен. Код ниже — это **обновленное состояние** проекта. Лог ошибки, который, возможно, был в начале, **БОЛЬШЕ НЕ АКТУАЛЕН**.

**Твоя задача — ВЕРИФИКАЦИЯ:**
1.  Забудь про старые логи. Проанализируй **текущий** код.
2.  Сравни его с **изначальной целью**.
3.  Если цель достигнута, используй формат `ГОТОВО` (с опциональным блоком `manual`).
4.  Если нет, предоставь следующий блок команд для исправления.

--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---

Напоминаю ИСХОДНУЮ ЦЕЛЬ: {goal}
"""

def get_error_fixing_prompt(failed_command, error_message, goal, context):
    """Создает промпт для исправления ошибки выполнения команды."""
    return f"""{get_command_rules()}
**ВАЖНО:** Твоя задача — исправить ошибку выполнения команды. Не пиши 'ГОТОВО'.

--- ДАННЫЕ ОБ ОШИБКЕ ---
КОМАНДА: {failed_command}
СООБЩЕНИЕ: {error_message}
--- КОНЕЦ ДАННЫХ ОБ ОШИБКЕ ---

Исходная ЦЕЛЬ была: {goal}

Проанализируй ошибку и предоставь **исправленный блок команд**.

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
            # Всплывающее окно на Ubuntu
            subprocess.run(['zenity', '--info', '--text', message, '--title', 'Sloth Script', '--timeout=10', '--window-icon=info'], check=True, timeout=10)
            # Звук через aplay (или другой аудиопроигрыватель)
            subprocess.run(['aplay', '/usr/share/sounds/alsa/Front_Center.wav'], check=True)
        elif system == "Windows":
            # Всплывающее окно на Windows
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

def extract_manual_steps_block(text):
    """Извлекает опциональный блок с инструкциями для ручного выполнения."""
    match = re.search(r"```manual\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

def apply_shell_commands(commands_str):
    print(f"{Colors.OKBLUE}  [Детали] Вход в apply_shell_commands().{Colors.ENDC}")
    try:
        is_macos = platform.system() == "Darwin"
        commands_str_adapted = re.sub(r"sed -i ", "sed -i '.bak' ", commands_str) if is_macos else commands_str
            
        print(f"{Colors.WARNING}⚡️ ЛОГ: Выполняю блок команд:\n---\n{commands_str_adapted}\n---{Colors.ENDC}")
        result = subprocess.run(['bash', '-c', commands_str_adapted], check=True, capture_output=True, text=True, encoding='utf-8')

        if result.stdout: print(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr: print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ (STDERR):\n{result.stderr.strip()}{Colors.ENDC}")
        
        if is_macos: subprocess.run("find . -name '*.bak' -delete", shell=True, check=True)

        print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен.{Colors.ENDC}")
        return True, None, None
    except subprocess.CalledProcessError as e:
        error_msg = f"Команда: 'bash -c \"...\"'\nОшибка: {e.stderr.strip()}"
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА при выполнении блока команд.\n{error_msg}{Colors.ENDC}")
        return False, commands_str, e.stderr.strip()
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

def send_request_to_model(prompt_text):
    try:
        print(f"{Colors.CYAN}🧠 ЛОГ: Отправляю запрос в модель... Размер промпта: ~{len(prompt_text)} символов.{Colors.ENDC}")
        prompt_preview = re.sub(r'--- КОНТЕКСТ ПРОЕКТА.*---(.|\n|\r)*--- КОНЕЦ КОНТЕКСТА ---', '--- КОНТЕКСТ ПРОЕКТА (скрыт) ---', prompt_text, flags=re.DOTALL)
        prompt_preview = re.sub(r'--- СОДЕРЖИМОЕ ФАЙЛА.*---(.|\n|\r)*--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---', '--- СОДЕРЖИМОЕ ФАЙЛА (скрыто) ---', prompt_preview, flags=re.DOTALL)
        print(f"{Colors.OKBLUE}  [Детали] Структура отправляемого промпта:\n---\n{prompt_preview}\n---{Colors.ENDC}")
        
        ### ИЗМЕНЕНИЕ 1: Удаление request_options из вызова ###
        # API Vertex AI не принимает этот аргумент в `generate_content`.
        response = model.generate_content(prompt_text)
        ### КОНЕЦ ИЗМЕНЕНИЯ 1 ###

        if not response.candidates or response.candidates[0].finish_reason.name != "STOP":
            reason = response.candidates[0].finish_reason.name if response.candidates else "Неизвестно"
            print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА: Ответ от модели не получен или был прерван. Причина: {reason}{Colors.ENDC}")
            return None
        return response.text
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА при запросе к API: {e}{Colors.ENDC}")
        return None

def _read_multiline_input(prompt):
    """Вспомогательная функция для чтения многострочного ввода до 3-х пустых строк."""
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
    """Интерактивный ввод цели и опционального лога ошибки."""
    goal_prompt = f"{Colors.HEADER}{Colors.BOLD}👋 Привет! Опиши свою основную цель. (Для завершения ввода, нажми Enter 3 раза подряд){Colors.ENDC}"
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

    for iteration_count in range(1, MAX_ITERATIONS + 1):
        print(f"\n{Colors.BOLD}{Colors.HEADER}🚀 --- АВТОМАТИЧЕСКАЯ ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---{Colors.ENDC}")
        
        answer = send_request_to_model(current_prompt)
        if not answer: return "Ошибка: Не удалось получить ответ от модели."

        print(f"\n{Colors.OKGREEN}📦 ПОЛУЧЕН ОТВЕТ МОДЕЛИ:{Colors.ENDC}\n" + "="*20 + f"\n{answer}\n" + "="*20)

        if answer.strip().upper().startswith("ГОТОВО"):
            manual_steps = extract_manual_steps_block(answer)
            final_message = f"{Colors.OKGREEN}✅ Задача выполнена успешно!{Colors.ENDC}"
            
            if manual_steps:
                final_message += f"\n\n{Colors.WARNING}✋ ВАЖНО: Требуются следующие ручные действия:{Colors.ENDC}\n" + "-"*20 + f"\n{manual_steps}\n" + "-"*20
                
            return final_message

        commands_to_run = extract_todo_block(answer)
        if not commands_to_run:
            return f"{Colors.FAIL}Модель не предоставила блок команд и не считает задачу выполненной.{Colors.ENDC}"

        print(f"\n{Colors.OKBLUE}🔧 Найдены shell-команды для применения:{Colors.ENDC}\n" + "-"*20 + f"\n{commands_to_run}\n" + "-"*20)
        
        success, failed_command, error_message = apply_shell_commands(commands_to_run)
        
        project_context = get_project_context()
        if not project_context: return f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"

        if success:
            print(f"\n{Colors.CYAN}🧐 ЛОГ: Команды успешно применены. Готовлюсь к верификации.{Colors.ENDC}")
            current_prompt = get_review_prompt(project_context, user_goal)
        else:
            print(f"\n{Colors.FAIL}🆘 ЛОГ: Обнаружена ошибка. Готовлю промпт для исправления.{Colors.ENDC}")
            filepath = extract_filepath_from_command(failed_command)
            
            error_context = f"--- КОНТЕКСТ ПРОЕКТА ---\n{project_context}\n--- КОНЕЦ КОНТЕКСТА ---"
            if filepath and os.path.exists(filepath) and not os.path.isdir(filepath):
                with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                error_context = f"--- СОДЕРЖИМОЕ ФАЙЛА: {filepath} ---\n{file_content}\n--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---\n\n{error_context}"
            
            current_prompt = get_error_fixing_prompt(
                failed_command=failed_command, error_message=error_message,
                goal=user_goal, context=error_context)
            
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