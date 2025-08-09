# Файл: sloth_cli.py
import os
import sys
import time
import re
import json
import platform
import subprocess
from colors import Colors
import sloth_core
import sloth_runner
import context_collector

# --- КОНСТАНТЫ ИНТЕРФЕЙСА ---
MAX_ITERATIONS = 15
CONTEXT_SCRIPT = 'AskGpt.py' # Оставим для обратной совместимости, если context_collector не сработает
CONTEXT_FILE = 'message_1.txt'
HISTORY_FILE = 'sloth_history.json'
RUN_LOG_FILE = 'sloth_run.log'

def calculate_cost(model_name, input_tokens, output_tokens):
    """
    Рассчитывает стоимость одного вызова API, учитывая многоуровневую тарификацию.
    """
    pricing_info = sloth_core.MODEL_PRICING.get(model_name)
    if not pricing_info:
        return 0.0

    total_cost = 0.0
    
    # Расчет стоимости для входных токенов
    input_tiers = pricing_info.get("input", {}).get("tiers", [])
    for tier in input_tiers:
        if input_tokens <= tier["up_to"]:
            total_cost += (tier["price"] / 1_000_000) * input_tokens
            break

    # Расчет стоимости для выходных токенов (цена зависит от размера ВХОДА)
    output_tiers = pricing_info.get("output", {}).get("tiers", [])
    for tier in output_tiers:
        if input_tokens <= tier["up_to"]: 
            total_cost += (tier["price"] / 1_000_000) * output_tokens
            break
            
    return total_cost

# --- УТИЛИТЫ ИНТЕРФЕЙСА ---

def get_project_context():
    """Собирает и возвращает контекст проекта, используя новый модуль."""
    print(f"{Colors.CYAN}🔄 ЛОГ: Обновляю контекст проекта...{Colors.ENDC}")
    try:
        # Используем новый, чистый способ
        context_data = context_collector.gather_project_context(os.getcwd())
        print(f"{Colors.OKGREEN}✅ ЛОГ: Контекст успешно обновлен. Размер: {len(context_data)} символов.{Colors.ENDC}")
        return context_data
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}{Colors.ENDC}")
        return None

