"""Explicit network acquisition; never called by a build, server, or ordinary test."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import re
from collections import Counter
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from .catalogue import CatalogueError

# Complete provincial coastal electoral inventories exceed 32 MiB. This bound
# applies only to explicit offline acquisition, never to serving requests.
MAX_BYTES = 128 * 1024 * 1024


def _raw_request(url):
    with urlopen(url, timeout=90) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES: raise CatalogueError('Source response exceeds its byte budget.')
    return content


def represent_snapshot(source, *, request=_raw_request, pause=time.sleep):
    """Join full shapes to stable publisher IDs; never use simplified geometry."""
    acquisition = source['acquisition']; slug = acquisition.get('slug')
    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}', slug):
        raise CatalogueError('Invalid Represent boundary-set slug.')
    base = 'https://represent.opennorth.ca/boundaries/' + slug
    raw = request(base + '/?limit=1000'); pause(1.1)
    shapes = request(base + '/shape'); pause(1.1)
    if any(hashlib.sha256(content).hexdigest() != acquisition.get(key) for content,key in
           ((raw,'inventory_sha256'),(shapes,'shape_sha256'))):
        raise CatalogueError('Represent snapshot changed; requalification is required.')
    try:
        inventory = json.loads(raw); objects = inventory['objects']; geometry = json.loads(shapes)['objects']
        identities = {row['name']: row['external_id'] for row in objects}
        if (inventory.get('meta', {}).get('next') or len(identities) != len(objects)
                or len(set(identities.values())) != len(objects) or len(objects) != source['expected_count']
                or any(not isinstance(k, str) or not k or type(v) not in (int,str) or not str(v) for k,v in identities.items())
                or Counter(row['name'] for row in geometry) != Counter(identities.keys())):
            raise ValueError('Incomplete identity join')
        features = [{'type':'Feature','properties':{'code':str(identities[row['name']]),'name':row['name']},
                     'geometry':row['shape']} for row in geometry]
    except (KeyError, TypeError, ValueError):
        raise CatalogueError('Represent inventory and full shapes do not form a unique complete join.') from None
    return (json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False,
                       sort_keys=True,separators=(',',':'))+'\n').encode()


def _request(url):
    with urlopen(url, timeout=30) as response:
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise CatalogueError('Source response exceeds its byte budget.')
    try:
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise CatalogueError('Publisher returned an invalid JSON source response.') from None


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
        if not isinstance(result, dict) or result.get('error') or result.get('exceededTransferLimit'):
            raise CatalogueError('Incomplete or rejected source query.')
        return result

    def metadata():
        result = request(url + '?f=json')
        if (not isinstance(result, dict) or result.get('name') != acquisition['layer_name'] or
                result.get('geometryType') != 'esriGeometryPolygon'):
            raise CatalogueError('Publisher layer identity or geometry type changed.')
        return result

    before = metadata()
    ids = query(f='json', where='1=1', returnIdsOnly='true')
    object_ids = ids.get('objectIds', [])
    field = ids.get('objectIdFieldName')
    count = query(f='json', where='1=1', returnCountOnly='true').get('count')
    if (not isinstance(field, str) or not field or not isinstance(object_ids, list)
            or type(count) is not int or any(type(i) is not int for i in object_ids) or
            len(object_ids) != len(set(object_ids)) or len(object_ids) != count or count != source['expected_count']):
        raise CatalogueError('Publisher count or identity inventory differs from the source plan.')
    features, seen, total = [], set(), 0
    ordered = sorted(object_ids)
    for start in range(0, len(ordered), 100):
        chunk = ordered[start:start+100]
        payload = query(f='geojson', objectIds=','.join(map(str, chunk)), outFields='*', outSR=4326,
                        returnGeometry='true')
        rows = payload.get('features', [])
        if (not isinstance(rows, list) or any(not isinstance(f, dict) or f.get('type') != 'Feature'
                or not isinstance(f.get('properties'), dict) or 'geometry' not in f for f in rows)):
            raise CatalogueError('Source page contains malformed features.')
        returned = [f['properties'].get(field) for f in rows]
        if (payload.get('type') != 'FeatureCollection' or any(type(uid) is not int for uid in returned)
                or set(returned) != set(chunk) or len(returned) != len(chunk) or seen.intersection(returned)):
            raise CatalogueError('Source page has missing, duplicate or unexpected features.')
        seen.update(returned)
        features.extend(rows)
        total += len(json.dumps(payload).encode())
        if total > MAX_BYTES:
            raise CatalogueError('Complete source exceeds its byte budget.')
    after_ids = query(f='json', where='1=1', returnIdsOnly='true').get('objectIds', [])
    after = metadata()
    if (not isinstance(after_ids, list) or any(type(uid) is not int for uid in after_ids)
            or set(after_ids) != seen or len(after_ids) != len(seen) or
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
    kind = source['acquisition']['kind']
    if kind not in {'wfs', 'arcgis', 'represent'}: raise CatalogueError('Unknown source acquisition method.')
    content = {'wfs':wfs_snapshot, 'arcgis':arcgis_snapshot, 'represent':represent_snapshot}[kind](source)
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


def wfs_snapshot(source, *, request=_request):
    """Canonical full WFS response; exclude generated transport feature IDs."""
    acquisition = source['acquisition']
    url = acquisition['url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment:
        raise CatalogueError('Expected a public HTTPS WFS query.')
    payload = request(url)
    if not isinstance(payload, dict): raise CatalogueError('Malformed WFS response.')
    rows = payload.get('features', [])
    if (not isinstance(rows, list) or payload.get('type') != 'FeatureCollection'
            or len(rows) != source['expected_count']
            or type(payload.get('numberMatched')) is not int or type(payload.get('numberReturned')) is not int
            or payload.get('numberMatched') != len(rows) or payload.get('numberReturned') != len(rows)):
        raise CatalogueError('Incomplete WFS source inventory.')
    fields = acquisition['fields']
    if (not isinstance(fields, list) or any(not isinstance(f, str) or not f for f in fields)
            or source['id_field'] not in fields or len(set(fields)) != len(fields)
            or any(not isinstance(r, dict) or r.get('type') != 'Feature' or 'geometry' not in r
                   or not isinstance(r.get('properties'), dict) or not set(fields) <= r['properties'].keys() for r in rows)):
        raise CatalogueError('WFS source fields changed or a feature is malformed.')
    features = [{'type': 'Feature', 'geometry': r['geometry'],
                 'properties': {key: r['properties'][key] for key in fields}} for r in rows]
    identities = [r['properties'][source['id_field']] for r in features]
    if (any(type(uid) not in (str, int) or not str(uid).strip() for uid in identities)
            or len(set(identities)) != len(identities)):
        raise CatalogueError('Invalid or duplicate WFS identity.')
    features.sort(key=lambda r: str(r['properties'][source['id_field']]))
    try:
        content = (json.dumps({'type': 'FeatureCollection', 'features': features},
                             allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    except ValueError:
        raise CatalogueError('WFS source contains nonfinite values.') from None
    if len(content) > MAX_BYTES: raise CatalogueError('Complete WFS source exceeds its byte budget.')
    return content
