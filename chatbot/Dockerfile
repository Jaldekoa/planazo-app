FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main_chatbot.py .

EXPOSE 10000

CMD ["uvicorn", "main_chatbot:app", "--host", "0.0.0.0", "--port", "10000"]