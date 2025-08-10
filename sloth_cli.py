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
import uuid

from colors import Colors, Symbols
import sloth_core
import sloth_runner
import context_collector
import config as sloth_config

# --- КОНСТАНТЫ ИНТЕРФЕЙСА ---
MAX_ITERATIONS = 20
HISTORY_FILE_NAME = 'sloth_history.json'
RUN_LOG_FILE_NAME = 'sloth_run.log'
# Базовая стартовая папка выбора проекта (уменьшает количество кликов)
# Может быть переопределена в конфиге: paths.default_start_dir
DEFAULT_START_DIR = '/Users/vladimirdoronin/VovkaNowEngineer'

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

def extract_block(tag, text):
    """Извлекает первый блок вида ```{tag}\n...\n``` или сигнальный блок ```{tag}```."""
    lines = text.splitlines()
    start_idx = None
    fence_prefix = f"```{tag}"
    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if stripped_line.startswith(fence_prefix):
            # Обрабатываем только самозакрывающиеся "сигнальные" теги, например ```verify_run```.
            # Обычный открывающий тег (```plan, ```files, ```write_file ...) не должен считаться сигнальным.
            if stripped_line == f"{fence_prefix}```":
                return ""  # Сигнал найден, содержимого нет
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Старая логика для блоков с содержимым остаётся корректной
    for j in range(start_idx, len(lines)):
        if lines[j].strip() == "```":
            return "\n".join(lines[start_idx:j]).strip()
    return None  # Блок был открыт, но не закрыт

_ALLOWED_TAGS_AFTER_FENCE = {"summary","bash","manual","files","plan","clarification","done_summary","write_file","verify_run"}

def _parse_write_file_header(header_line: str):
    header = header_line.strip()
    if header.startswith("```write_file"):
        header = header[len("```write_file"):].strip()
    path, boundary = "", None
    m = re.search(r'boundary\s*=\s*"([^"]+)"', header) or re.search(r'boundary\s*=\s*([^\s]+)', header)
    if m: boundary = m.group(1).strip().strip('"').strip("'")
    p = re.search(r'path\s*=\s*"([^"]+)"', header) or re.search(r'path\s*=\s*([^\s]+)', header)
    if p: path = p.group(1).strip().strip('"').strip("'")
    else:
        for tok in header.split():
            if "=" not in tok:
                path = tok.strip().strip('"').strip("'"); break
    return path, boundary

def _iter_write_file_blocks(answer_text: str, boundary_token: str):
    lines, i, n = answer_text.splitlines(), 0, len(answer_text.splitlines())
    while i < n:
        ln = lines[i].strip()
        if ln.startswith("```write_file"):
            filepath, boundary = _parse_write_file_header(ln)
            i += 1
            content = []
            if boundary:  # главный путь: читаем до строки-границы
                while i < n and lines[i].strip() != boundary:
                    content.append(lines[i]); i += 1
                if i < n and lines[i].strip() == boundary: i += 1
                if i < n and lines[i].strip() == "```": i += 1
                yield filepath, "\n".join(content); continue
            # fallback: закрытие только если после ``` реально начинается новый блок
            while i < n:
                if lines[i].strip() == "```":
                    j = i + 1
                    while j < n and lines[j].strip() == "": j += 1
                    if j >= n: break
                    nxt = lines[j].strip()
                    if nxt.startswith("```"): break
                    if any(nxt.startswith(t) or nxt.startswith(f"```{t}") for t in _ALLOWED_TAGS_AFTER_FENCE):
                        break
                    content.append(lines[i]); i += 1; continue
                content.append(lines[i]); i += 1
            if i < n and lines[i].strip() == "```": i += 1
            yield filepath, "\n".join(content); continue
        i += 1

def _normalize_model_path(p: str) -> str:
    p = (p or "").strip().strip('"').strip("'").replace("\\","/")
    if p.startswith("./"): p = p[2:]
    cwd = os.getcwd(); root = os.path.basename(cwd.rstrip(os.sep))
    cwd_posix = cwd.replace("\\","/").rstrip("/")
    if p.startswith("/"):
        if p.startswith(cwd_posix + "/"): p = p[len(cwd_posix)+1:]
        else: p = p.lstrip("/")
    if p.startswith(root + "/"): p = p[len(root)+1:]
    p = os.path.normpath(p).replace("\\","/")
    if p.startswith("../"): p = p[3:]
    if p == ".": p = ""
    return p

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

