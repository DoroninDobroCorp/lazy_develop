# Файл: sloth_cli.py
import os
import sys
import time
import re
import json
import platform
import subprocess
import argparse
from tkinter import Tk, filedialog

from colors import Colors, Symbols
import sloth_core
import sloth_runner
import context_collector

# --- КОНСТАНТЫ ИНТЕРФЕЙСА ---
MAX_ITERATIONS = 20
HISTORY_FILE_NAME = 'sloth_history.json'
RUN_LOG_FILE_NAME = 'sloth_run.log'

def calculate_cost(model_name, input_tokens, output_tokens):
    pricing_info = sloth_core.MODEL_PRICING.get(model_name)
    if not pricing_info:
        return 0.0
    total_cost = 0.0
    input_tiers = pricing_info.get("input", {}).get("tiers", [])
    for tier in input_tiers:
        if input_tokens <= tier["up_to"]:
            total_cost += (tier["price"] / 1_000_000) * input_tokens
            break
    output_tiers = pricing_info.get("output", {}).get("tiers", [])
    for tier in output_tiers:
        if output_tokens <= tier["up_to"]:
            total_cost += (tier["price"] / 1_000_000) * output_tokens
            break
    return total_cost

def get_project_context(is_fast_mode, files_to_include_fully=None):
    print(f"{Colors.CYAN}{Symbols.SPINNER} ЛОГ: Обновляю контекст проекта...{Colors.ENDC}")
    try:
        if is_fast_mode:
            context_data = context_collector.gather_project_context(os.getcwd(), mode='full')
        else:
            mode = 'summarized'
            if files_to_include_fully:
                print(f"{Colors.GREY}{Symbols.INFO}  Полное содержимое файлов: {len(files_to_include_fully)} шт.{Colors.ENDC}")
            context_data = context_collector.gather_project_context(
                os.getcwd(), mode=mode, full_content_files=files_to_include_fully
            )
        print(f"{Colors.OKGREEN}{Symbols.CHECK} ЛОГ: Контекст успешно обновлен. Размер: {len(context_data)} символов.{Colors.ENDC}")
        return context_data
    except Exception as e:
        print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}{Colors.ENDC}")
        return None

def _log_run(log_file_path, title, content):
    try:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "="*80 + "\n" + f"{title}\n" + "-"*80 + "\n")
            f.write(str(content if content is not None else "<empty>") + "\n")
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось записать в {log_file_path}: {e}{Colors.ENDC}")

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
    goal_prompt = (f"{Colors.HEADER}{Colors.BOLD} Привет! Опиши свою основную цель.{Colors.ENDC}\n"
                   f"{Colors.CYAN}{Symbols.INFO} (Для завершения ввода, нажми Enter 3 раза подряд){Colors.ENDC}")
    user_goal = _read_multiline_input(goal_prompt)
    if not user_goal:
        return None, None
    log_prompt = (f"\n{Colors.HEADER}{Colors.BOLD} Отлично. Теперь, если есть лог ошибки, вставь его. Если нет, просто нажми Enter 3 раза.{Colors.ENDC}")
    error_log = _read_multiline_input(log_prompt)
    return user_goal, error_log

def extract_block(tag, text):
    """Извлекает первый блок вида ```{tag}\n...\n```."""
    lines = text.splitlines()
    start_idx = None
    fence_prefix = f"```{tag}"
    for i, line in enumerate(lines):
        if line.strip().startswith(fence_prefix):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    for j in range(start_idx, len(lines)):
        if lines[j].strip() == "```":
            content = "\n".join(lines[start_idx:j])
            return content.strip()
    return None

