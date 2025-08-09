# Файл: context_collector.py
import os

# --- КОНФИГУРАЦИЯ СБОРА КОНТЕКСТА ---
IGNORE_EXTENSIONS = {".png", ".jpeg", ".jpg", ".gif", ".bmp", ".ico", ".svg", ".webp"}
IGNORE_FILES = {
    "go.mod", "go.sum", "package.json", "package-lock.json", "yarn.lock",
    ".ds_store", ".gitignore", "readme.md", "analyzer_wide", "tsconfig.tsbuildinfo",
    "sloth_debug_prompt.txt", "sloth_debug_bad_response.txt", "message_1.txt"
}
IGNORE_DIRS = {
    "venv", ".venv", "__pycache__", ".pytest_cache", "node_modules",
    ".next", "dist", "build", "coverage", ".git", ".idea", ".vscode",
    ".claude", "logs"
}

# --- ПРИВАТНЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _get_file_content(filepath):
    """Безопасно читает содержимое текстового файла."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def _should_ignore(path, root_dir):
    """Проверяет, следует ли игнорировать файл или директорию."""
    path_lower = path.lower()
    base_name = os.path.basename(path_lower)

    if base_name in {os.path.basename(__file__).lower(), "askgpt.py"}:
        return True
    if base_name in IGNORE_FILES:
        return True
    if any(base_name.endswith(ext) for ext in IGNORE_EXTENSIONS):
        return True
    
    # Проверяем, является ли какой-либо из родительских каталогов игнорируемым
    rel_path = os.path.relpath(path_lower, root_dir)
    path_parts = rel_path.split(os.sep)
    if any(part in IGNORE_DIRS for part in path_parts):
        return True

    return False

def _build_tree_string(root_dir, all_paths, file_sizes, top_files_set):
    """Строит детальное и красивое дерево проекта."""
    tree_lines = []
    
    # Создаем структуру папок и файлов
    tree = {}
    for path in all_paths:
        rel_path = os.path.relpath(path, root_dir)
        parts = rel_path.split(os.sep)
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
    
    def generate_lines_recursive(subtree, path_prefix=""):
        # Сортируем элементы: папки сначала, потом файлы
        entries = sorted(subtree.keys(), key=lambda x: not subtree[x])
        for i, name in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            
            current_rel_path = os.path.join(path_prefix, name)
            current_abs_path = os.path.join(root_dir, current_rel_path)
            
            is_dir = bool(subtree[name]) # Если есть дочерние элементы - это папка
            
            if is_dir:
                tree_lines.append(f"{path_prefix}{connector}{name}/")
                child_prefix = path_prefix + ("    " if is_last else "│   ")
                generate_lines_recursive(subtree[name], child_prefix)
            else: # Это файл
                prefix = "!!!" if current_abs_path in top_files_set else ""
                size = file_sizes.get(current_abs_path, 0)
                tree_lines.append(f"{path_prefix}{connector}{prefix}{name} ({size} chars)")

    generate_lines_recursive(tree)
    return "\n".join(tree_lines)


# --- ГЛАВНАЯ ПУБЛИЧНАЯ ФУНКЦИЯ ---

def gather_project_context(root_dir, top_n_files=3):
    """
    Сканирует директорию проекта, собирает контент и возвращает его в виде одной большой строки.
    """
    all_lines = []
    file_sizes = {}
    dir_sizes = {}
    file_paths_to_include = []

    # Шаг 1: Проход по дереву для сбора путей и размеров файлов
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True):
        # Удаляем игнорируемые директории из дальнейшего обхода
        dirnames[:] = [d for d in dirnames if not _should_ignore(os.path.join(dirpath, d), root_dir)]
        
        current_dir_size = 0
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if _should_ignore(filepath, root_dir):
                continue
            
            content = _get_file_content(filepath)
            if content is not None:
                size = len(content)
                file_sizes[filepath] = size
                current_dir_size += size
                file_paths_to_include.append(filepath)
        dir_sizes[dirpath] = current_dir_size

    # Шаг 2: Формируем итоговый текст
    all_lines.append(
        "Сейчас я выгружу контекст проекта: сначала дерево файлов с размерами в символах, а потом их содержимое."
    )

    sorted_by_size = sorted(file_sizes.items(), key=lambda item: item[1], reverse=True)
    top_files_set = {filepath for filepath, size in sorted_by_size[:top_n_files]}

    # Используем восстановленную функцию для построения дерева
    tree_string = _build_tree_string(root_dir, file_paths_to_include, file_sizes, top_files_set)
    all_lines.append("\n--- Структура проекта ---\n" + tree_string)
    
    all_lines.append("\n--- Содержимое файлов ---")
    for path in sorted(file_paths_to_include):
        rel_path = os.path.relpath(path, root_dir)
        all_lines.append(f"\nФайл: {rel_path}\n{'-' * len('Файл: ' + rel_path)}")
        # Контент уже прочитан, но для надежности можем прочитать снова
        content = _get_file_content(path)
        all_lines.append(content if content is not None else "Не удалось прочитать содержимое файла.")

    return "\n".join(all_lines)