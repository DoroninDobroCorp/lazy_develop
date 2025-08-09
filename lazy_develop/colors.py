# Файл: colors.py
class Colors:
    """Класс для хранения ANSI кодов цветов для консоли."""
    FAIL = '\033[38;2;191;97;106m'      # Красный (Aurora Red)
    OKGREEN = '\033[38;2;163;190;140m'   # Зеленый (Aurora Green)
    WARNING = '\033[38;2;235;203;139m'   # Желтый (Aurora Yellow)
    OKBLUE = '\033[38;2;94;129;172m'     # Голубой (Polar Night Blue)
    HEADER = '\033[38;2;180;142;173m'   # Пурпурный (Aurora Purple)
    CYAN = '\033[38;2;235;203;139m'     # Бирюзовый (Aurora Cyan)
    ENDC = '\033[0m'                    # Сброс
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GREY = '\033[38;2;106;114;128m'      # Серый для второстепенной информации