def _iter_write_file_blocks(text):
    """
    НАДЁЖНЫЙ разбор всех блоков ```write_file path\n... \n```.
    Важно: не обрезаем содержимое и поддерживаем несколько блоков подряд.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```write_file"):
            # Форматы:
            # ```write_file path/to/file.ext
            # <контент>
            # ```
            parts = stripped.split(None, 1)
            filepath = ""
            if len(parts) > 1:
                filepath = parts[1].strip()
            i += 1
            start = i
            content_lines = []
            while i < len(lines) and lines[i].strip() != "```":
                content_lines.append(lines[i])
                i += 1
            yield filepath, "\n".join(content_lines)
            # пропускаем закрывающую ```
            if i < len(lines) and lines[i].strip() == "```":
                i += 1
            continue
        i += 1

def update_history_with_attempt(history_file_path, goal, summary):
    try:
        with open(history_file_path, 'r+', encoding='utf-8') as f:
            history_data = json.load(f)
            new_entry = {"initial_goal": goal, "solution_summary": summary}
            history_data.setdefault("previous_attempts", []).insert(0, new_entry)
            f.seek(0)
            json.dump(history_data, f, indent=2, ensure_ascii=False)
            f.truncate()
        print(f"{Colors.OKGREEN}💾 ЛОГ: История решения обновлена в {history_file_path}.{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось обновить историю решения: {e}{Colors.ENDC}")

def load_fix_history(history_file_path):
    if not os.path.exists(history_file_path):
        return None
    try:
        with open(history_file_path, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
        attempts = history_data.get("previous_attempts", [])
        if not attempts:
            return None
        last_attempt = attempts[0]
        return (f"Это твоя самая последняя попытка решения, которая оказалась неверной:\n"
                f"  - Поставленная задача: {last_attempt.get('initial_goal', 'N/A')}\n"
                f"  - Твое 'решение': {last_attempt.get('solution_summary', 'N/A')}")
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось загрузить или прочитать файл истории {history_file_path}: {e}{Colors.ENDC}")
        return None

def notify_user(message):
    clean_message = re.sub(r'\033\[.*?m', '', message)
    print(f"{Colors.OKBLUE}📢 ЛОГ: Отправляю итоговое уведомление...{Colors.ENDC}")
    print(message)

def cost_report(cost_log, total_cost):
    print(f"\n{Colors.BOLD}{Colors.HEADER}--- ИТОГОВЫЙ ОТЧЕТ ПО СТОИМОСТИ ---{Colors.ENDC}")
    for entry in cost_log:
        phase, cost = entry['phase'], entry['cost']
        if phase == 'PLANNING':
            print(f"  Фаза: {phase:<12} | Стоимость: ${cost:.6f}")
        else:
            iteration = entry['iteration']
            print(f"  Фаза: {phase:<12} | Итерация: {iteration:<2} | Стоимость: ${cost:.6f}")
    print(f"{Colors.BOLD}\n  Общая стоимость задачи: ${total_cost:.6f}{Colors.ENDC}")

def main(is_fix_mode, is_fast_mode, history_file_path, run_log_file_path):
    # Модель инициализируется в точке входа до вызова этой функции.
    model_instance, active_service = sloth_core.get_active_service_details()
    if not model_instance:
        # Этот проверка - мера предосторожности, основная точка входа уже должна была это проверить.
        return f"{Colors.FAIL}Не удалось получить данные об инициализированной модели. Выход.{Colors.ENDC}"

    total_cost, cost_log = 0.0, []
    user_goal, error_log = get_user_input()
    if not user_goal:
        return f"{Colors.WARNING}Цель не была указана. Завершение работы.{Colors.ENDC}"
    initial_task = user_goal + (f"\n\n--- ЛОГ ОШИБКИ ---\n{error_log}" if error_log else "")
    
    attempt_history, final_message = [], ""
    state = "EXECUTION" if is_fast_mode else "PLANNING"
    iteration_count, files_to_include_fully, current_prompt = 1, None, None

    while iteration_count <= MAX_ITERATIONS:
        model_instance, active_service = sloth_core.get_active_service_details()

        if state == "PLANNING":
            print(f"\n{Colors.BOLD}{Colors.HEADER}--- ЭТАП: ПЛАНИРОВАНИЕ ---{Colors.ENDC}")
            project_context = get_project_context(is_fast_mode=False, files_to_include_fully=None)
            if not project_context:
                return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить контекст проекта.{Colors.ENDC}"
            current_prompt = sloth_core.get_clarification_and_planning_prompt(project_context, initial_task)
        
        elif state == "EXECUTION" and current_prompt is None:
            project_context = get_project_context(is_fast_mode, files_to_include_fully)
            if not project_context:
                return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось обновить контекст.{Colors.ENDC}"
            current_prompt = sloth_core.get_initial_prompt(
                project_context, initial_task,
                sloth_core.get_active_service_details() and (load_fix_history(history_file_path) if is_fix_mode else None)
            )
            
        log_iter = iteration_count if state == "EXECUTION" else 0
        if state == "EXECUTION":
            print(f"\n{Colors.BOLD}{Colors.HEADER}{Symbols.ROCKET} --- ЭТАП: ИСПОЛНЕНИЕ | ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---{Colors.ENDC}")
        
        _log_run(run_log_file_path, f"ЗАПРОС (Состояние: {state}, Итерация: {log_iter})", current_prompt)
        answer_data = sloth_core.send_request_to_model(model_instance, active_service, current_prompt, log_iter)
        
        if not answer_data:
            if sloth_core.model:
                print(f"{Colors.WARNING}🔄 ЛОГ: Ответ от модели не получен, пробую снова...{Colors.ENDC}")
                time.sleep(5)
                continue
            else:
                final_message = "Критическая ошибка: Не удалось получить ответ и нет запасного API."
                break

        answer_text = answer_data["text"]
        _log_run(run_log_file_path, f"ОТВЕТ (Состояние: {state}, Итерация: {log_iter})", answer_text)

        cost = calculate_cost(sloth_core.MODEL_NAME, answer_data["input_tokens"], answer_data["output_tokens"])
        total_cost += cost
        cost_log.append({"phase": state, "iteration": log_iter, "cost": cost})
        print(f"{Colors.GREY}📊 Статистика: Вход: {answer_data['input_tokens']} т., Выход: {answer_data['output_tokens']} т. Стоимость: ~${cost:.6f}{Colors.ENDC}")

        if state == "PLANNING":
            clarification = extract_block("clarification", answer_text)
            if clarification:
                print(f"{Colors.HEADER}{Colors.BOLD}🤖 Модель просит уточнений:{Colors.ENDC}\n{Colors.CYAN}{clarification}{Colors.ENDC}")
                user_response = _read_multiline_input("Пожалуйста, предоставьте ответ на вопросы модели. (Enter 3 раза для завершения)")
                initial_task += f"\n\n--- УТОЧНЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ ---\n{user_response}"
                current_prompt = None
                continue

            plan = extract_block("plan", answer_text)
            files_list_str = extract_block("files", answer_text)
            if plan and files_list_str:
                print(f"{Colors.OKGREEN}✅ Задача понятна. План получен.{Colors.ENDC}\n{Colors.HEADER}План действий:{Colors.ENDC}\n{Colors.CYAN}{plan}{Colors.ENDC}")
                with open("sloth_plan.txt", "w", encoding='utf-8') as f:
                    f.write(plan)
                print(f"{Colors.OKGREEN}План сохранен в 'sloth_plan.txt'.{Colors.ENDC}")
                raw_files_list = [line.strip() for line in files_list_str.split('\n') if line.strip()]
                project_root_name = os.path.basename(os.getcwd()) + os.sep
                files_to_include_fully = []
                for f_path in raw_files_list:
                    if f_path.startswith(project_root_name):
                        normalized_path = f_path[len(project_root_name):]
                        files_to_include_fully.append(normalized_path)
                        print(f"{Colors.GREY}ℹ️  Путь нормализован: '{f_path}' -> '{normalized_path}'{Colors.ENDC}")
                    else:
                        files_to_include_fully.append(f_path)
                print(f"{Colors.HEADER}Запрошены полные версии файлов:{Colors.ENDC}\n{Colors.CYAN}" + "\n".join(files_to_include_fully) + Colors.ENDC)
                state = "EXECUTION"
                current_prompt = None
                continue
            else:
                print(f"{Colors.WARNING}⚠️ Модель не вернула ни уточнений, ни плана. Пробуем снова...{Colors.ENDC}")
                time.sleep(5)
                continue

        elif state == "EXECUTION":
            if extract_block("done_summary", answer_text) or answer_text.strip().upper().startswith("ГОТОВО"):
                done_summary = extract_block("done_summary", answer_text) or "Задача выполнена."
                final_message = f"{Colors.OKGREEN}{Symbols.CHECK} Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
                update_history_with_attempt(history_file_path, user_goal, done_summary)
                print(f"{Colors.OKGREEN}📄 ИТОГОВОЕ РЕЗЮМЕ:\n{Colors.CYAN}{done_summary}{Colors.ENDC}")
                manual_steps = extract_block("manual", answer_text)
                if manual_steps:
                    final_message += f"\n\n{Colors.WARNING}✋ ТРЕБУЮТСЯ РУЧНЫЕ ДЕЙСТВИЯ:{Colors.ENDC}\n{manual_steps}"
                break
            
            # --- ОБРАБОТКА ДЕЙСТВИЙ: write_file (мульти-блоки) или bash ---
            commands_to_run = extract_block("bash", answer_text)
            write_blocks = list(_iter_write_file_blocks(answer_text))
            strategy_description = extract_block("summary", answer_text) or "Стратегия не описана"
            
            action_taken, success, failed_command, error_message = False, False, "N/A", ""

            if write_blocks:
                action_taken = True
                for filepath, content in write_blocks:
                    try:
                        print(f"\n{Colors.OKBLUE}📝 Найден блок write_file. Перезаписываю файл: {filepath}{Colors.ENDC}")
                        dir_name = os.path.dirname(filepath)
                        if dir_name:
                            os.makedirs(dir_name, exist_ok=True)
                        # Пишем БЕЗ strip(), С РОВНО ТЕМ СОДЕРЖИМЫМ, ЧТО ПРИШЛО
                        with open(filepath, "w", encoding="utf-8", newline="") as f:
                            f.write(content)
                        print(f"{Colors.OKGREEN}✅ Файл успешно перезаписан: {filepath}{Colors.ENDC}")
                        success = True
                    except Exception as e:
                        print(f"{Colors.FAIL}❌ ОШИБКА при записи файла '{filepath}': {e}{Colors.ENDC}")
                        success = False
                        failed_command = f"write_file {filepath}"
                        error_message = str(e)
                        break  # прекращаем последовательность, чтобы вернуть ошибку корректно

            elif commands_to_run:
                action_taken = True
                print(f"\n{Colors.OKBLUE}🔧 Найден блок shell-команд. Выполняю...{Colors.ENDC}")
                success, failed_command, error_message = sloth_runner.execute_commands(commands_to_run)

            if not action_taken:
                print(f"{Colors.FAIL}❌ ЛОГ: Модель не вернула команд. Пробую на следующей итерации.{Colors.ENDC}")
                project_context = get_project_context(is_fast_mode, files_to_include_fully)
                current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
                iteration_count += 1
                continue
            
            project_context = get_project_context(is_fast_mode, files_to_include_fully)
            if not project_context:
                final_message = f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"
                break

            history_entry = f"**Итерация {iteration_count}:**\n**Стратегия:** {strategy_description}\n"
            if success:
                history_entry += "**Результат:** УСПЕХ"
                current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history)
            else:
                history_entry += f"**Результат:** ПРОВАЛ\n**Ошибка:** {error_message}"
                current_prompt = sloth_core.get_error_fixing_prompt(
                    failed_command, error_message, user_goal, project_context, iteration_count + 1, attempt_history
                )
            
            attempt_history.append(history_entry)
            iteration_count += 1
    
    if not final_message:
        final_message = f"{Colors.WARNING}⌛ Достигнут лимит в {MAX_ITERATIONS} итераций.{Colors.ENDC}"
    cost_report(cost_log, total_cost)
    return final_message

# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    SLOTH_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Sloth: AI-ассистент для автоматического рефакторинга кода.")
    parser.add_argument('--here', action='store_true', help='Запустить для проекта в текущей директории (игнорируется с --fix).')
    parser.add_argument('--fix', action='store_true', help='Запустить в режиме исправления, загрузив настройки из последней сессии.')
    parser.add_argument('--fast', action='store_true', help='Запустить в быстром режиме (игнорируется с --fix).')
    args = parser.parse_args()

    # --- 1. Инициализация модели ---
    sloth_core.initialize_model()
    model_instance, _ = sloth_core.get_active_service_details()
    if not model_instance:
        print(f"{Colors.FAIL}❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель. "
              f"Проверьте API-ключ или настройки соединения. Завершение работы.{Colors.ENDC}")
        sys.exit(1)
    print(f"{Colors.OKGREEN}✅ Модель AI успешно инициализирована.{Colors.ENDC}\n")

    # --- 2. Определение пути к проекту ---
    history_file_path = os.path.join(SLOTH_SCRIPT_DIR, HISTORY_FILE_NAME)
    target_project_path, is_fast_mode = "", args.fast

    if args.fix:
        print(f"{Colors.CYAN}{Symbols.GEAR}  Активирован режим --fix. Загрузка конфигурации из {history_file_path}...{Colors.ENDC}")
        if not os.path.exists(history_file_path):
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ОШИБКА: Файл истории {history_file_path} не найден.{Colors.ENDC}")
            sys.exit(1)
        try:
            with open(history_file_path, 'r', encoding='utf-8') as f:
                config = json.load(f).get("last_run_config")
            target_project_path, is_fast_mode = config["target_project_path"], config["is_fast_mode"]
            print(f"{Colors.OKGREEN}{Symbols.CHECK} Конфигурация загружена. Проект: {target_project_path}, Режим: {'Быстрый' if is_fast_mode else 'Интеллектуальный'}.{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ОШИБКА: Не удалось прочитать конфигурацию: {e}{Colors.ENDC}")
            sys.exit(1)
    else:
        if args.here:
            target_project_path = os.getcwd()
        else:
            print(f"{Colors.OKBLUE}Пожалуйста, выберите папку проекта в открывшемся окне...{Colors.ENDC}")
            root = Tk(); root.withdraw()
            target_project_path = filedialog.askdirectory(title="Выберите папку проекта для Sloth")
            root.destroy()
        if not target_project_path:
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} Папка проекта не была выбрана.{Colors.ENDC}")
            sys.exit(1)
        if os.path.exists(history_file_path):
            os.remove(history_file_path)
        initial_history = {
            "last_run_config": {"target_project_path": target_project_path, "is_fast_mode": is_fast_mode},
            "previous_attempts": []
        }
        with open(history_file_path, 'w', encoding='utf-8') as f:
            json.dump(initial_history, f, indent=2, ensure_ascii=False)
        print(f"{Colors.CYAN}{Symbols.SAVE} Конфигурация для новой сессии сохранена в {history_file_path}.{Colors.ENDC}")

    # --- 3. Переход в директорию и запуск ---
    print(f"{Colors.OKGREEN}{Symbols.CHECK} Рабочая директория проекта: {target_project_path}{Colors.ENDC}")
    os.chdir(target_project_path)
    run_log_file_path = os.path.join(SLOTH_SCRIPT_DIR, RUN_LOG_FILE_NAME)
    try:
        with open(run_log_file_path, 'w', encoding='utf-8') as f:
            f.write(f"# SLOTH RUN LOG\n# Целевой проект: {target_project_path}\n# Режим: {'Быстрый' if is_fast_mode else 'Интеллектуальный'}\n")
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось инициализировать {run_log_file_path}: {e}{Colors.ENDC}")
    
    final_status = "Работа завершена."
    try:
        final_status = main(is_fix_mode=args.fix, is_fast_mode=is_fast_mode, history_file_path=history_file_path, run_log_file_path=run_log_file_path)
    except KeyboardInterrupt:
        final_status = f"\n{Colors.OKBLUE}{Symbols.BLUE_DOT} Процесс прерван пользователем.{Colors.ENDC}"
    except Exception as e:
        import traceback; traceback.print_exc()
        final_status = f"\n{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} Скрипт аварийно завершился: {e}{Colors.ENDC}"
    finally:
        print(f"\n{final_status}")
        print(f"\n{Colors.BOLD}{Symbols.FLAG} Скрипт завершил работу.{Colors.ENDC}")
