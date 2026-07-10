FROM python:3.11-slim

WORKDIR /app

# Dependencias primero para aprovechar la cache de capas de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# La base de datos SQLite vive en /app/data para poder montarla como volumen
# y que los datos sobrevivan a un `docker compose down` / rebuild.
ENV DB_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 5055

CMD ["gunicorn", "--bind", "0.0.0.0:5055", "--workers", "2", "--timeout", "60", "app:app"]
