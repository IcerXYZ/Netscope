FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && groupadd --gid 10001 netscope && useradd --uid 10001 --gid 10001 --no-create-home netscope
COPY app.py security.py telemetry_schema.py launch.py gunicorn.conf.py ./
COPY templates ./templates
COPY static ./static
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/launch.py"]

