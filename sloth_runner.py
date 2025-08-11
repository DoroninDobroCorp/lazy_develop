# Файл: sloth_runner.py
import subprocess
import platform
import re
import hashlib
import os
from colors import Colors

# --- БЕЛЫЙ СПИСОК КОМАНД ---
# Синхронизирован со списком в prompt (см. sloth_core.py)
ALLOWED_COMMANDS = (
    "rm", "mv", "touch", "mkdir", "npm", "npx", "yarn", "pnpm", "git", "echo", "./",
    # Расширение для миграций и современных менеджеров
    "prisma", "bunx", "bun"
)

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

def _adapt_commands_for_project_root(s: str) -> str:
    cwd = os.getcwd(); root = os.path.basename(cwd.rstrip(os.sep))
    root_posix = cwd.replace("\\","/").rstrip("/")
    s = re.sub(r'^' + re.escape(root + "/"), '', s, flags=re.MULTILINE)
    s = re.sub(r'([ \t\'"])' + re.escape(root + "/"), r'\1', s)
    s = re.sub(r'^' + re.escape(root_posix + "/"), '', s, flags=re.MULTILINE)
    s = re.sub(r'([ \t\'"])' + re.escape(root_posix + "/"), r'\1', s)
    return s

def execute_commands(commands_str):
    """
    Выполняет блок shell-команд.
    Возвращает кортеж: (success, failed_command, error_message, changed_files, created_paths)
    """
    print(f"{Colors.OKBLUE}  [Детали] Запуск выполнения блока команд...{Colors.ENDC}")

    # --- ВАЛИДАЦИЯ БЕЗОПАСНОСТИ ---
    commands_to_run = [cmd.strip() for cmd in commands_str.strip().split('\n') if cmd.strip()]
    # Разрешаем также безопасный паттерн: `cd <подпапка> && <разрешённая команда>`
    allowed_prefixes = ALLOWED_COMMANDS
    allowed_regex = re.compile(r'^cd\s+([A-Za-z0-9_\-\./]+)\s*&&\s*(' + '|'.join(map(re.escape, allowed_prefixes)) + r')\b')

    def _is_safe_cd_and_run(cmd: str) -> bool:
        m = allowed_regex.match(cmd)
        if not m:
            return False
        subdir = m.group(1)
        # Без абсолютных путей, без обратных слэшей и без переходов наверх
        if subdir.startswith('/') or '\\' in subdir:
            return False
        # Нормализуем и проверяем на '..'
        parts = [p for p in subdir.split('/') if p not in ('', '.')]
        if any(p == '..' for p in parts):
            return False
        return True

    def _is_allowed(cmd: str) -> bool:
        if any(cmd.startswith(p) for p in allowed_prefixes):
            return True
        if _is_safe_cd_and_run(cmd):
            return True
        return False

    for command in commands_to_run:
        if not _is_allowed(command):
            error_msg = (
                f"Опасная команда заблокирована: '{command}'. Разрешены только: "
                + ", ".join(ALLOWED_COMMANDS)
                + " и паттерн 'cd <subdir> && <разрешённая команда>'"
            )
            print(f"{Colors.FAIL}❌ ЛОГ: {error_msg}{Colors.ENDC}")
            return False, commands_str, error_msg, set(), set()

    # ИЗМЕНЕНО: Более надежный способ поиска путей, включая те, что в кавычках
    filepaths = re.findall(r'[\'"]?([a-zA-Z0-9_\-\.\/]+)[\'"]?', commands_str)
    
    # Собираем информацию о состоянии ДО выполнения команд
    hashes_before = {fp: get_file_hash(fp) for fp in filepaths if os.path.isfile(fp)}
    dirs_before = {fp for fp in filepaths if os.path.isdir(fp)}
    files_before = {fp for fp in filepaths if os.path.exists(fp)} # Все пути, включая папки
    
    try:
        is_macos = platform.system() == "Darwin"
        # Чистим возможные префиксы корня проекта в путях
        commands_str_fixed = _adapt_commands_for_project_root(commands_str)
        # Для macOS добавляем флаг .bak для sed -i, чтобы он работал как в Linux
        commands_str_adapted = re.sub(r"sed -i ", "sed -i '.bak' ", commands_str_fixed) if is_macos else commands_str_fixed
        full_command = f"set -e\n{commands_str_adapted}"

        print(f"{Colors.WARNING}⚡️ ЛОГ: Выполняю блок команд (bash, set -e)...{Colors.ENDC}")
        result = subprocess.run(['bash', '-c', full_command], capture_output=True, text=True, encoding='utf-8')

        if result.returncode != 0:
            error_msg = f"Команда завершилась с ненулевым кодом выхода ({result.returncode}).\nОшибка (STDERR): {result.stderr.strip()}"
            print(f"{Colors.FAIL}❌ ЛОГ: КРИТИЧЕСКАЯ ОШИБКА при выполнении блока команд.\n{error_msg}{Colors.ENDC}")
            return False, commands_str, result.stderr.strip() or "Команда провалилась без вывода в stderr.", set(), set()

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
        changed_files = {fp for fp in hashes_before.keys() if hashes_before.get(fp) != hashes_after.get(fp)}
        
        if not modified_files and not created_paths:
            # Если ничего не изменилось и не создалось - это ошибка логики
            error_msg = ("Команда выполнилась успешно, но не изменила и не создала ни одного файла или папки. "
                         "Вероятно, шаблон (например, в sed) не был найден или путь к файлу неверен.")
            final_error_message = result.stderr.strip() if result.stderr else error_msg
            print(f"{Colors.FAIL}❌ ЛОГ: ОШИБКА ЛОГИКИ: {error_msg}{Colors.ENDC}")
            if result.stderr:
                print(f"Причина из STDERR: {final_error_message}")
            return False, commands_str, final_error_message, set(), set()

        # Если были изменения или создания, все хорошо
        if modified_files:
            print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен. Файлы были изменены.{Colors.ENDC}")
        if created_paths:
            print(f"{Colors.OKGREEN}✅ ЛОГ: Блок команд успешно выполнен. Были созданы новые пути: {', '.join(created_paths)}{Colors.ENDC}")
            
        return True, None, None, changed_files, created_paths

    except Exception as e:
        print(f"{Colors.FAIL}❌ ЛОГ: Непредвиденная ОШИБКА в исполнителе: {e}{Colors.ENDC}")
        return False, commands_str, str(e), set(), set()