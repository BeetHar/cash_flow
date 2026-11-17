FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

WORKDIR /app

COPY requirements/base.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt

COPY --chown=app:app docker/ /app/docker/
COPY --chown=app:app src/ /app/src/

USER app
WORKDIR /app/src

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker/entrypoint.dev.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

