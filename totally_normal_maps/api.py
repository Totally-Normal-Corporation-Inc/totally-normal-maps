"""Read-only versioned HTTP API. No consumer database or cloud write credentials."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .catalogue import CatalogueError
from .dataset import Dataset

LOG = logging.getLogger('totally_normal_maps.api')
MAX_BODY_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
Level = Literal['country', 'province', 'region', 'municipality', 'city_area']


@dataclass(frozen=True)
class Settings:
    dataset: Path
    manifest_sha256: str | None = None
    mode: str = 'local'
    tokens: dict[str, str] = field(default_factory=dict, repr=False)
    allowed_hosts: tuple[str, ...] = ('localhost', '127.0.0.1', '::1')
    cors_origins: tuple[str, ...] = ()
    requests_per_minute: int = 120

    def __post_init__(self):
        if self.mode not in {'local', 'production'}:
            raise CatalogueError('MAPS_MODE must be local or production.')
        if (not isinstance(self.tokens, dict) or len(self.tokens) > 100
                or any(not isinstance(k, str) or not 1 <= len(k) <= 64
                       or not isinstance(v, str) or re.fullmatch(r'[A-Za-z0-9._~-]{32,256}', v) is None for k, v in self.tokens.items())
                or len(set(self.tokens.values())) != len(self.tokens)):
            raise CatalogueError('API tokens must be unique 32–256-character secrets mapped to client names.')
        if not self.allowed_hosts or '*' in self.allowed_hosts:
            raise CatalogueError('Configure explicit API hostnames, without an unrestricted wildcard.')
        if any(not s.startswith(('https://', 'http://localhost:', 'http://127.0.0.1:')) for s in self.cors_origins):
            raise CatalogueError('CORS origins must use HTTPS or explicit local development origins.')
        if not 1 <= self.requests_per_minute <= 100_000:
            raise CatalogueError('Request limit must be 1–100,000 per minute per client and process.')
        if self.mode == 'production' and (not self.manifest_sha256 or not self.tokens):
            raise CatalogueError('Production requires a pinned manifest and API tokens.')

    @classmethod
    def from_env(cls):
        path = os.environ.get('MAPS_DATASET')
        if not path:
            raise CatalogueError('Set MAPS_DATASET to an exported serving release.')
        if os.environ.get('MAPS_ALLOW_ANONYMOUS') == 'true':
            raise CatalogueError('Anonymous API hosting is no longer supported. Remove MAPS_ALLOW_ANONYMOUS and configure MAPS_API_TOKENS.')
        try:
            tokens = json.loads(os.environ.get('MAPS_API_TOKENS', '{}'))
            rate = int(os.environ.get('MAPS_REQUESTS_PER_MINUTE', '120'))
        except (ValueError, TypeError):
            raise CatalogueError('Invalid API token or request-limit configuration.') from None
        return cls(dataset=Path(path), manifest_sha256=os.environ.get('MAPS_MANIFEST_SHA256') or None,
                   mode=os.environ.get('MAPS_MODE', 'local'), tokens=tokens,
                   allowed_hosts=tuple(s.strip() for s in os.environ.get('MAPS_ALLOWED_HOSTS', 'localhost,127.0.0.1,::1').split(',') if s.strip()),
                   cors_origins=tuple(s.strip() for s in os.environ.get('MAPS_CORS_ORIGINS', '').split(',') if s.strip()),
                   requests_per_minute=rate)


class AccessMiddleware:
    """Bounded request input and per-process abuse limits, without access logging."""

    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.host_checked = TrustedHostMiddleware(app, allowed_hosts=list(settings.allowed_hosts), www_redirect=False)
        self.buckets = OrderedDict()

    async def reject(self, scope, receive, send, status, message, headers=None):
        response = JSONResponse({'error': message}, status_code=status,
                                headers={'Cache-Control': 'no-store', **(headers or {})})
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        # Health checks reveal no location or credentials and support load-balancer IP Host headers.
        if path in {'/healthz', '/readyz'}:
            return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope.get('headers', []):
            if key in headers and key in {b'authorization', b'content-length', b'host'}:
                return await self.reject(scope, receive, send, 400, 'Duplicate security-sensitive header.')
            headers[key] = value
        if len(scope.get('query_string', b'')) > 2048:
            return await self.reject(scope, receive, send, 414, 'Query string is too long.')
        if scope['method'] == 'OPTIONS':
            return await self.host_checked(scope, receive, send)
        if path.startswith('/v1/'):
            identity = None
            authorization = headers.get(b'authorization', b'')
            if authorization[:7].lower() == b'bearer ' and len(authorization) <= 263:
                candidate = authorization[7:]
                for name, token in self.settings.tokens.items():
                    if secrets.compare_digest(candidate, token.encode()):
                        identity = name
            if identity is None:
                host = (scope.get('client') or ('',))[0]
                try:
                    loopback = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    loopback = False
                local = self.settings.mode == 'local' and not self.settings.tokens and loopback
                if authorization or not local:
                    return await self.reject(scope, receive, send, 401, 'A valid bearer token is required.', {'WWW-Authenticate': 'Bearer'})
                identity = f'anonymous:{host}'
            now = time.monotonic()
            started, count = self.buckets.pop(identity, (now, 0))
            if now - started >= 60:
                started, count = now, 0
            self.buckets[identity] = (started, count + 1)
            while len(self.buckets) > 1000:
                self.buckets.popitem(last=False)
            if count >= self.settings.requests_per_minute:
                return await self.reject(scope, receive, send, 429, 'Request limit reached.', {'Retry-After': str(max(1, int(60 - now + started)))})
        try:
            length = headers.get(b'content-length')
            if length is not None and (int(length) < 0 or int(length) > MAX_BODY_BYTES):
                return await self.reject(scope, receive, send, 413, 'Request body is too large.')
        except ValueError:
            return await self.reject(scope, receive, send, 400, 'Invalid Content-Length.')
        if headers.get(b'content-encoding', b'identity') != b'identity':
            return await self.reject(scope, receive, send, 415, 'Compressed request bodies are unsupported.')

        async def collect():
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    raise ConnectionError
                body.extend(message.get('body', b''))
                if len(body) > MAX_BODY_BYTES:
                    raise OverflowError
                if not message.get('more_body', False):
                    return bytes(body)
        try:
            body = await asyncio.wait_for(collect(), timeout=10)
        except OverflowError:
            return await self.reject(scope, receive, send, 413, 'Request body is too large.')
        except TimeoutError:
            return await self.reject(scope, receive, send, 408, 'Request body timed out.')
        except ConnectionError:
            return
        consumed = False

        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                out = list(message.get('headers', []))
                out.extend([(b'x-content-type-options', b'nosniff'), (b'referrer-policy', b'no-referrer'),
                            (b'cache-control', b'no-store')])
                dataset = getattr(scope.get('app').state, 'dataset', None)
                if dataset:
                    out.append((b'x-maps-dataset-version', dataset.version.encode()))
                message = {**message, 'headers': out}
            await send(message)
        return await self.host_checked(scope, bounded_receive, secure_send)


class Area(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str
    source_id: str
    name: str
    kind: str
    level: Level
    parent_id: str | None
    country_id: str
    assignment_status: str
    geometry_available: bool
    display_available: bool
    child_count: int
    aliases: list[str]
    issues: list[str]


class AreaPage(BaseModel):
    dataset_version: str
    total: int
    offset: int
    limit: int
    next_offset: int | None
    items: list[Area]


class AreaDetail(BaseModel):
    dataset_version: str
    area: Area


class PointInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    longitude: Annotated[float, Field(strict=True, ge=-180, le=180, allow_inf_nan=False)]
    latitude: Annotated[float, Field(strict=True, ge=-90, le=90, allow_inf_nan=False)]


class BatchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    points: Annotated[list[PointInput], Field(min_length=1, max_length=100)]


class Match(Area):
    match_basis: Literal['geometry', 'hierarchy']


class LookupResult(BaseModel):
    dataset_version: str
    qualification: Literal['review_required']
    status: Literal['matched', 'no_match', 'ambiguous', 'review_required']
    longitude: float
    latitude: float
    ambiguous: bool
    matches: list[Match]
    direct_match_ids: list[str]
    review_candidate_ids: list[str]
    unlocated_missing_geometry_ids: list[str]
    hierarchy_geometry_disagreements: list[dict[str, str]]


class BatchResult(BaseModel):
    dataset_version: str
    results: list[LookupResult]


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.dataset = await asyncio.to_thread(Dataset, settings.dataset, settings.manifest_sha256)
        LOG.info('Serving geography release %s (%d areas)', app.state.dataset.version, len(app.state.dataset.areas))
        yield
        del app.state.dataset

    app = FastAPI(title='Totally Normal Maps', version='1.0.0', lifespan=lifespan,
                  description='Read-only reference geography. API v1; independently versioned, review-required datasets. Coordinates use WGS84 longitude/latitude. Public source code does not grant access to a hosted service.',
                  redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type', 'If-Match', 'If-None-Match'],
                       expose_headers=['X-Maps-Dataset-Version', 'ETag'], allow_credentials=False)
    app.add_middleware(AccessMiddleware, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'error': 'Invalid request.', 'details': [
            {k: issue[k] for k in ('loc', 'msg', 'type')} for issue in exc.errors()]}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        LOG.error('Unhandled API failure', exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse({'error': 'Internal service error.'}, status_code=500, headers={'Cache-Control': 'no-store'})

    def dataset(request):
        data = request.app.state.dataset
        expected = request.headers.get('If-Match')
        if expected is not None and expected != f'"{data.version}"':
            raise HTTPException(412, 'Dataset version differs from If-Match; use the quoted dataset_version.')
        return data

    def area(data, uid):
        if uid not in data.areas:
            raise HTTPException(404, 'Unknown geographic area.')
        return data.areas[uid]

    def geo_response(payload, request):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(body) > MAX_RESPONSE_BYTES:
            raise HTTPException(413, 'Boundary response exceeds 16 MiB; use display resolution or a smaller page.')
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        if request.headers.get('If-None-Match') == etag:
            return Response(status_code=304, headers={'ETag': etag})
        return Response(body, media_type='application/geo+json', headers={'ETag': etag})

    @app.get('/healthz', tags=['Health'])
    def health():
        return {'status': 'ok'}

    @app.get('/readyz', tags=['Health'])
    def ready(request: Request):
        if not getattr(request.app.state, 'dataset', None):
            raise HTTPException(503, 'Dataset not loaded.')
        return {'status': 'ready'}

    @app.get('/v1/datasets/current', tags=['Dataset'])
    def current(request: Request):
        return dataset(request).summary

    @app.get('/v1/countries', response_model=AreaPage, tags=['Areas'])
    def countries(request: Request):
        return dataset(request).page(level='country')

    @app.get('/v1/areas', response_model=AreaPage, tags=['Areas'])
    def areas(request: Request, parent_id: str | None = Query(None, max_length=100),
              level: Level | None = None, q: str | None = Query(None, min_length=1, max_length=120),
              offset: int = Query(0, ge=0, le=100_000), limit: int = Query(100, ge=1, le=500)):
        data = dataset(request)
        if parent_id is not None:
            area(data, parent_id)
        return data.page(parent_id=parent_id, level=level, query=q, offset=offset, limit=limit)

    @app.get('/v1/areas/{area_id}', response_model=AreaDetail, tags=['Areas'])
    def detail(area_id: str, request: Request):
        data = dataset(request)
        return {'dataset_version': data.version, 'area': area(data, area_id)}

    @app.get('/v1/areas/{area_id}/children', response_model=AreaPage, tags=['Areas'])
    def children(area_id: str, request: Request, offset: int = Query(0, ge=0, le=100_000), limit: int = Query(100, ge=1, le=500)):
        data = dataset(request)
        area(data, area_id)
        return data.page(parent_id=area_id, offset=offset, limit=limit)

    @app.get('/v1/areas/{area_id}/ancestors', tags=['Areas'])
    def ancestors(area_id: str, request: Request):
        data = dataset(request)
        area(data, area_id)
        return {'dataset_version': data.version, 'items': data.ancestors(area_id)}

    @app.get('/v1/areas/{area_id}/boundary', tags=['Boundaries'], responses={200: {'content': {'application/geo+json': {}}}, 409: {'description': 'Boundary unavailable'}})
    def boundary(area_id: str, request: Request, resolution: Literal['display', 'full'] = 'display'):
        data = dataset(request)
        area(data, area_id)
        try:
            payload = data.boundary(area_id, resolution)
        except CatalogueError as exc:
            raise HTTPException(409, str(exc)) from None
        return geo_response(payload, request)

    @app.get('/v1/areas/{area_id}/children/boundaries', tags=['Boundaries'], responses={200: {'content': {'application/geo+json': {}}}})
    def children_boundaries(area_id: str, request: Request, offset: int = Query(0, ge=0, le=100_000), limit: int = Query(100, ge=1, le=500)):
        data = dataset(request)
        area(data, area_id)
        page = data.page(parent_id=area_id, offset=offset, limit=limit)
        features = [data.boundary(r['id']) for r in page['items'] if r['display_available']]
        return geo_response({'type': 'FeatureCollection', 'features': features,
            'dataset_version': data.version, 'total': page['total'], 'offset': offset, 'limit': limit,
            'next_offset': page['next_offset'], 'unavailable_ids': [r['id'] for r in page['items'] if not r['display_available']]}, request)

    @app.get('/v1/lookup', response_model=LookupResult, tags=['Lookup'])
    def lookup(request: Request, longitude: float = Query(..., ge=-180, le=180, allow_inf_nan=False),
               latitude: float = Query(..., ge=-90, le=90, allow_inf_nan=False)):
        return dataset(request).lookup(longitude, latitude)

    @app.post('/v1/lookup', response_model=LookupResult, tags=['Lookup'])
    def lookup_post(point: PointInput, request: Request):
        return dataset(request).lookup(point.longitude, point.latitude)

    @app.post('/v1/lookup/batch', response_model=BatchResult, tags=['Lookup'])
    def batch(points: BatchInput, request: Request):
        data = dataset(request)
        return {'dataset_version': data.version, 'results': [data.lookup(p.longitude, p.latitude) for p in points.points]}

    original_openapi = app.openapi

    def openapi():
        spec = original_openapi()
        spec.setdefault('components', {}).setdefault('securitySchemes', {})['BearerAuth'] = {'type': 'http', 'scheme': 'bearer'}
        for path, methods in spec['paths'].items():
            if path.startswith('/v1/'):
                for method in methods.values():
                    method['security'] = [{'BearerAuth': []}]
        return spec
    app.openapi = openapi
    return app
