FROM python:3.14-slim AS build
WORKDIR /build
COPY requirements.lock requirements-s3.lock ./
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.lock -r requirements-s3.lock
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY totally_normal_maps ./totally_normal_maps
RUN python -m pip install --no-cache-dir --no-deps --prefix=/install .

FROM python:3.14-slim
COPY --from=build /install /usr/local
USER 10001:10001
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MAPS_MODE=production MAPS_DATASET=/data/release
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/readyz', timeout=3).read()"]
ENTRYPOINT ["maps", "api", "--host", "0.0.0.0", "--port", "8000"]
