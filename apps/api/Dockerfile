# 빌드 컨텍스트는 저장소 루트(seed/ 를 함께 담아야 한다).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/apps/api

COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install --no-cache-dir .

COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY seed /srv/seed
ENV PM_SEED_DIR=/srv/seed

EXPOSE 8000
# 시작할 때 스키마와 참조 데이터를 최신으로 맞춘다.
CMD ["sh", "-c", "python -m app.cli migrate && python -m app.cli seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
