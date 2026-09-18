# syntax=docker/dockerfile:1
FROM python:3.14-slim AS build
WORKDIR /build
COPY requirements.lock requirements-s3.lock ./
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.lock -r requirements-s3.lock
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY totally_normal_maps ./totally_normal_maps
RUN python -m pip install --no-cache-dir --no-deps --prefix=/install .

FROM python:3.14-slim AS runtime
COPY --from=build /install /usr/local
USER 10001:10001
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MAPS_MODE=production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/readyz', timeout=3).read()"]
ENTRYPOINT ["maps", "api", "--host", "0.0.0.0", "--port", "8000"]

# Explicit compatibility target for operators with separately mounted releases.
FROM runtime AS api-only
ENV MAPS_DATASET=/data/release

FROM runtime AS combined-base
ENV MAPS_BUNDLE=/opt/maps/bundle

# Offline CI or an operator-supplied, already verified bundle. This named context
# must be passed explicitly; the normal context still excludes all local data.
FROM combined-base AS bundled-local
COPY --from=deployment_bundle / /opt/maps/bundle/
RUN maps verify-deployment --bundle /opt/maps/bundle

# Only this explicit build operation downloads the locked public release asset.
FROM runtime AS assemble
COPY dataset.lock.json /tmp/dataset.lock.json
RUN maps assemble-deployment --lock /tmp/dataset.lock.json --output /tmp/bundle

# Default deployment: website, API and dataset travel and roll back together.
FROM combined-base AS combined
COPY --from=assemble /tmp/bundle /opt/maps/bundle
RUN maps verify-deployment --bundle /opt/maps/bundle
