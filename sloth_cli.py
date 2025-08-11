# Файл: sloth_cli.py
import os
import sys
import time
import re
import json
import platform
import subprocess
import argparse
# --- ИЗМЕНЕННЫЙ БЛОК ИМПОРТА TKINTER ---
try:
    from tkinter import Tk, filedialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
import uuid
import shutil

from colors import Colors, Symbols
import sloth_core
import sloth_runner
import context_collector
import config as sloth_config

# --- КОНСТАНТЫ ИНТЕРФЕЙСА ---
MAX_ITERATIONS = 20
HISTORY_FILE_NAME = 'sloth_history.json'
RUN_LOG_FILE_NAME = 'sloth_run.log'
PLAN_FILE_NAME = 'sloth_plan.txt'
# Базовая стартовая папка выбора проекта (уменьшает количество кликов)
# Может быть переопределена в конфиге: paths.default_start_dir
DEFAULT_START_DIR = '/Users/vladimirdoronin/VovkaNowEngineer'

def _parse_and_validate_filepath(header_line: str, project_root_dir: str) -> str:
    """
    Извлекает и валидирует путь к файлу из полного заголовка write_file.
    Возвращает безопасный, АБСОЛЮТНЫЙ путь к файлу или вызывает ValueError.
    """
    if not header_line.startswith("```write_file"):
        raise ValueError(f"Некорректный заголовок write_file: отсутствует префикс ```write_file. Получено: '{header_line}'")

    match = re.search(r'path\s*=\s*"([^"]+)"', header_line)
    if not match:
        raise ValueError(f"Путь в заголовке не соответствует формату path=\"...\": '{header_line}'")
    
    path_from_model = match.group(1).strip()

    if not path_from_model:
        raise ValueError("Атрибут 'path' в заголовке write_file не может быть пустым.")

    if ".." in path_from_model.split(os.sep) or path_from_model.startswith(('~', '/', '\\')):
        raise ValueError(f"Недопустимый путь (попытка выхода из директории или абсолютный путь): '{path_from_model}'")

    normalized_path = os.path.normpath(path_from_model)
    project_root_abs = os.path.abspath(project_root_dir)
    intended_file_abs = os.path.abspath(os.path.join(project_root_abs, normalized_path))
    
    if not intended_file_abs.startswith(project_root_abs):
        raise ValueError(f"Обнаружена попытка выхода за пределы директории проекта: '{path_from_model}'")

    return intended_file_abs

def get_project_context(is_fast_mode, files_to_include_fully=None):
    print(f"{Colors.CYAN}{Symbols.SPINNER} ЛОГ: Обновляю контекст проекта...{Colors.ENDC}", end='\r', flush=True)
    start_time = time.time()
    try:
        if is_fast_mode:
            context_data = context_collector.gather_project_context(os.getcwd(), mode='full')
        else:
            mode = 'summarized'
            if files_to_include_fully:
                print(f"{Colors.GREY}{Symbols.INFO}  Полное содержимое файлов: {len(files_to_include_fully)} шт.{Colors.ENDC}", flush=True)
            context_data = context_collector.gather_project_context(
                os.getcwd(), mode=mode, full_content_files=files_to_include_fully
            )
        duration = time.time() - start_time
        print(f"{Colors.OKGREEN}{Symbols.CHECK} ЛОГ: Контекст успешно обновлен за {duration:.2f} сек. Размер: {len(context_data)} символов.{' '*10}{Colors.ENDC}", flush=True)
        return context_data, duration
    except Exception as e:
        print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}{' '*20}{Colors.ENDC}", flush=True)
        return None, 0

def _log_run(log_file_path, title, content):
    try:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "="*80 + "\n" + f"{title}\n" + "-"*80 + "\n")
            f.write(str(content if content is not None else "<empty>") + "\n")
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось записать в {log_file_path}: {e}{Colors.ENDC}", flush=True)

def _read_multiline_input(prompt):
    print(prompt, flush=True)
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

