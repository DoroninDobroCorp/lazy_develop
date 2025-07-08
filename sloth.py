# -*- coding: utf-8 -*-

import google.generativeai as genai
import os
import subprocess
import time
import re
import platform

# --- НАСТРОЙКИ ---
API_KEY = 'REDACTED_GOOGLE_API_KEY'
CONTEXT_SCRIPT = 'AskGpt.py'
CONTEXT_FILE = 'message_1.txt'
MODEL_NAME = "gemini-2.5-pro"
ALLOWED_COMMANDS = (
    "sed", "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./", "cat"
)
MAX_ITERATIONS = 15
API_TIMEOUT_SECONDS = 600

# --- КОНФИГУРАЦИЯ МОДЕЛИ ---
print(f"ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}")
try:
    genai.configure(api_key=API_KEY)
    print("ЛОГ: API сконфигурировано успешно.")
except Exception as e:
    print(f"ЛОГ: ОШИБКА конфигурации API: {e}")
    exit()

generation_config = { "temperature": 1, "top_p": 1, "top_k": 1, "max_output_tokens": 32768 }
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=generation_config, safety_settings=safety_settings)
print(f"ЛОГ: Модель '{MODEL_NAME}' создана.")

# --- БЛОК ПРОМПТ-ШАБЛОНОВ ---

def get_command_rules():
    return f"""
Ты — AI-ассистент, работающий в составе автоматизированной системы. Чтобы наше взаимодействие было успешным, пожалуйста, придерживайся следующих ключевых принципов:

1.  **Формат ответа — это критически важно.** Твой ответ должен строго соответствовать одной из двух структур:
    *   **Если нужны действия:** Предоставь **только** блок команд, обернутый в ```bash ... ```. Пожалуйста, не добавляй никакого сопроводительного текста или комментариев вне этого блока.
    *   **Если задача решена:** Предоставь **только** одно слово: `ГОТОВО`.

2.  **Сложные задачи.** Для задач, требующих сложной логики (например, запись большого файла с помощью `cat <<'EOF'`), используй `bash`. Скрипт-исполнитель корректно обработает многострочные команды внутри ```bash ... ``` блока.

3.  **Разрешенные команды.** `{', '.join(ALLOWED_COMMANDS)}`. Если нужна другая команда, предложи ее в блоке `СОВЕТЫ:` после слова `ГОТОВО` в финальном ответе.
"""

def get_initial_prompt(context, task):
    return f"""{get_command_rules()}
--- КОНТЕКСТ ПРОЕКТА ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
Задача: {task}
Проанализируй задачу и предоставь ответ, строго следуя изложенным выше принципам.
"""

def get_review_prompt(context, task):
    return f"""{get_command_rules()}
Команды были выполнены. Вот обновленный проект:
--- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЕННЫЙ) ---
{context}
--- КОНЕЦ КОНТЕКСТА ---
Первоначальная задача: {task}
Задача решена? Если нет — дай новые команды. Если да — напиши "ГОТОВО".
"""

