# Файл: context_collector.py
import os
import re

# --- КОНФИГУРАЦИЯ СБОРА КОНТЕКСТА ---
IGNORE_EXTENSIONS = {".png", ".jpeg", ".jpg", ".gif", ".bmp", ".ico", ".svg", ".webp"}
IGNORE_FILES = {
    "go.mod", "go.sum", "package-lock.json", "yarn.lock",
    ".ds_store", ".gitignore", "readme.md", "analyzer_wide", "tsconfig.tsbuildinfo",
    "sloth_debug_prompt.txt", "sloth_debug_bad_response.txt"
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

def _summarize_content(content, filepath):
    """Сокращает содержимое файла, оставляя только ключевые сигнатуры."""
    filename = os.path.basename(filepath)
    _, extension = os.path.splitext(filename)
    extension = extension.lower()

    if extension == '.py':
        matches = re.findall(r"^(?:@.*?\n)*(?:async\s+)?def\s+.*?\)|class\s+.*?:", content, re.MULTILINE)
        if matches:
            summary = [m + "\n    ... # implementation" for m in matches]
            return f"# File: {filename}\n# Summary of declarations:\n\n" + "\n\n".join(summary)
        return f"# File: {filename}\n# No top-level functions or classes found."

    elif extension in ['.js', '.jsx', '.ts', '.tsx']:
        matches = re.findall(r"^(?:export\s+)?(?:async\s+)?function\s+.*?\{|^(?:export\s+)?class\s+.*?\{|^(?:export\s+)?(?:const|let|var)\s+.*?=.*?;|^(?:export\s+)?type\s+.*?=.*?;|^(?:export\s+)?interface\s+.*?\{", content, re.MULTILINE)
        if matches:
            summary = [m + ("\n  // ... implementation\n}" if m.endswith('{') else "") for m in matches]
            return f"// File: {filename}\n// Summary of declarations:\n\n" + "\n\n".join(summary)
        return f"// File: {filename}\n// No top-level declarations found."
        
    elif extension in ['.html', '.css', '.scss', '.json', '.yml', '.yaml', '.xml', '.md']:
         lines = content.splitlines()
         if len(lines) > 20:
             summary = "\n".join(lines[:10]) + "\n\n[... content truncated ...]\n\n" + "\n".join(lines[-5:])
             return summary
         return content

    else:
        lines = content.splitlines()
        if len(lines) > 20:
            return f"[Content of file {filename} truncated. First 10 lines:]\n" + "\n".join(lines[:10])
        return content

def _should_ignore(path, root_dir):
    """Проверяет, следует ли игнорировать файл или директорию."""
    path_lower = path.lower()
    base_name = os.path.basename(path_lower)
    sloth_scripts = {
        "sloth.py"
    }
    if base_name in sloth_scripts: return True
    if base_name in IGNORE_FILES: return True
    if any(base_name.endswith(ext) for ext in IGNORE_EXTENSIONS): return True
    rel_path = os.path.relpath(path_lower, root_dir)
    path_parts = rel_path.split(os.sep)
    if any(part in IGNORE_DIRS for part in path_parts): return True
    return False

# --- ГЛАВНАЯ ПУБЛИЧНАЯ ФУНКЦИЯ ---

def gather_project_context(root_dir, mode='full', full_content_files=None, top_n_files=3):
    """
    Сканирует директорию проекта, собирает контент и возвращает его в виде одной большой строки.
    """
    if full_content_files is None: full_content_files = set()
    else: full_content_files = {os.path.normpath(os.path.join(root_dir, f)) for f in full_content_files}

    all_lines = []
    file_sizes = {}
    file_paths_to_include = []

    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True):
        dirnames[:] = [d for d in dirnames if not _should_ignore(os.path.join(dirpath, d), root_dir)]
        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            if _should_ignore(filepath, root_dir): continue
            content = _get_file_content(filepath)
            if content is not None:
                file_sizes[filepath] = len(content)
                file_paths_to_include.append(filepath)

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