def parse_all_blocks(text: str) -> list[dict]:
    """
    Находит и извлекает все блоки ```tag...``` из текста.
    Специально обработан для 'write_file' с boundary, чтобы корректно извлекать
    содержимое файла, даже если оно содержит вложенные ``` блоки.
    """
    # Этот паттерн находит ```, тег, заголовок, затем (жадно) ВЕСЬ контент до финального ```
    pattern = re.compile(r"```(\w+)([^\n]*)?\n(.*?)\n```", re.DOTALL)
    
    blocks = []
    for match in pattern.finditer(text):
        block_type = match.group(1).strip()
        header_args = (match.group(2) or "").strip()
        full_header = f"```{block_type} {header_args}".strip()
        content = match.group(3)  # Сначала берем весь контент "как есть"

        # НОВАЯ ЛОГИКА: Проверяем, есть ли в этом блоке boundary
        if block_type == 'write_file':
            boundary_match = re.search(r'boundary\s*=\s*"([^"]+)"', header_args)
            if boundary_match:
                boundary = boundary_match.group(1)
                # Если контент заканчивается на boundary, отрезаем его
                # Используем split, чтобы безопасно отделить контент от границы
                if content.endswith(boundary):
                    content = content.rsplit(boundary, 1)[0].rstrip('\r\n')

        blocks.append({
            "type": block_type,
            "header": full_header,
            "content": content
        })
    return blocks

def update_history_with_attempt(history_file_path, goal, summary):
    try:
        with open(history_file_path, 'r+', encoding='utf-8') as f:
            history_data = json.load(f)
            new_entry = {"initial_goal": goal, "solution_summary": summary}
            history_data.setdefault("previous_attempts", []).insert(0, new_entry)
            f.seek(0)
            json.dump(history_data, f, indent=2, ensure_ascii=False)
            f.truncate()
        print(f"{Colors.OKGREEN}💾 ЛОГ: История решения обновлена в {history_file_path}.{Colors.ENDC}", flush=True)
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось обновить историю решения: {e}{Colors.ENDC}", flush=True)

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
        print(f"{Colors.FAIL}❌ ЛОГ: Не удалось загрузить или прочитать файл истории {history_file_path}: {e}{Colors.ENDC}", flush=True)
        return None

def notify_user(message):
    clean_message = re.sub(r'\033\[.*?m', '', message)
    print(f"{Colors.OKBLUE}📢 ЛОГ: Отправляю итоговое уведомление...{Colors.ENDC}", flush=True)
    print(message, flush=True)

def time_report(timings, total_start_time):
    total_duration = time.time() - total_start_time
    measured_duration = sum(timings.values())
    other_duration = total_duration - measured_duration if total_duration > measured_duration else 0.0

    print(f"\n{Colors.BOLD}{Colors.HEADER}--- ИТОГОВЫЙ ОТЧЕТ ПО ВРЕМЕНИ ---{Colors.ENDC}", flush=True)
    print(f"  - Сбор контекста:   {timings['context']:.2f} сек.", flush=True)
    print(f"  - Запросы к модели:   {timings['model']:.2f} сек.", flush=True)
    print(f"  - Выполнение команд:  {timings['commands']:.2f} сек.", flush=True)
    print(f"  - Верификация:        {timings['verify']:.2f} сек.", flush=True)
    print(f"  - Прочее (ввод/etc):  {other_duration:.2f} сек.", flush=True)
    print(f"{Colors.BOLD}\n  Общее время работы: {total_duration:.2f} сек.{Colors.ENDC}", flush=True)

def cost_report(cost_log, total_cost):
    print(f"\n{Colors.BOLD}{Colors.HEADER}--- ИТОГОВЫЙ ОТЧЕТ ПО СТОИМОСТИ ---{Colors.ENDC}", flush=True)
    for entry in cost_log:
        phase, cost = entry['phase'], entry['cost']
        if phase == 'PLANNING':
            print(f"  Фаза: {phase:<12} | Стоимость: ${cost:.6f}", flush=True)
        else:
            iteration = entry['iteration']
            print(f"  Фаза: {phase:<12} | Итерация: {iteration:<2} | Стоимость: ${cost:.6f}", flush=True)
    print(f"{Colors.BOLD}\n  Общая стоимость задачи: ${total_cost:.6f}{Colors.ENDC}", flush=True)