def main(is_fix_mode, is_fast_mode, history_file_path, run_log_file_path, verify_timeout_seconds=15, log_trim_limit=20000):
    # Модель инициализируется в точке входа до вызова этой функции.
    model_instance, active_service = sloth_core.get_active_service_details()
    if not model_instance:
        # Этот проверка - мера предосторожности, основная точка входа уже должна была это проверить.
        return f"{Colors.FAIL}Не удалось получить данные об инициализированной модели. Выход.{Colors.ENDC}"

    total_start_time = time.time()
    timings = {'context': 0.0, 'model': 0.0, 'commands': 0.0, 'verify': 0.0}
    total_cost, cost_log = 0.0, []

    user_goal, error_log = get_user_input()
    if not user_goal:
        return f"{Colors.WARNING}Цель не была указана. Завершение работы.{Colors.ENDC}"
    initial_task = user_goal + (f"\n\n--- ЛОГ ОШИБКИ ---\n{error_log}" if error_log else "")
    
    attempt_history, final_message = [], ""
    state = "EXECUTION" if is_fast_mode else "PLANNING"
    iteration_count, files_to_include_fully, current_prompt = 1, None, None
    current_prompt_type = None  # one of: planning, initial, review, error_fix, log_analysis

    # Генерируем уникальный токен-границу для write_file
    BOUNDARY_TOKEN = f"SLOTH_BOUNDARY_{uuid.uuid4().hex}"

    # --- Конфигурация verify_command (спросить ОДИН раз за сессию, только в интеллектуальном режиме) ---
    verify_command = None
    try:
        if os.path.exists(history_file_path):
            with open(history_file_path, 'r', encoding='utf-8') as f:
                _hist = json.load(f)
        else:
            _hist = {}
        last_cfg = (_hist.get("last_run_config") or {})
        verify_command = last_cfg.get("verify_command")
        if not is_fast_mode and verify_command is None:
            print(f"{Colors.OKBLUE}Вопрос: Какую команду использовать для запуска и проверки проекта (например, 'npm run dev' или 'pytest')? Если автоматическая проверка не нужна, просто нажмите Enter.{Colors.ENDC}", flush=True)
            try:
                verify_command = input().strip()
            except EOFError:
                verify_command = ""
            # Сохраняем ответ (даже пустой), чтобы больше не спрашивать
            last_cfg["verify_command"] = verify_command
            _hist["last_run_config"] = last_cfg
            with open(history_file_path, 'w', encoding='utf-8') as f:
                json.dump(_hist, f, indent=2, ensure_ascii=False)
            print(f"{Colors.CYAN}{Symbols.SAVE} Команда верификации сохранена в историю сессии.{Colors.ENDC}", flush=True)
    except Exception as e:
        print(f"{Colors.WARNING}{Symbols.WARNING}  ПРЕДУПРЕЖДЕНИЕ: Не удалось обработать verify_command: {e}{Colors.ENDC}", flush=True)

    while iteration_count <= MAX_ITERATIONS:
        model_instance, active_service = sloth_core.get_active_service_details()

        if state == "PLANNING":
            print(f"\n{Colors.BOLD}{Colors.HEADER}--- ЭТАП: ПЛАНИРОВАНИЕ ---{Colors.ENDC}", flush=True)
            project_context, duration = get_project_context(is_fast_mode=False, files_to_include_fully=None)
            timings['context'] += duration
            if not project_context:
                return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить контекст проекта.{Colors.ENDC}"
            current_prompt = sloth_core.get_clarification_and_planning_prompt(project_context, initial_task, boundary=BOUNDARY_TOKEN)
            current_prompt_type = "planning"
        
        elif state == "EXECUTION" and current_prompt is None:
            project_context, duration = get_project_context(is_fast_mode, files_to_include_fully)
            timings['context'] += duration
            if not project_context:
                return f"{Colors.FAIL}КРИТИЧЕСКАЯ ОШИБКА: Не удалось обновить контекст.{Colors.ENDC}"
            current_prompt = sloth_core.get_initial_prompt(
                project_context, initial_task,
                sloth_core.get_active_service_details() and (load_fix_history(history_file_path) if is_fix_mode else None),
                boundary=BOUNDARY_TOKEN
            )
            current_prompt_type = "initial"
            
        log_iter = iteration_count if state == "EXECUTION" else 0
        if state == "EXECUTION":
            print(f"\n{Colors.BOLD}{Colors.HEADER}{Symbols.ROCKET} --- ЭТАП: ИСПОЛНЕНИЕ | ИТЕРАЦИЯ {iteration_count}/{MAX_ITERATIONS} ---{Colors.ENDC}", flush=True)
        
        _log_run(run_log_file_path, f"ЗАПРОС (Состояние: {state}, Итерация: {log_iter})", current_prompt)
        print(f"{Colors.CYAN}{Symbols.SPINNER} Думаю...{Colors.ENDC}", end='\r', flush=True)
        start_model_time = time.time()
        answer_data = sloth_core.send_request_to_model(model_instance, active_service, current_prompt, log_iter)
        model_duration = time.time() - start_model_time
        timings['model'] += model_duration
        
        if not answer_data:
            if sloth_core.model:
                print(f"{Colors.WARNING}🔄 ЛОГ: Ответ от модели не получен, пробую снова...{Colors.ENDC}", flush=True)
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
        print(f"{Colors.GREY}📊 Статистика: Вход: {answer_data['input_tokens']} т., Выход: {answer_data['output_tokens']} т. | Время: {model_duration:.2f} сек. | Стоимость: ~${cost:.6f}{' '*10}{Colors.ENDC}", flush=True)

        if state == "PLANNING":
            clarification = extract_block("clarification", answer_text)
            if clarification:
                print(f"{Colors.HEADER}{Colors.BOLD}🤖 Модель просит уточнений:{Colors.ENDC}\n{Colors.CYAN}{clarification}{Colors.ENDC}", flush=True)
                user_response = _read_multiline_input("Пожалуйста, предоставьте ответ на вопросы модели. (Enter 3 раза для завершения)")
                initial_task += f"\n\n--- УТОЧНЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ ---\n{user_response}"
                current_prompt = None
                continue

            plan = extract_block("plan", answer_text)
            files_list_str = extract_block("files", answer_text)
            if plan and files_list_str:
                print(f"{Colors.OKGREEN}✅ Задача понятна. План получен.{Colors.ENDC}\n{Colors.HEADER}План действий:{Colors.ENDC}\n{Colors.CYAN}{plan}{Colors.ENDC}", flush=True)
                with open("sloth_plan.txt", "w", encoding='utf-8') as f:
                    f.write(plan)
                print(f"{Colors.OKGREEN}План сохранен в 'sloth_plan.txt'.{Colors.ENDC}", flush=True)
                raw_files_list = [line.strip() for line in files_list_str.split('\n') if line.strip()]
                project_root_name = os.path.basename(os.getcwd()) + os.sep
                files_to_include_fully = []
                for f_path in raw_files_list:
                    if f_path.startswith(project_root_name):
                        normalized_path = f_path[len(project_root_name):]
                        files_to_include_fully.append(normalized_path)
                        print(f"{Colors.GREY}ℹ️  Путь нормализован: '{f_path}' -> '{normalized_path}'{Colors.ENDC}", flush=True)
                    else:
                        files_to_include_fully.append(f_path)
                print(f"{Colors.HEADER}Запрошены полные версии файлов:{Colors.ENDC}\n{Colors.CYAN}" + "\n".join(files_to_include_fully) + Colors.ENDC, flush=True)
                state = "EXECUTION"
                current_prompt = None
                current_prompt_type = None
                continue
            else:
                print(f"{Colors.WARNING}⚠️ Модель не вернула ни уточнений, ни плана. Пробуем снова...{Colors.ENDC}", flush=True)
                time.sleep(5)
                continue

        elif state == "EXECUTION":
            if extract_block("done_summary", answer_text) or answer_text.strip().upper().startswith("ГОТОВО"):
                # ИСПРАВЛЕНО: Убираем строгую проверку. Если AI прислал done_summary, считаем задачу выполненной.
                # Это предотвращает бесконечный цикл, когда AI уверен в решении после этапа обзора.
                done_summary = extract_block("done_summary", answer_text) or "Задача выполнена."
                final_message = f"{Colors.OKGREEN}{Symbols.CHECK} Задача выполнена успешно! (за {iteration_count} итераций){Colors.ENDC}"
                update_history_with_attempt(history_file_path, user_goal, done_summary)
                print(f"{Colors.OKGREEN}📄 ИТОГОВОЕ РЕЗЮМЕ:\n{Colors.CYAN}{done_summary}{Colors.ENDC}", flush=True)
                manual_steps = extract_block("manual", answer_text)
                if manual_steps:
                    final_message += f"\n\n{Colors.WARNING}✋ ТРЕБУЮТСЯ РУЧНЫЕ ДЕЙСТВИЯ:{Colors.ENDC}\n{manual_steps}"
                break
            
            # --- ОБРАБОТКА ДЕЙСТВИЙ: write_file (мульти-блоки) или bash ---
            commands_to_run = extract_block("bash", answer_text)
            write_blocks = list(_iter_write_file_blocks(answer_text, boundary_token=BOUNDARY_TOKEN))
            strategy_description = extract_block("summary", answer_text) or "Стратегия не описана"
            verify_run_present = (extract_block("verify_run", answer_text) is not None)
            
            action_taken, success, failed_command, error_message = False, False, "N/A", ""

            if write_blocks:
                action_taken = True
                for raw_filepath, content in write_blocks:
                    try:
                        filepath = _normalize_model_path(raw_filepath)
                        print(f"\n{Colors.OKBLUE}📝 Найден блок write_file. Перезаписываю файл: {filepath}{Colors.ENDC}", flush=True)
                        dir_name = os.path.dirname(filepath)
                        if dir_name:
                            os.makedirs(dir_name, exist_ok=True)
                        # Пишем БЕЗ strip(), С РОВНО ТЕМ СОДЕРЖИМЫМ, ЧТО ПРИШЛО
                        # Жёсткий сэндбокс: запись только внутри корня проекта
                        abs_path = os.path.realpath(filepath)
                        root_abs = os.path.realpath(os.getcwd())
                        if not abs_path.startswith(root_abs + os.sep):
                            raise RuntimeError(f"Запрещён путь вне корня проекта: {filepath}")
                        with open(filepath, "w", encoding="utf-8", newline="") as f:
                            f.write(content)
                        print(f"{Colors.OKGREEN}✅ Файл успешно перезаписан: {filepath}{Colors.ENDC}", flush=True)
                        success = True
                    except Exception as e:
                        print(f"{Colors.FAIL}❌ ОШИБКА при записи файла '{raw_filepath}': {e}{Colors.ENDC}", flush=True)
                        success = False
                        failed_command = f"write_file {raw_filepath}"
                        error_message = str(e)
                        break  # прекращаем последовательность, чтобы вернуть ошибку корректно

            elif commands_to_run:
                action_taken = True
                print(f"\n{Colors.OKBLUE}🔧 Найден блок shell-команд. Выполняю...{Colors.ENDC}", flush=True)
                start_cmd_time = time.time()
                success, failed_command, error_message = sloth_runner.execute_commands(commands_to_run)
                cmd_duration = time.time() - start_cmd_time
                timings['commands'] += cmd_duration
                print(f"{Colors.GREY}ℹ️  Команды выполнены за {cmd_duration:.2f} сек.{Colors.ENDC}", flush=True)

            if not action_taken:
                print(f"{Colors.FAIL}❌ ЛОГ: Модель не вернула команд. Пробую на следующей итерации.{Colors.ENDC}", flush=True)
                project_context, duration = get_project_context(is_fast_mode, files_to_include_fully)
                timings['context'] += duration
                current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history, boundary=BOUNDARY_TOKEN)
                current_prompt_type = "review"
                iteration_count += 1
                continue
            
            project_context, duration = get_project_context(is_fast_mode, files_to_include_fully)
            timings['context'] += duration
            if not project_context:
                final_message = f"{Colors.FAIL}Критическая ошибка: не удалось обновить контекст.{Colors.ENDC}"
                break

            history_entry = f"**Итерация {iteration_count}:**\n**Стратегия:** {strategy_description}\n"
            if success:
                history_entry += "**Результат:** УСПЕХ"
                # Если ИИ запросил верификацию и задана команда — запускаем проект и собираем логи
                if verify_run_present and (verify_command or verify_command == ""):
                    if verify_command:
                        print(f"{Colors.OKBLUE}🧪 Запускаю команду верификации на {verify_timeout_seconds} сек: {verify_command}{Colors.ENDC}", flush=True)
                        start_verify_time = time.time()
                        try:
                            proc = subprocess.Popen(verify_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                            try:
                                stdout, stderr = proc.communicate(timeout=verify_timeout_seconds)
                                rc = proc.returncode
                            except subprocess.TimeoutExpired:
                                print(f"{Colors.CYAN}{Symbols.INFO}  Процесс верификации работал до таймаута, как и ожидалось для dev-сервера.{Colors.ENDC}", flush=True)
                                proc.kill()
                                stdout, stderr = proc.communicate()
                                rc = proc.returncode if proc.returncode is not None else 124
                                # stderr больше не помечаем как ошибку, а просто передаем как есть
                        except Exception as e:
                            stdout, stderr, rc = "", f"Ошибка запуска verify_command: {e}", -1
                        
                        verify_duration = time.time() - start_verify_time
                        timings['verify'] += verify_duration

                        # Обрезаем логи, чтобы не раздувать промпт
                        def _trim(s, lim=log_trim_limit):
                            if not s:
                                return ""
                            return (s[:lim] + "\n...[TRIMMED]...") if len(s) > lim else s
                        logs_collected = f"$ {verify_command}\n(exit={rc})\n\n[STDOUT]\n{_trim(stdout)}\n\n[STDERR]\n{_trim(stderr)}"
                        _log_run(run_log_file_path, "ЛОГИ ВЕРИФИКАЦИИ", logs_collected)
                        # Готовим промпт для анализа логов
                        attempts_str = "\n---\n".join(attempt_history) if attempt_history else ""
                        current_prompt = sloth_core.get_log_analysis_prompt(project_context, user_goal, attempts_str, logs_collected, boundary=BOUNDARY_TOKEN)
                        current_prompt_type = "log_analysis"
                    else:
                        print(f"{Colors.GREY}{Symbols.INFO} Блок verify_run обнаружен, но команда верификации не задана. Пропускаю запуск.{Colors.ENDC}", flush=True)
                        current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history, boundary=BOUNDARY_TOKEN)
                        current_prompt_type = "review"
                else:
                    current_prompt = sloth_core.get_review_prompt(project_context, user_goal, iteration_count + 1, attempt_history, boundary=BOUNDARY_TOKEN)
                    current_prompt_type = "review"
            else:
                history_entry += f"**Результат:** ПРОВАЛ\n**Ошибка:** {error_message}"
                current_prompt = sloth_core.get_error_fixing_prompt(
                    failed_command, error_message, user_goal, project_context, iteration_count + 1, attempt_history, boundary=BOUNDARY_TOKEN
                )
                current_prompt_type = "error_fix"
            
            attempt_history.append(history_entry)
            iteration_count += 1
    
    if not final_message:
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

    # --- 1. Инициализация модели ---
    sloth_core.initialize_model()
    model_instance, _ = sloth_core.get_active_service_details()
    if not model_instance:
        print(f"{Colors.FAIL}❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать модель. "
              f"Проверьте API-ключ или настройки соединения. Завершение работы.{Colors.ENDC}", flush=True)
        sys.exit(1)
    print(f"{Colors.OKGREEN}✅ Модель AI успешно инициализирована.{Colors.ENDC}\n", flush=True)

    # --- 2. Определение пути к проекту ---
    history_file_path = os.path.join(SLOTH_SCRIPT_DIR, HISTORY_FILE_NAME)
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
            print(f"{Colors.OKBLUE}Пожалуйста, выберите папку проекта в открывшемся окне...{Colors.ENDC}", flush=True)
            root = Tk(); root.withdraw()
            # Используем стартовую папку из конфига (fallback на DEFAULT_START_DIR), если не валидна — домашняя директория
            _cfg_start = sloth_config.get("paths.default_start_dir", DEFAULT_START_DIR)
            _start_dir = _cfg_start if os.path.isdir(_cfg_start) else os.path.expanduser("~")
            target_project_path = filedialog.askdirectory(title="Выберите папку проекта для Sloth", initialdir=_start_dir)
            root.destroy()
        if not target_project_path:
            print(f"{Colors.BOLD}{Colors.FAIL}{Symbols.CROSS} Папка проекта не была выбрана.{Colors.ENDC}", flush=True)
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
    run_log_file_path = os.path.join(SLOTH_SCRIPT_DIR, RUN_LOG_FILE_NAME)
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