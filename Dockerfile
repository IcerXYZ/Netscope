FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NETSCOPE_HOST_ROOT=/host
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY agent_tokens.py /usr/local/bin/netscope-agent-token
RUN sed -i '1c#!/usr/local/bin/python' /usr/local/bin/netscope-agent-token && chmod 0750 /usr/local/bin/netscope-agent-token
COPY templates ./templates
COPY static ./static
EXPOSE 8080
CMD ["/bin/sh", "-c", "exec gunicorn --workers 1 --bind ${NETSCOPE_BIND:-0.0.0.0}:${NETSCOPE_PORT:-8080} --access-logfile - --error-logfile - app:app"]
