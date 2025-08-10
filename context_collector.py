# Файл: context_collector.py
import os
import re
from colors import Colors

# --- КОНФИГУРАЦИЯ СБОРА КОНТЕКСТА ---
MAX_FILE_SIZE_CHARS = 100000
LARGE_FILE_THRESHOLD_CHARS = 25000

# !!! РАСШИРЕННЫЙ СПИСОК ИГНОРИРУЕМЫХ РАСШИРЕНИЙ !!!
IGNORE_EXTENSIONS = {
    # Изображения и медиа
    ".png", ".jpeg", ".jpg", ".gif", ".bmp", ".ico", ".svg", ".webp", ".mp4", ".mov", ".avi",
    
    # Аудио
    ".wav", ".mp3", ".flac", ".aac", ".ogg", ".m4a",
    
    # Документы и архивы
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".gz", ".tar", ".rar", ".7z",

    # Скомпилированные файлы и библиотеки
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".o", ".a", ".class", ".jar", ".war",
    
    # Файлы БД и кэша
    ".db", ".sqlite3", ".bak", ".tmp", ".swp",
    
    # Шрифты
    ".ttf", ".otf", ".woff", ".woff2",
    
    # Форматы данных и моделей ML
    ".h5", ".hdf5", ".pkl", ".pickle", ".safetensors", ".bin", ".pt", ".pth", ".onnx",
    ".npy", ".npz", ".mat", ".rpw", ".model",
    
    # Логи
    ".log",
}

IGNORE_FILES = {
    "go.mod", "go.sum", "package-lock.json", "yarn.lock", "poetry.lock",
    ".ds_store", ".gitignore", "readme.md", "analyzer_wide", "tsconfig.tsbuildinfo",
    "sloth_debug_prompt.txt", "sloth_debug_bad_response.txt"
}

IGNORE_DIRS = {
    "__pycache__", ".pytest_cache", "node_modules", ".next", "dist", "build",
    "coverage", ".git", ".idea", ".vscode", ".claude", "logs"
}


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (без изменений) ---

def _is_virtual_env(dirpath: str) -> bool:
    """Универсально проверяет, является ли директория виртуальным окружением Python."""
    has_pyvenv_cfg = os.path.exists(os.path.join(dirpath, 'pyvenv.cfg'))
    has_unix_activate = os.path.exists(os.path.join(dirpath, 'bin', 'activate'))
    has_windows_activate = os.path.exists(os.path.join(dirpath, 'Scripts', 'activate.bat'))
    return has_pyvenv_cfg or has_unix_activate or has_windows_activate

def _is_binary_file(filepath: str, blocksize: int = 1024) -> bool:
    """Эвристика для определения, является ли файл бинарным."""
    try:
        with open(filepath, 'rb') as f:
            return b'\0' in f.read(blocksize)
    except Exception:
        return True

def _get_file_content(filepath: str):
    """Безопасно читает содержимое текстового файла."""
    # ... (код этой функции не меняется)
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def _summarize_content(content: str, filepath: str):
    """Сокращает содержимое файла."""
    # ... (код этой функции не меняется)
    filename = os.path.basename(filepath)
    _, extension = os.path.splitext(filename)
    extension = extension.lower()

    if extension == '.py':
        matches = re.findall(r"^(?:@.*?\n)*(?:async\s+)?def\s+.*?\)|class\s+.*?:", content, re.MULTILINE)
        if matches:
            summary = [m + "\n    ... # implementation" for m in matches]
            return f"# File: {filename}\n# Summary of declarations:\n\n" + "\n\n".join(summary)
        return f"# File: {filename}\n# No top-level functions or classes found."
    lines = content.splitlines()
    if len(lines) > 20:
        summary = "\n".join(lines[:10]) + "\n\n[... content truncated ...]\n\n" + "\n".join(lines[-5:])
        return summary
    return content

def _should_ignore(path: str, root_dir: str) -> bool:
    """Проверяет, следует ли игнорировать файл/директорию по базовым правилам."""
    # ... (код этой функции не меняется)
    path_lower = path.lower()
    base_name = os.path.basename(path_lower)
    sloth_scripts = {"sloth.py"}
    if base_name in sloth_scripts: return True
    if base_name in IGNORE_FILES: return True
    if any(base_name.endswith(ext) for ext in IGNORE_EXTENSIONS): return True
    rel_path = os.path.relpath(path_lower, root_dir)
    path_parts = rel_path.split(os.sep)
    if any(part in IGNORE_DIRS for part in path_parts): return True
    return False

