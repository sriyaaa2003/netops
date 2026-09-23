FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN useradd -m appuser
USER appuser

EXPOSE 5001

CMD ["gunicorn", "-b", "0.0.0.0:5001", "-w", "1", "--threads", "2", "--timeout", "60", "app:app"]