def calculate_cost(model_name, input_tokens, output_tokens):
    """
    Расчёт стоимости запроса.

    - Если заданы ENV-переменные, используется OVERRIDE со ставками за 1000 токенов:
        SLOTH_COST_IN_RATE, SLOTH_COST_OUT_RATE.
      Это поведение сохранено для обратной совместимости.
    - Если ENV не заданы, используются тарифы из sloth_core.MODEL_PRICING,
      где цены заданы за 1,000,000 токенов (как в публичном прайсинге Google Gemini).
    """
    # 1) Пробуем ENV-override; если заданы оба — используем их напрямую
    try:
        in_rate = float(os.getenv("SLOTH_COST_IN_RATE", "0"))
        out_rate = float(os.getenv("SLOTH_COST_OUT_RATE", "0"))
    except Exception:
        in_rate, out_rate = 0.0, 0.0

    try:
        in_tokens = float(input_tokens or 0)
        out_tokens = float(output_tokens or 0)
    except Exception:
        in_tokens, out_tokens = 0.0, 0.0

    if in_rate > 0 or out_rate > 0:
        # ENV-override трактуем КАК ставку за 1,000 токенов (исторически)
        return (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate

    # 2) Если ENV не задан — используем таблицу тарифов из sloth_core.MODEL_PRICING (по tiers)
    pricing = getattr(sloth_core, "MODEL_PRICING", {}) or {}

    def pick_model_key(name: str) -> str:
        if name in pricing:
            return name
        # Поиск по префиксу/вхождению, чтобы покрыть вариации (например, gemini-2.5-pro-exp)
        name_low = (name or "").lower()
        for k in pricing.keys():
            k_low = k.lower()
            if name_low.startswith(k_low) or k_low in name_low:
                return k
        # Фолбэк — если задан дефолт в sloth_core
        default_key = getattr(sloth_core, "MODEL_NAME", None)
        if default_key and default_key in pricing:
            return default_key
        return ""

    def pick_tier_price(tiers, tokens: float) -> float:
        try:
            # tiers: list of {up_to, price}; выбираем первый с up_to >= tokens
            sorted_tiers = sorted((tiers or []), key=lambda t: float(t.get("up_to", float('inf'))))
            for t in sorted_tiers:
                up_to = t.get("up_to", float('inf'))
                price = t.get("price", None)
                if price is None:
                    continue
                if tokens <= float(up_to):
                    return float(price)
            # если ничего не подошло — последняя известная цена или 0
            if sorted_tiers:
                last_price = sorted_tiers[-1].get("price", 0.0)
                return float(last_price or 0.0)
        except Exception:
            pass
        return 0.0

    mkey = pick_model_key(model_name)
    mp = pricing.get(mkey, {})
    in_price_per_1k = pick_tier_price(((mp.get("input") or {}).get("tiers") or []), in_tokens)
    out_price_per_1k = pick_tier_price(((mp.get("output") or {}).get("tiers") or []), out_tokens)

    # Цены из MODEL_PRICING считаем за 1,000,000 токенов (единица прайсинга от Google)
    return (in_tokens / 1_000_000.0) * in_price_per_1k + (out_tokens / 1_000_000.0) * out_price_per_1k

def main(is_fix_mode, is_fast_mode, history_file_path, run_log_file_path, plan_file_path, verify_timeout_seconds=15, log_trim_limit=20000):
    total_start_time = time.time()
    timings = {'context': 0.0, 'model': 0.0, 'commands': 0.0, 'verify': 0.0}
    total_cost, cost_log = 0.0, []

    user_goal, error_log = get_user_input()
    if not user_goal:
        return f"{Colors.WARNING}Цель не была указана. Завершение работы.{Colors.ENDC}"
    initial_task = user_goal + (f"\n\n--- ЛОГ ОШИБКИ ---\n{error_log}" if error_log else "")
    
    # --- State Machine Setup ---
    state = "INITIAL_CODING" if is_fast_mode else "PLANNING"
    if is_fix_mode:
        state = "INITIAL_CODING"

    iteration_count = 1
    attempt_history, final_message = [], ""
    BOUNDARY_TOKEN = f"SLOTH_BOUNDARY_{uuid.uuid4().hex}"

    # Variables to pass data between states
    files_to_include_fully = None
    failed_command, error_message, logs_collected = None, None, None

    # --- Verify Command Setup ---
    verify_command = None
    try:
        # Simplified setup logic, assumes last_run_config exists if history does
        if os.path.exists(history_file_path):
            with open(history_file_path, 'r', encoding='utf-8') as f:
                verify_command = json.load(f).get("last_run_config", {}).get("verify_command")
        
        if not is_fast_mode and verify_command is None:
            print(f"{Colors.OKBLUE}Вопрос: Какую команду использовать для запуска и проверки проекта (например, 'npm run dev' или 'pytest')? Если автоматическая проверка не нужна, просто нажмите Enter.{Colors.ENDC}", flush=True)
            verify_command = input().strip() or "" # Default to empty string
            # Save for the session
            if os.path.exists(history_file_path):
                with open(history_file_path, 'r+', encoding='utf-8') as f:
                    _hist = json.load(f)
                    _hist.setdefault("last_run_config", {})["verify_command"] = verify_command
                    f.seek(0)
                    json.dump(_hist, f, indent=2, ensure_ascii=False)
                    f.truncate()
            print(f"{Colors.CYAN}{Symbols.SAVE} Команда верификации сохранена в историю сессии.{Colors.ENDC}", flush=True)
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось обработать verify_command: {e}{Colors.ENDC}", flush=True)

    # Детектор повторяющихся правок тех же файлов
    prev_changed_files = None
    repeat_same_files_count = 0

    while iteration_count <= MAX_ITERATIONS and state != "DONE":
        model_instance, active_service = sloth_core.get_active_service_details()

        # --- 1. GENERATE PROMPT BASED ON STATE ---
        current_prompt = None
        log_iter = iteration_count if state != "PLANNING" else 0
        
        if state == "PLANNING":
            print(f"\n{Colors.BOLD}{Colors.HEADER}--- ЭТАП: ПЛАНИРОВАНИЕ ---{Colors.ENDC}", flush=True)
            project_context, duration = get_project_context(is_fast_mode=False, files_to_include_fully=None)
            timings['context'] += duration
            if project_context:
                current_prompt = sloth_core.get_clarification_and_planning_prompt(project_context, initial_task, boundary=BOUNDARY_TOKEN)
        else: # Any execution state
            print(f"\n{Colors.BOLD}{Colors.HEADER}{Symbols.ROCKET} --- ЭТАП: ИСПОЛНЕНИЕ ({state}) | ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---{Colors.ENDC}", flush=True)
            project_context, duration = get_project_context(is_fast_mode, files_to_include_fully)
            timings['context'] += duration
            if project_context:
                if state == "INITIAL_CODING":
                    fix_history = load_fix_history(history_file_path) if is_fix_mode else None
                    current_prompt = sloth_core.get_initial_prompt(project_context, initial_task, fix_history, BOUNDARY_TOKEN)
                elif state == "REVIEWING":
                    current_prompt = sloth_core.get_review_prompt(project_context, initial_task, iteration_count, attempt_history, BOUNDARY_TOKEN)
                elif state == "FIXING_ERROR":
                    current_prompt = sloth_core.get_error_fixing_prompt(failed_command, error_message, initial_task, project_context, iteration_count, attempt_history, BOUNDARY_TOKEN)
                elif state == "ANALYZING_LOGS":
                    current_prompt = sloth_core.get_log_analysis_prompt(project_context, initial_task, attempt_history, logs_collected, BOUNDARY_TOKEN)
            
        if not project_context:
            final_message = f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить контекст проекта.{Colors.ENDC}"
            break
        
        _log_run(run_log_file_path, f"ЗАПРОС (Состояние: {state}, Итерация: {log_iter})", current_prompt)
        # Лог подготовки запроса печатается в sloth_core.send_request_to_model(); здесь не дублируем
        print(f"{Colors.CYAN}{Symbols.SPINNER} Думаю...{Colors.ENDC}", end='\r', flush=True)
        start_model_time = time.time()
        
        # --- 2. SEND REQUEST TO MODEL ---
        answer_data = sloth_core.send_request_to_model(model_instance, active_service, current_prompt, log_iter)
        model_duration = time.time() - start_model_time
        timings['model'] += model_duration

        if not answer_data:
            print(f"{Colors.WARNING}🔄 ЛОГ: Ответ от модели не получен, пробую снова...{Colors.ENDC}", flush=True)
            time.sleep(5)
            continue
        
        answer_text = answer_data["text"]
        _log_run(run_log_file_path, f"ОТВЕТ (Состояние: {state}, Итерация: {log_iter})", answer_text)

        cost = calculate_cost(sloth_core.MODEL_NAME, answer_data["input_tokens"], answer_data["output_tokens"])
        total_cost += cost
        cost_log.append({"phase": state, "iteration": log_iter, "cost": cost})
        print(f"{Colors.GREY}📊 Статистика: Вход: {answer_data['input_tokens']} т., Выход: {answer_data['output_tokens']} т. | Время: {model_duration:.2f} сек. | Стоимость: ~${cost:.6f}{' '*10}{Colors.ENDC}", flush=True)

        # --- 3. PROCESS RESPONSE AND DETERMINE NEXT STATE ---
        # --- НОВЫЙ, НАДЕЖНЫЙ КОД ---
        if state == "PLANNING":
            # Логика для планирования используется новый парсер для единообразия.
            all_plan_blocks = parse_all_blocks(answer_text)
            clarification_block = next((b for b in all_plan_blocks if b['type'] == 'clarification'), None)
            
            if clarification_block:
                clarification = clarification_block['content']
                print(f"{Colors.HEADER}{Colors.BOLD}🤖 Модель просит уточнений:{Colors.ENDC}\n{Colors.CYAN}{clarification}{Colors.ENDC}", flush=True)
                user_response = _read_multiline_input("Пожалуйста, предоставьте ответ на вопросы модели. (Enter 3 раза для завершения)")
                initial_task += f"\n\n--- УТОЧНЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ ---\n{user_response}"
                state = "PLANNING" # Loop in planning state
                continue

            plan_block = next((b for b in all_plan_blocks if b['type'] == 'plan'), None)
            files_block = next((b for b in all_plan_blocks if b['type'] == 'files'), None)

            if plan_block and files_block:
                plan = plan_block['content']
                files_list_str = files_block['content']
                print(f"{Colors.OKGREEN}✅ Задача понятна. План получен.{Colors.ENDC}\n{Colors.HEADER}План действий:{Colors.ENDC}\n{Colors.CYAN}{plan}{Colors.ENDC}", flush=True)
                with open(plan_file_path, "w", encoding='utf-8') as f: f.write(plan)
                
                raw_files_list = [line.strip() for line in files_list_str.split('\n') if line.strip() and not line.strip().startswith('- ')]
                # Здесь _normalize_model_path больше не нужен, валидация будет на этапе записи
                files_to_include_fully = raw_files_list

                print(f"{Colors.HEADER}Запрошены полные версии файлов:{Colors.ENDC}\n{Colors.CYAN}" + "\n".join(files_to_include_fully) + Colors.ENDC, flush=True)
                state = "INITIAL_CODING"
            else:
                print(f"{Colors.WARNING}⚠️ Модель не вернула ни уточнений, ни плана. Пробуем снова...{Colors.ENDC}", flush=True)
                time.sleep(5)
                state = "PLANNING"
        else: # Любое состояние исполнения
            all_blocks = parse_all_blocks(answer_text)

            strategy_description = next((b['content'] for b in all_blocks if b['type'] == 'summary'), "Стратегия не описана")
            commands_to_run_block = next((b for b in all_blocks if b['type'] == 'bash'), None)
            write_file_blocks = [b for b in all_blocks if b['type'] == 'write_file']
            verify_run_present = any(b['type'] == 'verify_run' for b in all_blocks)
            done_summary_block = next((b for b in all_blocks if b['type'] == 'done_summary'), None)
            is_done = done_summary_block is not None

            action_taken, success = False, False
            iteration_changed_files = set()
            iteration_created_paths = set()

            if write_file_blocks:
                action_taken = True
                for block in write_file_blocks:
                    try:
                        safe_filepath = _parse_and_validate_filepath(block['header'], os.getcwd())
                        relative_path_for_display = os.path.relpath(safe_filepath, os.getcwd())
                        
                        # --- ДОБАВЛЕНА ПРОВЕРКА ---
                        # Защита от случайного стирания файла
                        if not block['content'] and os.path.exists(safe_filepath):
                            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Модель предложила очистить существующий файл {relative_path_for_display}. Действие пропущено.{Colors.ENDC}", flush=True)
                            continue # Переходим к следующему файлу, не выполняя запись
                        # --- КОНЕЦ ПРОВЕРКИ ---
                        
                        print(f"\n{Colors.OKBLUE}📝 Перезаписываю файл: {relative_path_for_display}{Colors.ENDC}", flush=True)
                        existed_before = os.path.exists(safe_filepath)
                        os.makedirs(os.path.dirname(safe_filepath), exist_ok=True)
                        with open(safe_filepath, "w", encoding="utf-8", newline="") as f:
                            f.write(block['content'])

                        print(f"{Colors.OKGREEN}✅ Файл успешно перезаписан: {relative_path_for_display}{Colors.ENDC}", flush=True)
                        success = True
                        iteration_changed_files.add(relative_path_for_display)
                        if not existed_before:
                            iteration_created_paths.add(relative_path_for_display)
                    except ValueError as e:
                        print(f"{Colors.FAIL}❌ ОШИБКА ВАЛИДАЦИИ: {e}{Colors.ENDC}", flush=True)
                        success, failed_command, error_message = False, f"write_file ({block['header']})", str(e)
                        break
                    except Exception as e:
                        print(f"{Colors.FAIL}❌ ОШИБКА при записи файла '{block['header']}': {e}{Colors.ENDC}", flush=True)
                        success, failed_command, error_message = False, f"write_file ({block['header']})", str(e)
                        break
            
            elif commands_to_run_block:
                action_taken = True
                print(f"\n{Colors.OKBLUE}🔧 Выполняю shell-команды...{Colors.ENDC}", flush=True)
                start_cmd_time = time.time()
                success, failed_command, error_message, changed_files, created_paths = sloth_runner.execute_commands(commands_to_run_block['content'])
                iteration_changed_files |= set(changed_files or set())
                iteration_created_paths |= set(created_paths or set())
                timings['commands'] += time.time() - start_cmd_time

            # --- Логика определения следующего состояния (остаётся в основном без изменений) ---
            history_entry = f"**Итерация {iteration_count} ({state}):**\n**Стратегия:** {strategy_description}\n"
            if iteration_changed_files or iteration_created_paths:
                changed_list = ", ".join(sorted(iteration_changed_files)) or "—"
                created_list = ", ".join(sorted(iteration_created_paths)) or "—"
                history_entry += f"**Изменены файлы:** {changed_list}\n**Созданы пути:** {created_list}\n"

            # Простая аннотация повторяющихся правок тех же файлов
            if prev_changed_files is not None and iteration_changed_files == prev_changed_files and iteration_changed_files:
                repeat_same_files_count += 1
            else:
                repeat_same_files_count = 0
            prev_changed_files = set(iteration_changed_files)
            if repeat_same_files_count >= 1 and iteration_changed_files:
                history_entry += f"**Замечание:** Повтор правок одних и тех же файлов уже {repeat_same_files_count + 1} итерации подряд. Избегай микро‑изменений, консолидируй правки и, если цель достигнута, возвращай `ГОТОВО`.\n"

            # Если те же файлы меняются уже в третий раз подряд — форсируем верификацию и анализ логов
            if repeat_same_files_count >= 2 and iteration_changed_files:
                print(f"{Colors.WARNING}{Symbols.WARNING}  Обнаружен повтор правок одних и тех же файлов (>=3 подряд). Форсирую верификацию и анализ логов.{Colors.ENDC}", flush=True)
                if verify_command is not None:
                    print(f"{Colors.OKBLUE}🧪 (FORCED) Запускаю верификацию: {verify_command}{Colors.ENDC}", flush=True)
                    start_verify_time = time.time()
                    try:
                        proc = subprocess.Popen(verify_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
                        stdout, stderr = proc.communicate(timeout=verify_timeout_seconds)
                        rc = proc.returncode
                    except subprocess.TimeoutExpired:
                        proc.kill(); stdout, stderr = proc.communicate(); rc = 124
                    except Exception as e:
                        stdout, stderr, rc = "", f"Ошибка запуска verify_command: {e}", -1
                    timings['verify'] += time.time() - start_verify_time
                    def _trim(s, lim=log_trim_limit): return (s[:lim] + "\n...[TRIMMED]...") if len(s) > lim else s
                    logs_collected = f"$ {verify_command}\n(exit={rc})\n\n[STDOUT]\n{_trim(stdout)}\n\n[STDERR]\n{_trim(stderr)}"
                    _log_run(run_log_file_path, "ЛОГИ ВЕРИФИКАЦИИ (FORCED)", logs_collected)
                else:
                    logs_collected = "(Верификация не настроена) Автоматический переход в анализ логов из-за повторяющихся правок тех же файлов."
                    _log_run(run_log_file_path, "ЛОГИ ВЕРИФИКАЦИИ (FORCED-NONE)", logs_collected)
                state = "ANALYZING_LOGS"
                attempt_history.append(history_entry)
                iteration_count += 1
                continue

            if is_done:
                final_message = f"{Colors.OKGREEN}{Symbols.CHECK} Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
                done_summary_text = done_summary_block['content'] if done_summary_block else "Задача выполнена."
                update_history_with_attempt(history_file_path, user_goal, done_summary_text)
                print(f"{Colors.OKGREEN}📄 ИТОГОВОЕ РЕЗЮМЕ:\n{Colors.CYAN}{done_summary_text or 'Нет резюме.'}{Colors.ENDC}", flush=True)
                manual_block = next((b for b in all_blocks if b['type'] == 'manual'), None)
                if manual_block:
                    final_message += f"\n\n{Colors.WARNING}✋ ТРЕБУЮТСЯ РУЧНЫЕ ДЕЙСТВИЯ:{Colors.ENDC}\n{manual_block['content']}"
                state = "DONE"
            elif not action_taken:
                print(f"{Colors.FAIL}❌ ЛОГ: Модель не вернула ни команд, ни файла. Перехожу к анализу.{Colors.ENDC}", flush=True)
                history_entry += "**Результат:** ПРОВАЛ (нет действий)\n**Ошибка:** Модель не сгенерировала действий."
                state = "REVIEWING"
            elif success:
                history_entry += "**Результат:** УСПЕХ"
                if verify_run_present and verify_command is not None:
                    print(f"{Colors.OKBLUE}🧪 Запускаю верификацию: {verify_command}{Colors.ENDC}", flush=True)
                    start_verify_time = time.time()
                    try:
                        proc = subprocess.Popen(verify_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
                        stdout, stderr = proc.communicate(timeout=verify_timeout_seconds)
                        rc = proc.returncode
                    except subprocess.TimeoutExpired:
                        proc.kill(); stdout, stderr = proc.communicate(); rc = 124
                    except Exception as e:
                        stdout, stderr, rc = "", f"Ошибка запуска verify_command: {e}", -1
                    timings['verify'] += time.time() - start_verify_time
                    def _trim(s, lim=log_trim_limit): return (s[:lim] + "\n...[TRIMMED]...") if len(s) > lim else s
                    logs_collected = f"$ {verify_command}\n(exit={rc})\n\n[STDOUT]\n{_trim(stdout)}\n\n[STDERR]\n{_trim(stderr)}"
                    _log_run(run_log_file_path, "ЛОГИ ВЕРИФИКАЦИИ", logs_collected)
                    state = "ANALYZING_LOGS"
                else:
                    if verify_run_present: print(f"{Colors.GREY}{Symbols.INFO} verify_run есть, но команда не задана. Пропускаю.{Colors.ENDC}", flush=True)
                    state = "REVIEWING"
            else: # failure
                history_entry += f"**Результат:** ПРОВАЛ\n**Ошибка:** {error_message}"
                state = "FIXING_ERROR"

            attempt_history.append(history_entry)
            iteration_count += 1

    if state != "DONE":
        final_message = f"{Colors.WARNING}⌛ Достигнут лимит в {MAX_ITERATIONS} итераций.{Colors.ENDC}"
    
    time_report(timings, total_start_time)
    cost_report(cost_log, total_cost)
    return final_message

# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    SLOTH_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Sloth: AI-ассистент для автоматического рефакторинга кода.")
    parser.add_argument('--here', action='store_true', help='Запустить для проекта в текущей директории (игнорируется с --fix).')
    parser.add_argument('--fix', action='store_true', help='Запустить в режиме исправления, загрузив настройки из последней сессии.')
    parser.add_argument('--fast', action='store_true', help='Запустить в быстром режиме (игнорируется с --fix).')
    parser.add_argument('--verify-timeout', type=int, default=None, help='Таймаут в секундах для команды верификации (env SLOTH_VERIFY_TIMEOUT, по умолчанию 15).')
    parser.add_argument('--log-trim-limit', type=int, default=None, help='Лимит символов для обрезки stdout/stderr в логах (env SLOTH_LOG_TRIM_LIMIT, по умолчанию 20000).')
    args = parser.parse_args()

    # --- Управление директорией логов ---
    LOGS_DIR = os.path.join(SLOTH_SCRIPT_DIR, 'logs')
    # Если запуск не в режиме исправления, очистить предыдущие логи
    if not args.fix:
        if os.path.exists(LOGS_DIR):
            shutil.rmtree(LOGS_DIR)
        os.makedirs(LOGS_DIR)
        # Добавить .gitignore, чтобы логи не попадали в Git
        with open(os.path.join(LOGS_DIR, '.gitignore'), 'w', encoding='utf-8') as f:
            f.write('*\n')
    else:
        # В режиме исправления просто убедимся, что директория существует
        os.makedirs(LOGS_DIR, exist_ok=True)

    # --- 1. Инициализация модели ---
    sloth_core.initialize_model()
    model_instance, _ = sloth_core.get_active_service_details()
    if not model_instance:
        print(f"{Colors.FAIL}❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель. "
              f"Проверьте API-ключ или настройки соединения. Завершение работы.{Colors.ENDC}", flush=True)
        sys.exit(1)
    print(f"{Colors.OKGREEN}✅ Модель AI успешно инициализирована.{Colors.ENDC}\n", flush=True)

    # --- 2. Определение пути к проекту ---
    history_file_path = os.path.join(LOGS_DIR, HISTORY_FILE_NAME)
    target_project_path, is_fast_mode = "", args.fast

    if args.fix:
        print(f"{Colors.CYAN}{Symbols.GEAR}  Активирован режим --fix. Загрузка конфигурации из {history_file_path}...{Colors.ENDC}", flush=True)
        if not os.path.exists(history_file_path):
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ОШИБКА: Файл истории {history_file_path} не найден.{Colors.ENDC}", flush=True)
            sys.exit(1)
        try:
            with open(history_file_path, 'r', encoding='utf-8') as f:
                config = json.load(f).get("last_run_config")
            target_project_path, is_fast_mode = config["target_project_path"], config["is_fast_mode"]
            print(f"{Colors.OKGREEN}{Symbols.CHECK} Конфигурация загружена. Проект: {target_project_path}, Режим: {'Быстрый' if is_fast_mode else 'Интеллектуальный'}.{Colors.ENDC}", flush=True)
        except Exception as e:
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} ОШИБКА: Не удалось прочитать конфигурацию: {e}{Colors.ENDC}", flush=True)
            sys.exit(1)
    else:
        if args.here:
            target_project_path = os.getcwd()
        else:
            _cfg_start = sloth_config.get("paths.default_start_dir", DEFAULT_START_DIR)
            _start_dir = _cfg_start if os.path.isdir(_cfg_start) else os.path.expanduser("~")
            if TKINTER_AVAILABLE:
                print(f"{Colors.OKBLUE}Пожалуйста, выберите папку проекта в открывшемся окне...{Colors.ENDC}", flush=True)
                root = Tk(); root.withdraw()
                target_project_path = filedialog.askdirectory(title="Выберите папку проекта для Sloth", initialdir=_start_dir)
                root.destroy()
            else:
                print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: GUI не доступен. Используется консольный ввод.{Colors.ENDC}", flush=True)
                prompt = f"Пожалуйста, введите полный путь к папке проекта (или нажмите Enter для '{_start_dir}'): "
                user_path = input(prompt).strip()
                target_project_path = user_path or _start_dir
        if not target_project_path or not os.path.isdir(target_project_path):
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} Папка проекта не была выбрана или не существует.{Colors.ENDC}", flush=True)
            sys.exit(1)
        if os.path.exists(history_file_path):
            os.remove(history_file_path)
        initial_history = {
            "last_run_config": {"target_project_path": target_project_path, "is_fast_mode": is_fast_mode},
            "previous_attempts": []
        }
        with open(history_file_path, 'w', encoding='utf-8') as f:
            json.dump(initial_history, f, indent=2, ensure_ascii=False)
        print(f"{Colors.CYAN}{Symbols.SAVE} Конфигурация для новой сессии сохранена в {history_file_path}.{Colors.ENDC}", flush=True)

    # --- 3. Переход в директорию и запуск ---
    print(f"{Colors.OKGREEN}{Symbols.CHECK} Рабочая директория проекта: {target_project_path}{Colors.ENDC}", flush=True)
    os.chdir(target_project_path)
    run_log_file_path = os.path.join(LOGS_DIR, RUN_LOG_FILE_NAME)
    plan_file_path = os.path.join(LOGS_DIR, PLAN_FILE_NAME)
    try:
        with open(run_log_file_path, 'w', encoding='utf-8') as f:
            f.write(f"# SLOTH RUN LOG\n# Целевой проект: {target_project_path}\n# Режим: {'Быстрый' if is_fast_mode else 'Интеллектуальный'}\n")
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось инициализировать {run_log_file_path}: {e}{Colors.ENDC}", flush=True)
    
    # Настройки таймаута и обрезки логов (CLI → ENV → default)
    env_verify_timeout = int(os.getenv("SLOTH_VERIFY_TIMEOUT", "15"))
    env_log_trim_limit = int(os.getenv("SLOTH_LOG_TRIM_LIMIT", "20000"))
    verify_timeout_seconds = args.verify_timeout if args.verify_timeout is not None else env_verify_timeout
    log_trim_limit = args.log_trim_limit if args.log_trim_limit is not None else env_log_trim_limit

    final_status = "Работа завершена."
    try:
        final_status = main(
            is_fix_mode=args.fix,
            is_fast_mode=is_fast_mode,
            history_file_path=history_file_path,
            run_log_file_path=run_log_file_path,
            plan_file_path=plan_file_path,
            verify_timeout_seconds=verify_timeout_seconds,
            log_trim_limit=log_trim_limit,
        )
    except KeyboardInterrupt:
        final_status = f"\n{Colors.OKBLUE}{Symbols.BLUE_DOT} Процесс прерван пользователем.{Colors.ENDC}"
    except Exception as e:
        import traceback; traceback.print_exc()
        final_status = f"\n{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} Скрипт аварийно завершился: {e}{Colors.ENDC}"
    finally:
        print(f"\n{final_status}", flush=True)
        print(f"\n{Colors.BOLD}{Symbols.FLAG} Скрипт завершил работу.{Colors.ENDC}", flush=True)