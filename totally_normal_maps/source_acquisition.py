"""Explicit network acquisition; never called by a build, server, or ordinary test."""
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from .catalogue import CatalogueError

MAX_BYTES = 32 * 1024 * 1024


def _request(url):
    with urlopen(url, timeout=30) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise CatalogueError('Source response exceeds its byte budget.')
    return json.loads(content)


def arcgis_snapshot(source, *, request=_request):
    """Fetch full features by object ID, rejecting pagination and snapshot drift."""
    acquisition = source['acquisition']
    url = acquisition['layer_url']
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment or
            acquisition.get('kind') != 'arcgis'):
        raise CatalogueError('Expected a public HTTPS ArcGIS layer URL.')

    def query(**args):
        result = request(url + '/query?' + urlencode(args))
        if result.get('error') or result.get('exceededTransferLimit'):
            raise CatalogueError('Incomplete or rejected source query.')
        return result

    def metadata():
        result = request(url + '?f=json')
        if (result.get('name') != acquisition['layer_name'] or
                result.get('geometryType') != 'esriGeometryPolygon'):
            raise CatalogueError('Publisher layer identity or geometry type changed.')
        return result

    before = metadata()
    ids = query(f='json', where='1=1', returnIdsOnly='true')
    object_ids = ids.get('objectIds', [])
    field = ids.get('objectIdFieldName')
    count = query(f='json', where='1=1', returnCountOnly='true').get('count')
    if (not field or any(type(i) is not int for i in object_ids) or
            len(object_ids) != len(set(object_ids)) or len(object_ids) != count or count != source['expected_count']):
        raise CatalogueError('Publisher count or identity inventory differs from the source plan.')
    features, seen, total = [], set(), 0
    ordered = sorted(object_ids)
    for start in range(0, len(ordered), 100):
        chunk = ordered[start:start+100]
        payload = query(f='geojson', objectIds=','.join(map(str, chunk)), outFields='*', outSR=4326,
                        returnGeometry='true')
        rows = payload.get('features', [])
        returned = [f['properties'].get(field) for f in rows]
        if payload.get('type') != 'FeatureCollection' or set(returned) != set(chunk) or len(returned) != len(chunk) or seen.intersection(returned):
            raise CatalogueError('Source page has missing, duplicate or unexpected features.')
        seen.update(returned)
        features.extend(rows)
        total += len(json.dumps(payload).encode())
        if total > MAX_BYTES:
            raise CatalogueError('Complete source exceeds its byte budget.')
    after_ids = query(f='json', where='1=1', returnIdsOnly='true').get('objectIds', [])
    after = metadata()
    if (set(after_ids) != seen or len(after_ids) != len(seen) or
            before.get('editingInfo') != after.get('editingInfo')):
        raise CatalogueError('Publisher changed during source acquisition.')
    features.sort(key=lambda feature: feature['properties'][field])
    return (json.dumps({'type': 'FeatureCollection', 'features': features},
                       ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def download_source(source, destination):
    """Publish only bytes matching the previously qualified checksum, without overwrite."""
    if not source.get('acquisition'):
        from .__main__ import download
        return download(destination, manifest=source, max_bytes=MAX_BYTES)
    content = arcgis_snapshot(source)
    digest = hashlib.sha256(content).hexdigest()
    if digest != source['sha256']:
        raise CatalogueError('Source snapshot changed; requalification is required.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation via hard link publishes the complete checked temporary file.
    with tempfile.NamedTemporaryFile(dir=destination.parent) as temporary:
        temporary.write(content); temporary.flush()
        try:
            destination.hardlink_to(temporary.name)
        except FileExistsError as exc:
            raise CatalogueError('Source destination exists; refusing overwrite.') from exc
    return {'sha256': digest, 'bytes': len(content), 'output': str(destination)}
