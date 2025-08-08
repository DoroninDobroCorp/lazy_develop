# ты красивый)))
# Файл: test_sloth_vertex_FIXED.py
# Цель: добиться успешного выполнения этого скрипта.

import vertexai
# Эта строка теперь работает, так как вы обновили библиотеку
from vertexai.generative_models import GenerativeModel
import sys

# --- Ваши учетные данные ---
GOOGLE_CLOUD_PROJECT = "useful-gearbox-464618-v3"
GOOGLE_CLOUD_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro"

# --- Цвета для наглядности ---
OKGREEN = '\033[92m'
FAIL = '\033[91m'
ENDC = '\033[0m'
BOLD = '\033[1m'

print(f"{BOLD}--- Тестирую ИСПРАВЛЕННУЮ логику Vertex AI ---{ENDC}")

try:
    # 1. Инициализация (этот шаг у вас уже проходил)
    print("1. Пытаюсь инициализировать Vertex AI (vertexai.init)...")
    vertexai.init(project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)
    print(f"{OKGREEN}   - Инициализация прошла успешно.{ENDC}")

    # 2. Создание модели (этот шаг у вас уже проходил)
    print("2. Пытаюсь создать объект GenerativeModel...")
    model = GenerativeModel(MODEL_NAME)
    print(f"{OKGREEN}   - Объект модели создан успешно.{ENDC}")

    # 3. Тестовый запрос (ЗДЕСЬ БЫЛО ИСПРАВЛЕНИЕ)
    print("3. Пытаюсь сделать КОРРЕКТНЫЙ тестовый запрос (БЕЗ `request_options`)...")
    
    # БЫЛО (вызывало ошибку): model.generate_content("test", request_options={"timeout": 60})
    # СТАЛО (правильно для Vertex AI):
    model.generate_content("test")
    
    print(f"{OKGREEN}   - Тестовый запрос прошел успешно.{ENDC}")

    print(f"\n{OKGREEN}{BOLD}✅ ПОЛНЫЙ УСПЕХ! Логика вызова Vertex AI теперь правильная.{ENDC}")

except Exception as e:
    print(f"\n{FAIL}{BOLD}❌ ОБНАРУЖЕНА ОШИБКА!{ENDC}")
    print(f"   Тип ошибки: {type(e).__name__}")
    print(f"   Детали: {e}")
    print(f"\n{FAIL}Если вы все еще видите ошибку, убедитесь, что выполнили команду:{ENDC}")
    print("   pip3 install --upgrade --force-reinstall google-cloud-aiplatform")
    sys.exit(1)
