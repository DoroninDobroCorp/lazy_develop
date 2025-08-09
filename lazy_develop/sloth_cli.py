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

from colors import Colors
import sloth_core
import sloth_runner
import context_collector

# --- КОНСТАНТЫ ИНТЕРФЕЙСА ---
MAX_ITERATIONS = 20
HISTORY_FILE_NAME = 'sloth_history.json'
RUN_LOG_FILE_NAME = 'sloth_run.log'

def calculate_cost(model_name, input_tokens, output_tokens):
    pricing_info = sloth_core.MODEL_PRICING.get(model_name)
    if not pricing_info: return 0.0
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
    print(f"{Colors.CYAN}🔄 ЛОГ: Обновляю контекст проекта...{Colors.ENDC}")
    try:
        if is_fast_mode:
            context_data = context_collector.gather_project_context(os.getcwd(), mode='full')
        else:
            mode = 'summarized'
            context_data = context_collector.gather_project_context(os.getcwd(), mode=mode, full_content_files=files_to_include_fully)
        print(f"{Colors.OKGREEN}✅ ЛОГ: Контекст успешно обновлен. Размер: {len(context_data)} символов.{Colors.ENDC}")
        return context_data
    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА в get_project_context: {e}{Colors.ENDC}")
        return None

def _log_run(log_file_path, title, content):
    try:
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "="*80 + "\n" + f"{title}\n" + "-"*80 + "\n")
            f.write(str(content if content is not None else "<empty>") + "\n")
    except Exception as e:
        print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ: Не удалось записать в {log_file_path}: {e}{Colors.ENDC}")

def _read_multiline_input(prompt):
    print(prompt)
    lines = []
    empty_line_count = 0
    while empty_line_count < 3:
        try:
            line = input()
            if line: lines.append(line); empty_line_count = 0
            else: empty_line_count += 1
        except EOFError: break
    return '\n'.join(lines).strip()

def get_user_input():
    goal_prompt = (f"{Colors.HEADER}{Colors.BOLD}👋 Привет! Опиши свою основную цель.{Colors.ENDC}\n"
                   f"{Colors.CYAN}💡 (Для завершения ввода, нажми Enter 3 раза подряд){Colors.ENDC}")
    user_goal = _read_multiline_input(goal_prompt)
    if not user_goal: return None, None
    log_prompt = (f"\n{Colors.HEADER}{Colors.BOLD}👍 Отлично. Теперь, если есть лог ошибки, вставь его. Если нет, просто нажми Enter 3 раза.{Colors.ENDC}")
    error_log = _read_multiline_input(log_prompt)
    return user_goal, error_log

def extract_block(tag, text):
    """Извлекает содержимое блока из текста, например
