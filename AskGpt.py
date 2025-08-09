#!/usr/bin/env python3
import os

# --- Настройки ---
MAX_CHARS = 7500000
OUTPUT_PREFIX = "message_"
FINISH_INSTRUCTION = "ГПТ, Я ЕЩЕ НЕ ЗАКОНЧИЛ - ПРОСТО КОРОТКО ОТВЕТЬ ОК И ВСЕ!!!"
BASE_DIR = os.getcwd()
TOP_N_FILES = 3

# --- Списки игнорирования ---

# Папки, названия которых НАЧИНАЮТСЯ с этих префиксов, будут проигнорированы.
USER_IGNORE_DIR_PREFIXES = "parse_"

# Папки для полного игнорирования (через запятую).
USER_IGNORE_DIRS = (
    "venv, .venv, __pycache__, .pytest_cache, *.egg-info, "
    "node_modules, .next, dist, build, coverage, "
    ".git, .idea, .vscode, .claude, "
    "logs"
)

# Расширения файлов для игнорирования.
USER_IGNORE_EXTENSIONS = ".png, .jpeg, .jpg"

# Конкретные файлы для игнорирования.
USER_IGNORE_FILES = (
    "go.mod, go.sum, go.work, go.work.sum, "
    "package-lock.json, yarn.lock, "
    ".DS_Store, .gitignore, README.md, Makefile, Dockerfile, "
    "analyzer_wide, tsconfig.tsbuildinfo, chat_sender.py, chat_sender_g.py, "
    "sloth.py, sloth_debug_prompt.txt, sloth_debug_bad_response.txt"
)

# Файлы-исключения для обязательного включения.
USER_INCLUDE_FILES = ""  # "important-script.js"

# --- Инициализация множеств для быстрой проверки ---
SCRIPT_NAME_LOWER = os.path.basename(__file__).lower()
IGNORE_FILES_SET = {name.strip().lower() for name in "".join(USER_IGNORE_FILES).split(",") if name.strip()}
IGNORE_DIRS_SET = {name.strip().lower() for name in "".join(USER_IGNORE_DIRS).split(",") if name.strip()}
IGNORE_EXTENSIONS_SET = {ext.strip().lower() for ext in USER_IGNORE_EXTENSIONS.split(",") if ext.strip()}
INCLUDE_FILES_SET = {name.strip().lower() for name in USER_INCLUDE_FILES.split(",") if name.strip()}
IGNORE_DIR_PREFIXES_SET = {prefix.strip().lower() for prefix in USER_IGNORE_DIR_PREFIXES.split(",") if prefix.strip()}


def should_ignore_dir(dirname):
    """Проверяет, следует ли игнорировать папку по имени или префиксу."""
    lower_dirname = dirname.lower()
    if lower_dirname in IGNORE_DIRS_SET:
        return True
    if any(lower_dirname.startswith(prefix) for prefix in IGNORE_DIR_PREFIXES_SET):
        return True
    return False


def should_ignore_file(filepath):
    """
    Проверяет, следует ли игнорировать файл.
    Принимает полный путь для проверки дополнительных правил (например, для Go).
    """
    filename = os.path.basename(filepath)
    lower_filename = filename.lower()

    if lower_filename in INCLUDE_FILES_SET:
        return False
    if lower_filename == SCRIPT_NAME_LOWER:
        return True
    if lower_filename in IGNORE_FILES_SET:
        return True
    if IGNORE_EXTENSIONS_SET and any(lower_filename.endswith(ext) for ext in IGNORE_EXTENSIONS_SET):
        return True

    # НОВОЕ ПРАВИЛО: Игнорировать исполняемые файлы Go.
    # Проверяем, что у файла нет расширения.
    if '.' not in filename:
        # Получаем имя родительской папки.
        parent_dir_name = os.path.basename(os.path.dirname(filepath))
        # Если имя файла совпадает с именем папки, игнорируем его.
        if filename.lower() == parent_dir_name.lower():
            return True

    return False


