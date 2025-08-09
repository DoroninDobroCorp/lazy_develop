# Файл: sloth_log_cleaner.py
import os
import sys
import argparse
from tkinter import Tk, filedialog

from colors import Colors, Symbols

SLOTH_TAG = "[SLOTHLOG]"


def is_probably_text(filepath, blocksize=1024):
    """
    Грубая эвристика: пытаемся прочитать небольшой блок в utf-8.
    Если удаётся без исключений — считаем текстовым.
    """
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(blocksize)
        chunk.decode('utf-8')
        return True
    except Exception:
        return False


def clean_file(filepath: str, tag: str, backup: bool) -> tuple[int, bool]:
    """
    Удаляет строки, содержащие tag, из файла.
    Возвращает (количество_удалённых_строк, был_изменён_файл)
    """
    if not os.path.isfile(filepath):
        return 0, False

    if not is_probably_text(filepath):
        return 0, False

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return 0, False

    total = len(lines)
    kept = [ln for ln in lines if tag not in ln]
    removed = total - len(kept)

    if removed > 0:
        try:
            if backup:
                try:
                    with open(filepath + '.bak', 'w', encoding='utf-8') as fb:
                        fb.writelines(lines)
                except Exception as e:
                    print(f"{Colors.WARNING}{Symbols.WARNING} Не удалось сделать backup для {filepath}: {e}{Colors.ENDC}")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(kept)
            return removed, True
        except Exception as e:
            print(f"{Colors.FAIL}{Symbols.CROSS} Ошибка записи файла {filepath}: {e}{Colors.ENDC}")
            return 0, False
    return 0, False


def walk_and_clean(root_dir: str, tag: str, backup: bool) -> tuple[int, int, int]:
    """
    Рекурсивно проходит по директории и чистит все файлы.
    Возвращает (обработано_файлов, изменено_файлов, удалено_строк)
    """
    processed = 0
    changed = 0
    removed_total = 0
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            path = os.path.join(base, name)
            processed += 1
            removed, modified = clean_file(path, tag, backup)
            removed_total += removed
            if modified:
                changed += 1
                print(f"{Colors.OKGREEN}{Symbols.CHECK} Обновлён: {path} (−{removed} строк с {tag}){Colors.ENDC}")
    return processed, changed, removed_total


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sloth Log Cleaner: удаление строк с [SLOTHLOG] из файлов в директории.')
    parser.add_argument('--here', action='store_true', help='Использовать текущую директорию вместо диалога выбора.')
    parser.add_argument('--backup', action='store_true', help='Сохранять .bak копии изменённых файлов.')
    parser.add_argument('--tag', type=str, default=SLOTH_TAG, help='Префикс лога для удаления (по умолчанию [SLOTHLOG]).')
    args = parser.parse_args()

    if args.here:
        target_dir = os.getcwd()
    else:
        print(f"{Colors.OKBLUE}Выберите папку проекта для очистки логов {SLOTH_TAG}...{Colors.ENDC}")
        root = Tk(); root.withdraw()
        target_dir = filedialog.askdirectory(title='Выберите папку проекта для очистки логов')
        root.destroy()

    if not target_dir:
        print(f"{Colors.FAIL}{Symbols.CROSS} Папка не выбрана. Выход.{Colors.ENDC}")
        sys.exit(1)

    if not os.path.isdir(target_dir):
        print(f"{Colors.FAIL}{Symbols.CROSS} Указанный путь не является директорией: {target_dir}{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.HEADER}{Symbols.SPINNER} Начинаю очистку в: {target_dir}{Colors.ENDC}")
    processed, changed, removed_total = walk_and_clean(target_dir, args.tag, args.backup)

    print("\n" + "="*80)
    print(f"{Colors.BOLD}📊 Итоги очистки:{Colors.ENDC}")
    print(f"  Файлов обработано: {processed}")
    print(f"  Файлов изменено:   {changed}")
    print(f"  Строк удалено:     {removed_total}")
    print("="*80)
