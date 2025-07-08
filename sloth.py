# -*- coding: utf-8 -*-

import google.generativeai as genai
import os
import subprocess
import time

# --- НАСТРОЙКИ ---
# ВНИМАНИЕ: Ты явно попросил вставить этот ключ.
# В реальном проекте НИКОГДА не выкладывай ключ напрямую в код!
# Используй переменные окружения или другие безопасные методы хранения.
API_KEY = 'REDACTED_GOOGLE_API_KEY' # ВАЖНО: Убедитесь, что этот ключ актуален

# Имя твоего скрипта, который собирает весь проект в один файл
CONTEXT_SCRIPT = 'AskGpt.py'
# Имя файла, куда скрипт сохраняет весь код
CONTEXT_FILE = 'message_1.txt' # Убедись, что имя файла верное

# --- КОНФИГУРАЦИЯ МОДЕЛИ ---
MODEL_NAME = "gemini-2.5-pro"

print(f"ЛОГ: Начинаю конфигурацию. Модель: {MODEL_NAME}")
try:
    genai.configure(api_key=API_KEY)
    print("ЛОГ: API сконфигурировано успешно.")
except Exception as e:
    print(f"ЛОГ: ОШИБКА конфигурации API. Проверь правильность ключа. Ошибка: {e}")
    exit()

# Настройки генерации (АКТУАЛЬНАЯ ВЕРСИЯ)
generation_config = {
    "temperature": 1, # Максимум "креативности", как ты и хотел
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 32768, # Максимальный размер ответа.
}
# Этот лог теперь будет выводить именно те значения, что указаны выше
print(f"ЛОГ: Настройки генерации: {generation_config}")

# Настройки безопасности (стандартные)
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
print(f"ЛОГ: Настройки безопасности: {safety_settings}")

# Создаем модель
model = genai.GenerativeModel(model_name=MODEL_NAME,
                              generation_config=generation_config,
                              safety_settings=safety_settings)