def _log_run(title, content):
    """Пишет запись в файл запуска. Один файл на весь запуск, перезаписывается при старте."""
    try:
        with open(RUN_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write("\n" + "="*80 + "\n")
            f.write(f"{title}\n")
            f.write("-"*80 + "\n")
            if content is None:
                content = "<empty>"
            f.write(str(content) + "\n")
            f.write("="*80 + "\n")
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось записать в {RUN_LOG_FILE}: {e}{Colors.ENDC}")

def _read_multiline_input(prompt):
    """Читает многострочный ввод от пользователя."""
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
    """Получает цель и лог ошибки от пользователя."""
    goal_prompt = (
        f"{Colors.HEADER}{Colors.BOLD}👋 Привет! Опиши свою основную цель.{Colors.ENDC}\n"
        f"{Colors.CYAN}💡 Пожалуйста, будь максимально точен и детален.\n"
        f"(Для завершения ввода, нажми Enter 3 раза подряд){Colors.ENDC}"
    )
    user_goal = _read_multiline_input(goal_prompt)

    if not user_goal:
        return None, None

    log_prompt = f"\n{Colors.HEADER}{Colors.BOLD}👍 Отлично. Теперь, если есть лог ошибки, вставь его. Если нет, просто нажми Enter 3 раза.{Colors.ENDC}"
    error_log = _read_multiline_input(log_prompt)

    return user_goal, error_log

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

# --- ГЛАВНЫЙ УПРАВЛЯЮЩИЙ ЦИКЛ ---
def main(is_fix_mode=False):
    sloth_core.initialize_model()
    model_instance, active_service = sloth_core.get_active_service_details()

    if not model_instance:
        return f"{Colors.FAIL}Не удалось инициализировать модель. Выход.{Colors.ENDC}"

    total_cost = 0.0
    initial_phase_cost = 0.0
    fix_phase_cost = 0.0
    cost_log = []
    
    current_phase = "Fix" if is_fix_mode else "Initial"

    user_goal, error_log = get_user_input()
    if not user_goal:
        return f"{Colors.WARNING}Цель не была указана. Завершение работы.{Colors.ENDC}"
    
    initial_task = user_goal + (f"\n\n--- ЛОГ ОШИБКИ ---\n{error_log}" if error_log else "")
    project_context = get_project_context()
    if not project_context:
        return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить контекст проекта.{Colors.ENDC}"
    
    current_prompt = sloth_core.get_initial_prompt(project_context, initial_task, load_fix_history() if is_fix_mode else None)
    attempt_history = []
    final_message = ""
    
    iteration_count = 1
    while iteration_count <= MAX_ITERATIONS:
        model_instance, active_service = sloth_core.get_active_service_details()
        print(f"\n{Colors.BOLD}{Colors.HEADER}🚀 --- ЭТАП: {current_phase} | ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} (API: {active_service}) ---{Colors.ENDC}")

        # Логируем запрос перед отправкой
        _log_run(f"ИТЕРАЦИЯ {iteration_count}: ЗАПРОС В МОДЕЛЬ", current_prompt)
        answer_data = sloth_core.send_request_to_model(model_instance, active_service, current_prompt, iteration_count)
        if not answer_data:
            if sloth_core.model:
                print(f"{Colors.WARNING}🔄 ЛОГ: Ответ от модели не получен, пробую снова...{Colors.ENDC}")
                print(f"{Colors.WARNING}⏸️  ЛОГ: Пауза на 5 секунд перед повторной попыткой...{Colors.ENDC}")
                time.sleep(5)
                continue
            else:
                final_message = "Критическая ошибка: Не удалось получить ответ и нет запасного API."
                break
        
        iteration_cost = calculate_cost(sloth_core.MODEL_NAME, answer_data["input_tokens"], answer_data["output_tokens"])
        total_cost += iteration_cost
        if current_phase == "Fix": fix_phase_cost += iteration_cost
        else: initial_phase_cost += iteration_cost
        
        cost_log.append({
            "phase": current_phase, "iteration": iteration_count, "model": sloth_core.MODEL_NAME, 
            "cost": iteration_cost, "input": answer_data["input_tokens"], "output": answer_data["output_tokens"]
        })
        print(f"{Colors.GREY}📊 Статистика: Вход: {answer_data['input_tokens']} т., Выход: {answer_data['output_tokens']} т. Стоимость: ~${iteration_cost:.6f}{Colors.ENDC}")
        
        answer_text = answer_data["text"]
        # Логируем сырой ответ модели
        _log_run(f"ИТЕРАЦИЯ {iteration_count}: ОТВЕТ МОДЕЛИ (RAW)", answer_text)

        if answer_text.strip().upper().startswith("ГОТОВО"):
            done_summary = extract_done_summary_block(answer_text)
            manual_steps = extract_manual_steps_block(answer_text)
            final_message = f"{Colors.OKGREEN}✅ Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
            if done_summary:
                save_completion_history(user_goal, done_summary)
                print(f"{Colors.OKGREEN}📄 ИТОГОВОЕ РЕЗЮМЕ:\n{Colors.CYAN}{done_summary}{Colors.ENDC}")
                _log_run(f"ИТЕРАЦИЯ {iteration_count}: DONE SUMMARY", done_summary)
            if manual_steps:
                 final_message += f"\n\n{Colors.WARNING}✋ ТРЕБУЮТСЯ РУЧНЫЕ ДЕЙСТВИЯ:{Colors.ENDC}\n{manual_steps}"
                 _log_run(f"ИТЕРАЦИЯ {iteration_count}: MANUAL STEPS", manual_steps)
            break

        commands_to_run = extract_todo_block(answer_text)
        if not commands_to_run:
            print(f"{Colors.FAIL}❌ ЛОГ: Модель вернула ответ без команд. Пробую на следующей итерации.{Colors.ENDC}")
            current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
            iteration_count += 1
            continue

        strategy_description = extract_summary_block(answer_text) or "Стратегия не описана."
        # Логируем найденные команды и стратегию в файл запуска
        _log_run(f"ИТЕРАЦИЯ {iteration_count}: СТРАТЕГИЯ", strategy_description)
        _log_run(f"ИТЕРАЦИЯ {iteration_count}: КОМАНДЫ К ВЫПОЛНЕНИЮ (bash)", commands_to_run)
        # Не засоряем консоль самими командами
        print(f"\n{Colors.OKBLUE}🔧 Найден блок shell-команд. Пытаюсь выполнить...{Colors.ENDC}")

        success, failed_command, error_message = sloth_runner.execute_commands(commands_to_run)
        # Логируем результат выполнения команд
        if success:
            _log_run(f"ИТЕРАЦИЯ {iteration_count}: РЕЗУЛЬТАТ ВЫПОЛНЕНИЯ КОМАНД", "УСПЕХ")
        else:
            _log_run(f"ИТЕРАЦИЯ {iteration_count}: РЕЗУЛЬТАТ ВЫПОЛНЕНИЯ КОМАНД", f"ПРОВАЛ\nОшибка: {error_message}\nПровалившийся блок:\n{failed_command}")
        
        project_context = get_project_context()
        if not project_context: 
            final_message = f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"
            break

        history_entry = f"**Итерация {iteration_count}:**\n**Стратегия:** {strategy_description}\n"
        if success:
            history_entry += "**Результат:** УСПЕХ"
            current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
        else:
            history_entry += f"**Результат:** ПРОВАЛ\n**Ошибка:** {error_message}"
            current_prompt = sloth_core.get_error_fixing_prompt(failed_command, error_message, user_goal, project_context, iteration_count + 1, attempt_history)
        
        attempt_history.append(history_entry)
        iteration_count += 1
    
    if not final_message:
        final_message = f"{Colors.WARNING}⌛ Достигнут лимит в {MAX_ITERATIONS} итераций. Задача не была завершена.{Colors.ENDC}"
    
    print(f"\n{Colors.BOLD}{Colors.HEADER}--- ИТОГОВЫЙ ОТЧЕТ ПО СТОИМОСТИ ---{Colors.ENDC}")
    for entry in cost_log:
        print(f"  Фаза: {entry['phase']:<8} | Итерация: {entry['iteration']:<2} | Модель: {entry['model']:<20} | Стоимость: ${entry['cost']:.6f}")
    
    if fix_phase_cost > 0:
        print(f"\n  Стоимость начального этапа: ${initial_phase_cost:.6f}")
        print(f"  Стоимость этапа исправлений: ${fix_phase_cost:.6f}")
    
    print(f"{Colors.BOLD}\n  Общая стоимость задачи: ${total_cost:.6f}{Colors.ENDC}")

    return final_message

if __name__ == "__main__":
    is_fix_mode = '--fix' in sys.argv
    
    if not is_fix_mode and os.path.exists(HISTORY_FILE):
        try: 
            os.remove(HISTORY_FILE)
            print(f"{Colors.CYAN}🗑️  ЛОГ: Очищена старая история ({HISTORY_FILE}).{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось удалить файл истории: {e}{Colors.ENDC}")
    
    # Перезаписываем файл лога запуска
    try:
        with open(RUN_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("# SLOTH RUN LOG\n")
            f.write(f"Платформа: {platform.system()} | Python: {platform.python_version()}\n")
            f.write("Этот файл перезаписывается при каждом запуске.\n")
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось инициализировать {RUN_LOG_FILE}: {e}{Colors.ENDC}")
    
    final_status = "Работа завершена."
    try:
        final_status = main(is_fix_mode)
    except KeyboardInterrupt:
        final_status = f"{Colors.OKBLUE}🔵 Процесс прерван пользователем.{Colors.ENDC}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        final_status = f"{Colors.FAIL}❌ Скрипт аварийно завершился: {e}{Colors.ENDC}"
    finally:
        print(f"\n{final_status}")
        notify_user(final_status)
        print(f"\n{Colors.BOLD}🏁 Скрипт завершил работу.{Colors.ENDC}")