# --- ГЛАВНАЯ ПУБЛИЧНАЯ ФУНКЦИЯ (С ИЗМЕНЕНИЯМИ) ---

def gather_project_context(root_dir, mode='full', full_content_files=None, top_n_files=3):
    # ... (начало функции без изменений)
    if full_content_files is None: full_content_files = set()
    else: full_content_files = {os.path.normpath(os.path.join(root_dir, f)) for f in full_content_files}
    all_lines, file_sizes, file_paths_to_include = [], {}, []

    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True):
        
        original_dirs = list(dirnames)
        dirnames.clear()
        for d in original_dirs:
            current_dir_path = os.path.join(dirpath, d)
            if not _should_ignore(current_dir_path, root_dir) and not _is_virtual_env(current_dir_path):
                dirnames.append(d)

        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            # Пропускаем файлы по базовым правилам (имя, расширение) молча
            if _should_ignore(filepath, root_dir):
                continue

            try:
                # !!! УЛУЧШЕННАЯ И ОКОНЧАТЕЛЬНАЯ ЛОГИКА ФИЛЬТРАЦИИ !!!
                
                # 1. Сначала МОЛЧА пропускаем бинарные файлы
                if _is_binary_file(filepath):
                    continue
                
                # 2. Только теперь, для текстовых файлов, проверяем размер
                file_size = os.path.getsize(filepath)

                # 3. Сообщаем, только если пропускаем ОГРОМНЫЙ ТЕКСТОВЫЙ файл
                if file_size > MAX_FILE_SIZE_CHARS:
                    print(f"{Colors.WARNING}ЛОГ: Пропускаю слишком большой ТЕКСТОВЫЙ файл ({file_size} байт): {os.path.relpath(filepath, root_dir)}{Colors.ENDC}")
                    continue
                
                # 4. Предупреждение о рефакторинге для включенных файлов — полезно, оставляем
                if file_size > LARGE_FILE_THRESHOLD_CHARS:
                    print(f"{Colors.WARNING}ПРЕДУПРЕЖДЕНИЕ: Обнаружен большой файл ({file_size} байт): {os.path.relpath(filepath, root_dir)}. Возможно, требуется рефакторинг.{Colors.ENDC}")

            except OSError:
                continue
            
            content = _get_file_content(filepath)
            if content is not None:
                file_sizes[filepath] = len(content)
                file_paths_to_include.append(filepath)

    # ... (вся остальная часть функции для генерации дерева и контента остается без изменений) ...
    sorted_by_size = sorted(file_sizes.items(), key=lambda item: item[1], reverse=True)
    top_files_set = {filepath for filepath, size in sorted_by_size[:top_n_files]}
    tree_structure = {}
    for path in file_paths_to_include:
        rel_path = os.path.relpath(path, root_dir)
        parts = rel_path.split(os.sep)
        node = tree_structure
        for part in parts[:-1]: node = node.setdefault(part, {})
        node[parts[-1]] = path
    def generate_tree_lines_recursive(subtree, prefix=""):
        lines = []
        entries = sorted(subtree.items(), key=lambda item: isinstance(item[1], dict), reverse=True)
        for i, (name, value) in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            if isinstance(value, dict):
                lines.append(f"{prefix}{connector}{name}/")
                lines.extend(generate_tree_lines_recursive(value, prefix + ("    " if i == len(entries) - 1 else "│   ")))
            else:
                size = file_sizes.get(value, 0)
                marker = "!!!" if value in top_files_set else ""
                lines.append(f"{prefix}{connector}{marker}{name} ({size} chars)")
        return lines
    tree_string = f"{os.path.basename(root_dir)}/\n" + "\n".join(generate_tree_lines_recursive(tree_structure))
    all_lines.append("Сейчас я выгружу контекст проекта: сначала дерево файлов с размерами в символах, а потом их содержимое.")
    all_lines.append("\n--- Структура проекта ---\n" + tree_string)
    all_lines.append("\n--- Содержимое файлов ---")
    for path in sorted(file_paths_to_include):
        rel_path = os.path.relpath(path, root_dir)
        all_lines.append(f"\nФайл: {rel_path}\n{'-' * len('Файл: ' + rel_path)}")
        content = _get_file_content(path)
        if content is None:
            all_lines.append("Не удалось прочитать содержимое файла.")
            continue
        norm_path = os.path.normpath(path)
        if mode == 'full' or norm_path in full_content_files:
            all_lines.append(content)
        else:
            all_lines.append(_summarize_content(content, path))
    return "\n".join(all_lines)