print(f"ЛОГ: Модель '{MODEL_NAME}' создана.")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_project_context():
    """Запускает твой скрипт и читает контекст из файла."""
    print(f"ЛОГ: Вход в функцию get_project_context().")
    print(f"ЛОГ: Запускаю '{CONTEXT_SCRIPT}' для сбора контекста проекта...")
    try:
        # --- ИСПРАВЛЕНИЕ ДЛЯ ПОИСКА ФАЙЛА ---
        # Формируем полный, абсолютный путь к скрипту, чтобы subprocess его точно нашел.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_to_run_path = os.path.join(script_dir, CONTEXT_SCRIPT)

        if not os.path.exists(script_to_run_path):
             print(f"ЛОГ: ОШИБКА: Скрипт '{CONTEXT_SCRIPT}' не найден по полному пути: '{script_to_run_path}'")
             return None

        print(f"ЛОГ: Будет запущен скрипт по полному пути: '{script_to_run_path}'")
        result = subprocess.run(
            ['python3', script_to_run_path],
            check=True, text=True, capture_output=True, encoding='utf-8'
        )
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

        print(f"ЛОГ: Скрипт '{CONTEXT_SCRIPT}' выполнен успешно. Стандартный вывод скрипта:\n{result.stdout}\nСтандартные ошибки скрипта:\n{result.stderr}")

        context_file_path = os.path.join(script_dir, CONTEXT_FILE)
        if os.path.exists(context_file_path):
            with open(context_file_path, 'r', encoding='utf-8') as f:
                context_data = f.read()
                print(f"ЛОГ: Читаю контекст из '{context_file_path}'. Размер контекста: {len(context_data)} символов.")
                print("ЛОГ: Контекст успешно прочитан.")
                print(f"ЛОГ: Выход из функции get_project_context() с контекстом.")
                return context_data
        else:
            print(f"ЛОГ: ОШИБКА: Файл '{CONTEXT_FILE}' не найден после выполнения '{CONTEXT_SCRIPT}'. Ожидался по пути: '{context_file_path}'")
            print("ЛОГ: Выход из функции get_project_context() без контекста.")
            return None
    except FileNotFoundError:
        print(f"ЛОГ: ОШИБКА: Интерпретатор 'python3' не найден. Убедитесь, что Python 3 установлен и доступен в системе.")
        print("ЛОГ: Выход из функции get_project_context() без контекста.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"ЛОГ: ОШИБКА при выполнении '{CONTEXT_SCRIPT}':")
        print(f"ЛОГ: STDOUT скрипта:\n{e.stdout}")
        print(f"ЛОГ: STDERR скрипта:\n{e.stderr}")
        print("ЛОГ: Выход из функции get_project_context() без контекста.")
        return None
    except Exception as e:
        print(f"ЛОГ: Непредвиденная ОШИБКА при чтении файла или выполнении скрипта: {e}")
        print("ЛОГ: Выход из функции get_project_context() без контекста.")
        return None


def extract_todo_block(text):
    """Извлекает текст между TODO START и TODO FINISH."""
    print(f"ЛОГ: Вход в функцию extract_todo_block().")
    try:
        start_marker = "TODO START"
        end_marker = "TODO FINISH"
        print(f"ЛОГ: Ищу маркер '{start_marker}'.")
        start_index = text.find(start_marker)
        if start_index == -1:
            print(f"ЛОГ: Маркер '{start_marker}' не найден. Возвращаю пустую строку.")
            print(f"ЛОГ: Выход из функции extract_todo_block().")
            return ""

        print(f"ЛОГ: Маркер '{start_marker}' найден на позиции {start_index}.")
        print(f"ЛОГ: Ищу маркер '{end_marker}' после позиции {start_index}.")
        end_index = text.find(end_marker, start_index)
        if end_index == -1:
            print(f"ЛОГ: Маркер '{end_marker}' не найден. Возвращаю пустую строку.")
            print(f"ЛОГ: Выход из функции extract_todo_block().")
            return ""

        print(f"ЛОГ: Маркер '{end_marker}' найден на позиции {end_index}.")
        todo_content = text[start_index + len(start_marker):end_index].strip()
        print(f"ЛОГ: Извлечено содержимое TODO блока (длина: {len(todo_content)}).")
        print(f"ЛОГ: Выход из функции extract_todo_block() с содержимым.")
        return todo_content
    except Exception as e:
        print(f"ЛОГ: ОШИБКА при извлечении блока TODO: {e}")
        print(f"ЛОГ: Выход из функции extract_todo_block() с пустой строкой.")
        return ""

# --- ГЛАВНЫЙ ЦИКЛ ---

def main():
    """Основная логика программы."""
    print("ЛОГ: Вход в функцию main().")
    initial_task = input("Привет, друже! Опиши задачу или вставь текст ошибки:\n> ")
    print(f"ЛОГ: Пользовательский ввод (начальная задача): '{initial_task}'")
    if not initial_task:
        print("ЛОГ: Начальная задача пуста. Выход из программы.")
        print("Задача не может быть пустой. Выход.")
        return

    project_context = get_project_context()
    if not project_context:
        print("ЛОГ: Контекст проекта не получен. Выход из программы.")
        return

    prompt_template = """
    Привет. Я работаю над большим учебным проектом. Вот весь его код, собранный в один файл:
    --- КОНТЕКСТ ПРОЕКТА ---
    {context}
    --- КОНЕЦ КОНТЕКСТА ---

    Моя задача: {task}

    Проанализируй код и задачу. Предоставь конкретные изменения, которые нужно внести для решения задачи.
    ВАЖНО: Весь код, который нужно изменить или добавить, оберни в маркеры:
    TODO START
    # Указывай полный путь к файлу, который нужно изменить, например: # FILE: src/main.py
    # ... здесь код для вставки/замены ...
    TODO FINISH

    Если ничего менять не нужно и задача решена, напиши только одно слово: "ГОТОВО".
    """
    print("ЛОГ: Шаблон промпта определён.")

    current_prompt = prompt_template.format(context=project_context, task=initial_task)
    print(f"ЛОГ: Начальный промпт сформирован. Длина промпта: {len(current_prompt)} символов.")

    for iteration_count in range(1, 11): # Ограничим 10 итерациями, чтобы не уйти в вечный цикл
        print(f"\n--- ИТЕРАЦИЯ {iteration_count} ---")
        print(f"ЛОГ: Начинаю итерацию № {iteration_count}.")
        print(f"ЛОГ: Отправляю запрос в модель {MODEL_NAME}...")

        try:
            print("ЛОГ: Отправляю запрос genai.GenerativeModel.generate_content()...")
            response = model.generate_content(current_prompt)
            answer = response.text
            print("ЛОГ: Ответ от модели успешно получен.")
        except Exception as e:
            print(f"ЛОГ: ОШИБКА при запросе к API: {e}")
            print("ЛОГ: Возможно, в вашем проекте слишком много текста или проблема с API ключом.")
            print(f"Произошла ошибка при запросе к API: {e}")
            print("Возможно, в вашем проекте слишком много текста или проблема с API ключом.")
            break

        print("\nПОЛУЧЕН ОТВЕТ:\n" + "="*20 + f"\n{answer}\n" + "="*20)
        print(f"ЛОГ: Проверяю ответ модели на наличие 'ГОТОВО'.")

        if "ГОТОВО" in answer.upper(): # Проверяем в верхнем регистре для надежности
            print("ЛОГ: В ответе модели найдено 'ГОТОВО'. Считаем задачу выполненной.")
            print("\nGemini считает, что задача выполнена! Пора тебе проверить результат!")
            break

        print("ЛОГ: 'ГОТОВО' не найдено. Извлекаю блок TODO.")
        todo_changes = extract_todo_block(answer)
        if not todo_changes:
            print("ЛОГ: Блок TODO не найден в ответе модели.")
            print("\nНе найдено блока TODO в ответе. Возможно, задача решена или модель не поняла запрос.")
            print("Зову тебя проверить. Посмотри последний ответ от модели.")
            print("ЛОГ: Выход из цикла и программы из-за отсутствия TODO блока.")
            break

        print("\nНайдены следующие рекомендации:\n" + "-"*20 + f"\n{todo_changes}\n" + "-"*20)
        print("ЛОГ: Блок TODO успешно извлечён.")

        user_input = input("Применить эти изменения и продолжить итерацию? (y/n): ")
        print(f"ЛОГ: Пользовательский ввод для продолжения: '{user_input}'")
        if user_input.lower() != 'y':
            print("ЛОГ: Пользователь отказался продолжать. Работа остановлена.")
            print("Работа остановлена.")
            break

        print("\nВАЖНО: Пожалуйста, вручную внеси предложенные изменения в код твоего проекта и сохрани файлы.")
        input("Когда закончишь, нажми Enter для продолжения...")
        print("ЛОГ: Пользователь подтвердил внесение изменений и готов продолжить.")

        print("ЛОГ: Обновляю контекст проекта после твоих правок...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        context_file_path = os.path.join(script_dir, CONTEXT_FILE)
        if os.path.exists(context_file_path):
            print(f"ЛОГ: Обнаружен старый файл контекста '{context_file_path}'. Удаляю его.")
            os.remove(context_file_path)
            print("ЛОГ: Старый файл контекста удалён.")
        else:
            print(f"ЛОГ: Старый файл контекста '{context_file_path}' не найден. Продолжаю.")

        project_context = get_project_context()
        if not project_context:
            print("ЛОГ: Новый контекст проекта не получен после обновления. Выход из программы.")
            break

        review_prompt_template = """
        --- КОНТЕКСТ ПРОЕКТА (ОБНОВЛЕННЫЙ) ---
        {context}
        --- КОНЕЦ КОНТЕКСТА ---

        Я внес предыдущие изменения. Первоначальная задача была: {task}

        Проверь еще раз. Нужно ли что-то еще исправить? Только самое необходимое.
        Если нужны еще правки, снова предоставь их в блоке TODO START ... TODO FINISH.
        Если все готово, напиши только одно слово: "ГОТОВО".
        """
        current_prompt = review_prompt_template.format(context=project_context, task=initial_task)
        print(f"ЛОГ: Промпт для следующей итерации сформирован. Длина: {len(current_prompt)} символов.")

        print("ЛОГ: Пауза 3 секунды перед следующей итерацией...")
        time.sleep(3)
        print("ЛОГ: Пауза завершена.")

    print("\nСкрипт завершил работу.")
    print("ЛОГ: Выход из функции main().")

if __name__ == "__main__":
    print("ЛОГ: Скрипт запущен как основной модуль.")
    main()
    print("ЛОГ: Выполнение скрипта завершено.")