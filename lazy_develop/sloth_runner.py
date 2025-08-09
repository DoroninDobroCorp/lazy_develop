# Файл: sloth_runner.py
import subprocess
import platform
import re
import hashlib
import os
from colors import Colors

def get_file_hash(filepath):
    """Вычисляет SHA256 хэш файла."""
    if not os.path.exists(filepath) or os.path.isdir(filepath): return None
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()

def execute_commands(commands_str):
    """
    Выполняет блок shell-команд.
    Возвращает кортеж: (success, failed_command, error_message)
    """
    print(f"{Colors.OKBLUE}  [Детали] Запуск выполнения блока команд...{Colors.ENDC}")

    # ИЗМЕНЕНО: Более надежный способ поиска путей, включая те, что в кавычках
    filepaths = re.findall(r'[\'"]?([a-zA-Z0-9_\-\.\/]+)[\'"]?', commands_str)
    
    # Собираем информацию о состоянии ДО выполнения команд
    hashes_before = {fp: get_file_hash(fp) for fp in filepaths if os.path.isfile(fp)}
    dirs_before = {fp for fp in filepaths if os.path.isdir(fp)}
    files_before = {fp for fp in filepaths if os.path.exists(fp)} # Все пути, включая папки
    
    try:
        is_macos = platform.system() == "Darwin"
        # Для macOS добавляем флаг .bak для sed -i, чтобы он работал как в Linux
        commands_str_adapted = re.sub(r"sed -i ", "sed -i '.bak' ", commands_str) if is_macos else commands_str
        full_command = f"set -e\n{commands_str_adapted}"

        print(f"{Colors.WARNING}⚡️ ЛОГ: Выполняю блок команд (bash, set -e)...{Colors.ENDC}")
        result = subprocess.run(['bash', '-c', full_command], capture_output=True, text=True, encoding='utf-8')

        if result.returncode != 0:
            error_msg = f"Команда завершилась с ненулевым кодом выхода ({result.returncode}).\nОшибка (STDERR): {result.stderr.strip()}"
            print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА при выполнении блока команд.\n{error_msg}{Colors.ENDC}")
            return False, commands_str, result.stderr.strip() or "Команда провалилась без вывода в stderr."

        if result.stderr:
            print(f"{Colors.WARNING}⚠️  ПРЕДУПРЕЖДЕНИЕ (STDERR от успешной команды):\n{result.stderr.strip()}{Colors.ENDC}")

        # Удаляем временные файлы .bak, созданные sed на macOS
        if is_macos:
            subprocess.run("find . -name '*.bak' -delete", shell=True, check=True, capture_output=True)

        # --- НОВАЯ, БОЛЕЕ НАДЕЖНАЯ ПРОВЕРКА ИЗМЕНЕНИЙ ---
        hashes_after = {fp: get_file_hash(fp) for fp in hashes_before.keys()}
        files_after = {fp for fp in filepaths if os.path.exists(fp)}

        # Проверяем, изменился ли хэш у существующих файлов
        modified_files = any(hashes_before.get(fp) != hashes_after.get(fp) for fp in hashes_before)
        # Проверяем, появились ли новые файлы или папки
        created_paths = files_after - files_before
        
        if not modified_files and not created_paths:
            # Если ничего не изменилось и не создалось - это ошибка логики
            error_msg = ("Команда выполнилась успешно, но не изменила и не создала ни одного файла или папки. "
                         "Вероятно, шаблон (например, в sed) не был найден или путь к файлу неверен.")
            final_error_message = result.stderr.strip() if result.stderr else error_msg
            print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА ЛОГИКИ: {error_msg}{Colors.ENDC}")
            if result.stderr:
                print(f"Причина из STDERR: {final_error_message}")
            return False, commands_str, final_error_message

        # Если были изменения или создания, все хорошо
        if modified_files:
            print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен. Файлы были изменены.{Colors.ENDC}")
        if created_paths:
            print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен. Были созданы новые пути: {', '.join(created_paths)}{Colors.ENDC}")
            
        return True, None, None

    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Непредвиденная ОШИБКА в исполнителе: {e}{Colors.ENDC}")
        return False, commands_str, str(e)