def get_error_fixing_prompt(failed_command, error_message, task, context):
    return f"""
Ты — AI-ассистент для исправления ошибок. Твой ответ должен содержать **только** блок ```bash ... ``` с исправленной командой(ами). Пожалуйста, не пиши 'ГОТОВО' или объяснения.

--- ДАННЫЕ ОБ ОШИБКЕ ---
КОМАНДА: {failed_command}
СООБЩЕНИЕ: {error_message}
--- КОНЕЦ ДАННЫХ ОБ ОШИБКЕ ---
Задача: {task}
Проанализируй ошибку и предоставь исправленные команды.
--- КОНТЕКСТ, ГДЕ ПРОИЗОШЛА ОШИБКА ---
{context}
--- КОНЕЦ КОНТЕКСТА ---"""


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def notify_user(message):
    """Отправляет видное и/или слышимое уведомление пользователю. Более надежная версия."""
    print(f"ЛОГ: Отправляю уведомление: {message}")
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            # Атомарная команда, которая показывает уведомление и проигрывает стандартный звук
            script = f'display notification "{message}" with title "Sloth Script" sound name "Submarine"'
            subprocess.run(['osascript', '-e', script], check=True, timeout=10)
        elif system == "Linux":
            subprocess.run(['notify-send', 'Sloth Script', message], check=True, timeout=10)
        elif system == "Windows":
            command = f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show(\'{message}\', \'Sloth Script\');"'
            subprocess.run(command, shell=True, check=True, timeout=30)
    except Exception as e:
        print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось отправить основное уведомление. Ошибка: {e}. Пробую резервный звуковой метод.")
        try: # Резервный звуковой метод
             if system == "Darwin":
                subprocess.run(['say', message], check=True, timeout=10)
             elif system == "Linux":
                subprocess.run(['spd-say', '-t', 'female1', message], check=True, timeout=10)
        except Exception as e2:
             print(f"ПРЕДУПРЕЖДЕНИЕ: Резервное звуковое уведомление тоже не сработало. Ошибка: {e2}")

def get_project_context():
    # ... (код функции без изменений)
    print("ЛОГ: Обновляю контекст проекта...")
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_to_run_path = os.path.join(script_dir, CONTEXT_SCRIPT)
        context_file_path = os.path.join(script_dir, CONTEXT_FILE)
        if os.path.exists(context_file_path):
            os.remove(context_file_path)
        subprocess.run(['python3', script_to_run_path], check=True, capture_output=True, text=True, encoding='utf-8')
        with open(context_file_path, 'r', encoding='utf-8') as f:
            context_data = f.read()
        print(f"ЛОГ: Контекст успешно обновлен. Размер: {len(context_data)} символов.")
        return context_data
    except Exception as e:
        print(f"ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}")
        return None

def extract_todo_block(text):
    # ... (код функции без изменений)
    match = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    if match: return match.group(1).strip()
    return None

def apply_shell_commands(commands_str):
    # ... (код функции без изменений)
    print("ЛОГ: Вход в функцию apply_shell_commands().")
    try:
        is_macos = platform.system() == "Darwin"
        if is_macos:
            commands_str_adapted = re.sub(r"sed -i ", "sed -i '.bak' ", commands_str)
        else:
            commands_str_adapted = commands_str
        print(f"ЛОГ: Выполняю блок команд:\n---\n{commands_str_adapted}\n---")
        result = subprocess.run(['bash', '-c', commands_str_adapted], check=True, capture_output=True, text=True, encoding='utf-8')
        if result.stdout: print(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr: print(f"ПРЕДУПРЕЖДЕНИЕ (STDERR):\n{result.stderr.strip()}")
        if is_macos:
            print("ЛОГ: Очищаю временные .bak файлы на macOS...")
            subprocess.run("find . -name '*.bak' -delete", shell=True)
        print("ЛОГ: Блок команд успешно выполнен.")
        return True, None, None
    except subprocess.CalledProcessError as e:
        error_msg = f"Команда: 'bash -c \"...\"'\nОшибка: {e.stderr.strip()}"
        print(f"ЛОГ: КРИТИЧЕСКАЯ ОШИБКА при выполнении блока команд.\n{error_msg}")
        return False, commands_str, e.stderr.strip()
    except Exception as e:
        print(f"ЛОГ: Непредвиденная ОШИБКА в apply_shell_commands: {e}")
        return False, commands_str, str(e)

def extract_filepath_from_command(command):
    # ... (код функции без изменений)
    parts = command.split()
    for part in reversed(parts):
        if '/' in part or '.' in part:
            if part in ['-c', '-e', '<<']: continue
            clean_part = part.strip("'\"")
            if os.path.exists(clean_part):
                return clean_part
    return None

def send_request_to_model(prompt_text):
    # ... (код функции без изменений)
    try:
        print(f"ЛОГ: Отправляю запрос в модель... Размер промпта: ~{len(prompt_text)} символов.")
        prompt_preview = re.sub(r'--- КОНТЕКСТ ПРОЕКТА.*---(.|\n|\r)*--- КОНЕЦ КОНТЕКСТА ---', '--- КОНТЕКСТ ПРОЕКТА (скрыт) ---', prompt_text)
        prompt_preview = re.sub(r'--- СОДЕРЖИМОЕ ФАЙЛА.*---(.|\n|\r)*--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---', '--- СОДЕРЖИМОЕ ФАЙЛА (скрыто) ---', prompt_preview)
        print(f"ЛОГ: Структура отправляемого промпта:\n---\n{prompt_preview}\n---")
        response = model.generate_content(prompt_text, request_options={'timeout': API_TIMEOUT_SECONDS})
        if not response.candidates or response.candidates[0].finish_reason.name != "STOP":
            reason = response.candidates[0].finish_reason.name if response.candidates else "Неизвестно"
            print(f"ЛОГ: ОШИБКА: Ответ от модели не получен или был прерван. Причина: {reason}")
            return None
        return response.text
    except Exception as e:
        print(f"ЛОГ: ОШИБКА при запросе к API: {e}")
        return None

# --- ГЛАВНЫЙ ЦИКЛ ---

def main():
    print("ЛОГ: Вход в функцию main().")
    print("Привет, друже! Опиши задачу (для завершения ввода, нажми Enter на пустой строке):")
    lines = []
    while True:
        line = input()
        if line: lines.append(line)
        else: break
    initial_task = '\n'.join(lines)
    if not initial_task:
        raise ValueError("Задача не может быть пустой.")

    project_context = get_project_context()
    if not project_context:
        raise ConnectionError("Не удалось получить контекст проекта.")

    current_prompt = get_initial_prompt(project_context, initial_task)

    for iteration_count in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- АВТОМАТИЧЕСКАЯ ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---")
        
        answer = send_request_to_model(current_prompt)
        if not answer: return "Ошибка при запросе к модели."

        print("\nПОЛУЧЕН ОТВЕТ МОДЕЛИ:\n" + "="*20 + f"\n{answer}\n" + "="*20)

        if "ГОТОВО" in answer.upper():
            return "Задача выполнена успешно!"

        commands_to_run = extract_todo_block(answer)
        if not commands_to_run:
            if "ГОТОВО" in answer.upper():
                 return "Задача выполнена успешно!"
            else:
                return "Модель не предоставила блок команд и не считает задачу выполненной."

        print("\nНайдены следующие shell-команды для автоматического применения:\n" + "-"*20 + f"\n{commands_to_run}\n" + "-"*20)
        
        success, failed_command, error_message = apply_shell_commands(commands_to_run)
        
        if success:
            print("\nЛОГ: Команды успешно применены. Обновляю контекст для полной верификации.")
            project_context = get_project_context()
            if not project_context: return "Не удалось обновить контекст после успешного применения команд."
            current_prompt = get_review_prompt(project_context, initial_task)
        else:
            print("\nЛОГ: Обнаружена ошибка. Запускаю цикл исправления.")
            filepath = extract_filepath_from_command(failed_command)
            
            error_context = ""
            if filepath and os.path.exists(filepath) and not os.path.isdir(filepath):
                print(f"ЛОГ: Ошибка в файле '{filepath}'. Готовлю сфокусированный промпт.")
                with open(filepath, 'r', encoding='utf-8') as f: file_content = f.read()
                error_context = f"--- СОДЕРЖИМОЕ ФАЙЛА: {filepath} ---\n{file_content}\n--- КОНЕЦ СОДЕРЖИМОГО ФАЙЛА ---"
            else:
                print(f"ЛОГ: Не удалось определить файл (найдено: {filepath}). Использую запасной план: полный контекст.")
                error_context = f"--- КОНТЕКСТ ПРОЕКТА ---\n{project_context}\n--- КОНЕЦ КОНТЕКСТА ---"

            current_prompt = get_error_fixing_prompt(
                failed_command=failed_command, error_message=error_message,
                task=initial_task, context=error_context)
            
            continue
            
    return f"Достигнут лимит в {MAX_ITERATIONS} итераций."

if __name__ == "__main__":
    final_status = "Работа завершена."
    try:
        final_status = main()
    except Exception as e:
        print(f"\nКРИТИЧЕСКАЯ НЕПЕРЕХВАЧЕННАЯ ОШИБКА: {e}")
        final_status = f"Скрипт аварийно завершился с ошибкой: {e}"
    finally:
        print(f"\n{final_status}")
        notify_user(final_status)
        time.sleep(1) 
        print("\nСкрипт завершил работу.")