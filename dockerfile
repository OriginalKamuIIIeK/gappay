FROM python:3.11-slim

WORKDIR /app

# Копируем файлы
COPY requirements.txt .
COPY main.py .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку для скриншотов
RUN mkdir -p screenshots

# Запускаем бота
CMD ["python", "main.py"]