def get_file_content(filepath):
    """Безопасно читает текстовое содержимое файла."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def calculate_sizes(root):
    """
    Вычисляет размеры файлов и папок за один проход, корректно фильтруя игнорируемые элементы.
    """
    file_sizes = {}
    dir_sizes = {}
    all_valid_paths = []

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Фильтруем папки, чтобы os.walk не спускался в них.
        dirnames[:] = [d for d in dirnames if not should_ignore_dir(d)]

        current_dir_size = 0
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            # Теперь передаем полный путь в функцию проверки.
            if should_ignore_file(filepath):
                continue

            content = get_file_content(filepath)
            if content is not None:
                size = len(content)
                file_sizes[filepath] = size
                current_dir_size += size
                all_valid_paths.append(filepath)

        dir_sizes[dirpath] = current_dir_size

    # Агрегируем размеры от дочерних папок к родительским.
    sorted_dirs = sorted(dir_sizes.keys(), key=lambda x: x.count(os.sep), reverse=True)
    for path in sorted_dirs:
        parent = os.path.dirname(path)
        if parent in dir_sizes and parent != path:
            dir_sizes[parent] += dir_sizes[path]

    return file_sizes, dir_sizes, all_valid_paths


def build_tree(root, file_sizes, dir_sizes, top_files_set):
    """Строит строковое представление дерева проекта."""
    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Повторяем фильтрацию для консистентности вывода дерева.
        dirnames[:] = [d for d in dirnames if not should_ignore_dir(d)]

        rel_path = os.path.relpath(dirpath, root)
        depth = 0 if rel_path == '.' else rel_path.count(os.sep) + 1
        indent = "  " * depth

        dir_size = dir_sizes.get(dirpath, 0)
        folder_name = os.path.basename(dirpath) if rel_path != '.' else os.path.basename(root)
        tree_lines.append(f"{indent}[DIR] {folder_name}/ ({dir_size} chars)")

        sub_indent = "  " * (depth + 1)
        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            if should_ignore_file(filepath):
                continue

            file_size = file_sizes.get(filepath, 0)
            prefix = "!!!" if filepath in top_files_set else ""
            tree_lines.append(f"{sub_indent}{prefix}[FILE] {filename} ({file_size} chars)")

    return "\n".join(tree_lines)


def write_chunks(full_text):
    """Разбивает текст на чанки заданного максимального размера."""
    chunks = []
    cursor = 0
    instruction_with_newline = "\n\n" + FINISH_INSTRUCTION
    instruction_len = len(instruction_with_newline)

    while cursor < len(full_text):
        if len(full_text) - cursor <= MAX_CHARS:
            chunks.append(full_text[cursor:])
            break

        content_limit = MAX_CHARS - instruction_len
        chunk_content = full_text[cursor : cursor + content_limit]
        full_chunk = chunk_content + instruction_with_newline
        chunks.append(full_chunk)
        cursor += content_limit

    return chunks


def cleanup_old_files():
    """Удаляет старые файлы message_*.txt перед новым запуском."""
    print("Очистка старых файлов контекста...")
    i = 1
    while True:
        old_file = f"{OUTPUT_PREFIX}{i}.txt"
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
                print(f"Удален старый файл: {old_file}")
            except OSError as e:
                print(f"Ошибка при удалении {old_file}: {e}")
                break
            i += 1
        else:
            break
    print("Очистка завершена.")


def main():
    """Главная функция скрипта."""
    cleanup_old_files()

    initial_prompt = (
        "сейчас я выгружу тебя сначала дерево файлов с размерами в символах, "
        "а потом все файлы, которые не были проигнорированы. "
        "Возможно это займет больше одного сообщения, тогда просто скажи ОК. "
        "После того как все будет загружено, я задам вопросы, чтобы ты был в контексте кода."
    )
    all_content_lines = [initial_prompt]

    file_sizes, dir_sizes, file_paths = calculate_sizes(BASE_DIR)

    sorted_files = sorted(file_sizes.items(), key=lambda item: item[1], reverse=True)
    top_files_set = {filepath for filepath, size in sorted_files[:TOP_N_FILES]}

    tree = build_tree(BASE_DIR, file_sizes, dir_sizes, top_files_set)
    all_content_lines.append("\n--- Структура проекта (с размерами в символах) ---\n")
    all_content_lines.append(tree)

    all_content_lines.append("\n--- Содержимое файлов ---\n")
    for path in sorted(file_paths):
        rel_path = os.path.relpath(path, BASE_DIR)
        header = f"Файл: {rel_path}"
        all_content_lines.append(f"\n{header}\n{'-' * len(header)}")
        content = get_file_content(path)
        all_content_lines.append(content if content is not None else "Не удалось прочитать содержимое файла.")

    full_text = "\n".join(all_content_lines)
    chunks = write_chunks(full_text)

    for i, chunk in enumerate(chunks, 1):
        out_filename = f"{OUTPUT_PREFIX}{i}.txt"
        try:
            with open(out_filename, "w", encoding="utf-8") as out_file:
                out_file.write(chunk)
            print(f"Сохранено: {out_filename} ({len(chunk)} символов)")
        except IOError as e:
            print(f"Ошибка при записи файла {out_filename}: {e}")

if __name__ == "__main__":
    main()