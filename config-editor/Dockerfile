FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py gamedata.py status.py ./
COPY static ./static

ENV CONFIG_DIR=/config \
    GAME_DIR=/game \
    SERVER_LOG=/logs/wf/server.log \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
