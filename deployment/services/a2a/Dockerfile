FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system --gid 10001 agentops && useradd --system --uid 10001 --gid agentops --home-dir /app agentops
COPY services/a2a/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/common/auth.py ./auth.py
COPY services/common/telemetry.py ./telemetry.py
COPY services/a2a/server.py ./server.py
USER 10001:10001
EXPOSE 9000
CMD ["python", "server.py"]
