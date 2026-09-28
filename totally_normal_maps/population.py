"""Immutable population snapshots. Only operator commands read source files.

Population is separate from assignment geometry and from catalogue ordering.
An explicit, geometry-bound crosswalk is required even when CSD codes agree.
"""
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zipfile import ZipFile, BadZipFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator, field_validator

from .catalogue import CatalogueError, PROVINCES, new_directory, read_json, sha256, write_json
from .releases import validate_manifest

MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024
MAX_COUNT = 1_000_000_000
HEX = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Unavailable = Literal['no_source', 'unmatched_geography', 'incompatible_boundary',
                      'suppressed', 'not_available', 'not_enumerated', 'withdrawn']
Quality = Literal['revised', 'use_with_caution', 'incomplete_enumeration']
REASONS = ('no_source', 'unmatched_geography', 'incompatible_boundary', 'suppressed',
           'not_available', 'not_enumerated', 'withdrawn')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise CatalogueError(message)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Credit(Model):
    publisher: Text
    dataset: Text
    record_id: Text
    url: str = Field(max_length=500)

    @field_validator('url')
    @classmethod
    def public_url(cls, value):
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.fragment:
            raise ValueError('Expected a public HTTPS source URL.')
        return value


class Population(Model):
    count: Annotated[int, Field(ge=0, le=MAX_COUNT)]
    reference_year: Annotated[int, Field(ge=1900, le=2100)]
    measure: Literal['usual_residents'] = 'usual_residents'
    method: Literal['census_count', 'census_count_boundary_adjusted']
    source: Credit
    geography_reference: Text
    quality_flags: list[Quality] = Field(default_factory=list, max_length=3)

    @field_validator('quality_flags')
    @classmethod
    def unique_flags(cls, value):
        if value != sorted(set(value)):
            raise ValueError('Quality flags must be unique and sorted.')
        return value


class Metadata(Model):
    population: Population | None
    population_unavailable_reason: Unavailable | None

    @model_validator(mode='after')
    def exclusive(self):
        if (self.population is None) == (self.population_unavailable_reason is None):
            raise ValueError('Population and unavailable reason must be mutually exclusive.')
        return self


class Source(Model):
    publisher: Literal['Statistics Canada'] = 'Statistics Canada'
    dataset: Text
    url: str = Field(max_length=500)
    download_url: str = Field(max_length=500)
    filename: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,100}$')
    sha256: HEX
    release: Text
    retrieved_on: str
    reference_date: str
    geography_reference: Text
    licence: Literal['https://www.statcan.gc.ca/en/terms-conditions/open-licence']
    format: Literal['statcan_98100002_zip', 'statcan_interim_csv']
    encoding: Literal['utf-8-sig', 'cp1252'] = 'utf-8-sig'
    expected_count: Annotated[int, Field(ge=1, le=100000)]
    identity_sha256: HEX
    unavailable_symbol_reason: Literal['not_available', 'not_enumerated'] = 'not_available'

    _urls = field_validator('url', 'download_url')(Credit.public_url.__func__)

    @model_validator(mode='after')
    def supported_source(self):
        if self.reference_date != '2021-05-11':
            raise ValueError('This importer requires the 2021 Census measurement date.')
        if self.format == 'statcan_98100002_zip' and (self.dataset != '98-10-0002-01'
                or self.geography_reference != 'statcan-csd-2021-01-01'):
            raise ValueError('Census table identity or geography vintage mismatch.')
        if self.format == 'statcan_interim_csv' and not re.fullmatch(r'92F0009X-20\d{2}', self.dataset):
            raise ValueError('Invalid interim list identity.')
        for url in (self.url, self.download_url):
            if not urlsplit(url).hostname.endswith('.statcan.gc.ca'):
                raise ValueError('This importer accepts official Statistics Canada sources only.')
        return self

    @field_validator('retrieved_on', 'reference_date')
    @classmethod
    def iso_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('Expected YYYY-MM-DD.')
        return value


class Adjustment(Model):
    source: Text
    record_id: HEX
    direction: Literal['gain', 'loss']


class TransferEvidence(Adjustment):
    population_affected: Annotated[int, Field(ge=0, le=MAX_COUNT)]
    file_number: str = Field(pattern=r'^\d{6}$')
    effective_date: Text


class Calculation(Model):
    source_count: Annotated[int, Field(ge=0, le=MAX_COUNT)] | None
    source_unavailable_reason: Unavailable | None
    quality_flags: list[Quality] = Field(max_length=3)
    transfers: list[TransferEvidence] = Field(max_length=50)


class Match(Model):
    source: Text
    record_id: Annotated[str, Field(pattern=r'^2021A0005[0-9]{7}$')]
    target_sha256: HEX
    basis: Literal['equivalent_geometry', 'reviewed_equivalence', 'official_adjustment']
    geography_reference: Text
    evidence: list[Text] = Field(min_length=1, max_length=20)
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def adjustment_basis(self):
        if bool(self.adjustments) != (self.basis == 'official_adjustment'):
            raise ValueError('Official adjustments require explicit transaction records.')
        if len({a.record_id for a in self.adjustments}) != len(self.adjustments):
            raise ValueError('An official transaction row cannot be applied more than once.')
        return self


class Missing(Model):
    reason: Unavailable
    target_sha256: HEX
    evidence: list[Text] = Field(min_length=1, max_length=20)


class Plan(Model):
    schema_version: Literal[1]
    base_dataset_version: HEX
    reviewed_on: str
    reference_year: Literal[2021]
    sources: dict[str, Source] = Field(min_length=1, max_length=20)
    matches: dict[str, Match]
    unavailable: dict[str, Missing]

    _date = field_validator('reviewed_on')(Source.iso_date.__func__)

    @model_validator(mode='after')
    def one_census_snapshot(self):
        validate_source_selection(self.sources)
        return self


def validate(model, value):
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError) as exc:
        raise CatalogueError('Malformed population metadata or import plan.') from exc


def identity_hash(ids):
    return hashlib.sha256(('\n'.join(sorted(ids)) + '\n').encode()).hexdigest()


def validate_source_selection(sources):
    require(1 <= len(sources) <= 20 and sum(s.format == 'statcan_98100002_zip' for s in sources.values()) == 1,
            'Select exactly one comparable census population snapshot.')
    require(len({(s.publisher, s.dataset) for s in sources.values()}) == len(sources),
            'Select one snapshot per source product; aliases cannot duplicate population transfers.')


def source_citations(sources):
    return {key: {'authority': s.publisher, 'family': s.dataset, 'release': s.release,
                  'reference_date': s.reference_date, 'retrieved_on': s.retrieved_on, 'url': s.url,
                  'licence': s.licence, 'sha256': s.sha256,
                  'attribution': f'Adapted from Statistics Canada, {s.dataset}, {s.reference_date}. '
                      'This does not constitute an endorsement by Statistics Canada of this product.'}
            for key, s in sorted(sources.items())}


def validate_match(data, uid, match, sources, used):
    require(match.source in sources and sources[match.source].format == 'statcan_98100002_zip',
            'Population match must select census population facts.')
    require(match.basis != 'equivalent_geometry' or match.record_id == '2021A0005' + data.areas[uid]['source_id'],
            'Automatic population equivalence requires the same authoritative source code.')
    require(match.record_id not in used, 'A source municipality cannot supply multiple current territories.')
    used.add(match.record_id)
    require(all(a.source in sources and sources[a.source].format == 'statcan_interim_csv' for a in match.adjustments),
            'Population transfers must reference official interim sources.')


def interim_rows(path, encoding):
    with Path(path).open(encoding=encoding, newline='') as raw:
        rows = csv.reader(raw)
        for _ in range(3):
            header = next(rows, [])
            if header and header[0] == 'Gaining CSDuid':
                break
            require(not header or header[0] in {'Table 1', 'Changes to census subdivisions by province and territory'},
                    'Unexpected interim table preamble.')
        while header and not header[-1]:
            header.pop()
        expected = {'Gaining CSDuid', 'Losing CSDuid', 'Census Population Affected', 'Effective Date', 'File Number'}
        require(expected <= set(header) and len(header) == len(set(header)), 'Interim population table schema changed.')
        for values in rows:
            if not values:
                continue
            require(len(values) >= len(header) and not any(values[len(header):]), 'Incomplete interim table row.')
            row = dict(zip(header, values))
            if not row['File Number']:
                headings = {p[1] for p in PROVINCES.values()} | {'Quebec', '... not applicable', ''}
                require(row['Gaining CSDuid'] in headings and not any(row.get(k, '').strip('. ') for k in expected - {'Gaining CSDuid'}),
                        'Unrecognized interim table record.')
                continue
            yield row


def source_rows(path, source):
    """Check the *whole* input before returning facts; unknown symbols fail closed."""
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_SOURCE_BYTES,
            'Expected a bounded local population source file.')
    require(sha256(path) == source.sha256, 'Population source checksum mismatch; qualify changes explicitly.')
    facts = {}
    if source.format == 'statcan_98100002_zip':
        try:
            with ZipFile(path) as archive:
                entries = archive.infolist()
                require(len(entries) == 2 and {e.filename for e in entries} == {'98100002.csv', '98100002_MetaData.csv'}
                        and sum(e.file_size for e in entries) <= MAX_SOURCE_BYTES
                        and not any(e.flag_bits & 1 for e in entries), 'Unexpected population archive members or size.')
                with archive.open('98100002.csv') as raw:
                    rows = csv.reader(io.TextIOWrapper(raw, encoding=source.encoding))
                    header = next(rows)
                    require(len(header) == 30 and header[:6] == ['REF_DATE', 'GEO', 'DGUID', 'Coordinate',
                            'Population and dwelling counts (13): Population, 2021 [1]', 'Symbols'],
                            'Population table schema changed.')
                    for row in rows:
                        if not row:
                            continue
                        require(len(row) == len(header) and row[0] == '2021', 'Incomplete or unexpected population row.')
                        uid, value, symbol = row[2], row[4], row[5]
                        require(bool(re.fullmatch(r'2021A000[0235]\d{2,7}', uid)), 'Unexpected census geography identifier.')
                        if not uid.startswith('2021A0005'):
                            continue  # Municipality/equivalent facts only; never metro/dwellings/rank.
                        require(bool(re.fullmatch(r'2021A0005\d{7}', uid)), 'Malformed census subdivision identifier.')
                        require(uid not in facts, 'Duplicate population geography.')
                        flags, reason = [], None
                        if symbol in {'x', '..', '...'}:
                            require(value == '', 'Unavailable census population contains a numeric value.')
                            count = None
                            reason = 'suppressed' if symbol == 'x' else source.unavailable_symbol_reason if symbol == '..' else 'not_available'
                        else:
                            require(symbol in {'', 'r', 'E'} and bool(re.fullmatch(r'\d+', value)), 'Malformed census population or symbol.')
                            count = int(value)
                            require(count <= MAX_COUNT, 'Population count exceeds its bound.')
                            flags = {'': [], 'r': ['revised'], 'E': ['use_with_caution']}[symbol]
                        facts[uid] = {'count': count, 'reason': reason, 'quality_flags': flags, 'name': row[1]}
        except (BadZipFile, UnicodeError, csv.Error, StopIteration) as exc:
            raise CatalogueError('Unreadable population archive.') from exc
    else:
        for row in interim_rows(path, source.encoding):
            require(bool(re.fullmatch(r'\d{6}', row['File Number'])), 'Invalid interim transaction identity.')
            # Hash identifies the complete authoritative row, not a guessed name or a moving line number.
            uid = digest(row)
            require(uid not in facts, 'Duplicate interim transaction row.')
            value = row['Census Population Affected']
            try:
                n = Decimal(value)
                require(n.is_finite() and n == n.to_integral_value() and 0 <= n <= MAX_COUNT,
                        'Fractional or invalid official population transfer.')
                count = int(n)
            except InvalidOperation:
                require(value in {'...', '…', '', '..'}, 'Unknown official population transfer value.')
                count = None  # Not-applicable is NEVER an assumed zero transfer.
            facts[uid] = {'count': count, 'gain': row['Gaining CSDuid'], 'loss': row['Losing CSDuid'],
                          'file_number': row['File Number'], 'effective_date': row['Effective Date'], 'row': row}
    require(sha256(path) == source.sha256, 'Population source changed during import.')
    require(len(facts) == source.expected_count and identity_hash(facts) == source.identity_sha256,
            'Population source inventory is incomplete or changed.')
    return facts


def territory_fingerprint(data, uid):
    """Internal stale-crosswalk guard, NOT a consumer classification revision."""
    row = data.areas[uid]
    fields = ('id', 'source_id', 'level', 'province_id', 'parent_id', 'lifecycle_status', 'effective_date',
              'boundary_basis', 'uncertainty_basis', 'assignment_status', 'predecessor_ids', 'successor_ids', 'repair')
    full = data.geometries.get(uid)
    pending = [hashlib.sha256(g.wkb).hexdigest() for key, g in zip(data.pending_ids, data.pending_shapes) if key == uid]
    return digest({'area': {k: row[k] for k in fields if k in row},
                   'full': None if full is None else hashlib.sha256(full.wkb).hexdigest(), 'pending': sorted(pending)})


def eligible(data):
    return {uid for uid, row in data.areas.items() if row['level'] == 'municipality'
            and row.get('layer', 'administrative') == 'administrative' and row.get('lifecycle_status') != 'superseded'}


def metadata(data, row):
    record = data.populations.get(row['id'])
    value = record['metadata'] if record else {'population': None, 'population_unavailable_reason': 'no_source'}
    return {**row, **value}


def metadata_page(data, page):
    return {**page, 'items': [metadata(data, row) for row in page['items']]}


def load_population(data):
    """Validate persisted values and their territory bindings once, at startup."""
    data.populations, data.population_sources = {}, {}
    with closing(sqlite3.connect((data.root / 'catalogue.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        present = {'area_population', 'population_source'} & tables
        if not present:
            require('population' not in data.report, 'Population report lacks stored records.')
            return
        require(present == {'area_population', 'population_source'} and 'population' in data.report,
                'Incomplete population snapshot.')
        sources = {key: validate(Source, json.loads(raw)) for key, raw in db.execute('SELECT id, record FROM population_source')}
        validate_source_selection(sources)
        data.population_sources = {key: source.model_dump() for key, source in sources.items()}
        population = eligible(data)
        used = set()
        for uid, raw in db.execute('SELECT area_id, record FROM area_population ORDER BY area_id'):
            require(uid in population and len(raw.encode()) <= MAX_RECORD_BYTES, 'Invalid population area or oversized evidence.')
            record = json.loads(raw)
            require(isinstance(record, dict) and set(record) == {'metadata', 'target_sha256', 'source_keys', 'evidence', 'calculation'}, 'Unexpected population record fields.')
            value = validate(Metadata, record['metadata'])
            require(record['target_sha256'] == territory_fingerprint(data, uid), 'Population crosswalk is stale for the served territory.')
            require(isinstance(record['source_keys'], list) and all(isinstance(k, str) for k in record['source_keys'])
                    and set(record['source_keys']) <= sources.keys(), 'Population provenance is missing.')
            require(value.population is None or bool(record['source_keys']), 'Population count lacks a source.')
            require(isinstance(record['evidence'], dict), 'Malformed population evidence.')
            proof = validate(Match if 'source' in record['evidence'] else Missing, record['evidence'])
            require(proof.target_sha256 == record['target_sha256'], 'Population proof/target mismatch.')
            if isinstance(proof, Match):
                validate_match(data, uid, proof, sources, used)
                calculation = validate(Calculation, record['calculation'])
                require([Adjustment.model_validate(t.model_dump(include={'source', 'record_id', 'direction'})).model_dump()
                         for t in calculation.transfers] == [t.model_dump() for t in proof.adjustments],
                        'Population calculation differs from its crosswalk.')
                require(record['source_keys'] == sorted({proof.source, *(t.source for t in proof.adjustments)}),
                        'Population calculation source inventory differs.')
                if value.population is not None:
                    require(calculation.source_count is not None and calculation.source_unavailable_reason is None,
                            'Available population has no source count.')
                    total = calculation.source_count + sum(t.population_affected * (1 if t.direction == 'gain' else -1)
                                                           for t in calculation.transfers)
                    require(value.population.count == total and value.population.quality_flags == calculation.quality_flags
                            and value.population.method == ('census_count_boundary_adjusted' if proof.adjustments else 'census_count'),
                            'Population does not match its recorded calculation.')
                else:
                    require(calculation.source_count is None and not calculation.transfers
                            and calculation.source_unavailable_reason == value.population_unavailable_reason,
                            'Unavailable population differs from source evidence.')
            else:
                require(record['calculation'] is None and value.population is None
                        and value.population_unavailable_reason == proof.reason and not record['source_keys'],
                        'Unavailable population differs from its reviewed reason.')
            if value.population is not None:
                source = sources.get(proof.source)
                require(source is not None and value.population.source.model_dump() == {
                    'publisher': source.publisher, 'dataset': source.dataset, 'record_id': proof.record_id, 'url': source.url}
                    and value.population.reference_year == 2021
                    and value.population.geography_reference == proof.geography_reference,
                    'Population provenance does not match its stored source.')
            record['metadata'] = value.model_dump()
            data.populations[uid] = record
        require(set(data.populations) == population, 'Population snapshot does not account for every active municipality.')
        require(isinstance(data.report['population'], dict) and data.report['population'].get('reference_year') == 2021
                and data.report['population'].get('sources') == source_citations(sources),
                'Population report/source citations differ from the stored snapshot.')
        require(data.report['population'].get('records_sha256') == digest(data.populations), 'Population report/records mismatch.')
        require(data.report['population'].get('source_records_sha256') == digest({k: v.model_dump() for k, v in sources.items()}),
                'Population report/source mismatch.')
        require(data.report['population'].get('coverage') == coverage(data, data.populations), 'Population coverage report mismatch.')


def coverage(data, records):
    levels, provinces = defaultdict(Counter), defaultdict(Counter)
    for uid, row in data.areas.items():
        if row.get('layer', 'administrative') not in {'administrative', 'shared'} or row.get('lifecycle_status') == 'superseded':
            continue
        value = records.get(uid, {}).get('metadata', {'population': None, 'population_unavailable_reason': 'no_source'})
        status = 'known' if value['population'] is not None else value['population_unavailable_reason']
        for tally in (levels[row['level']], provinces[row.get('province_id', uid)]):
            tally['total'] += 1; tally[status] += 1
            if value['population'] is not None and value['population']['count'] == 0:
                tally['zero'] += 1  # Subset of known, never another missing state.
    return {'by_level': {k: dict(sorted(v.items())) for k, v in sorted(levels.items())},
            'by_province': {k: dict(sorted(v.items())) for k, v in sorted(provinces.items())}}


def prepare_records(data, plan, facts):
    population = eligible(data)
    require(not set(plan.matches) & set(plan.unavailable) and set(plan.matches) | set(plan.unavailable) == population,
            'Crosswalk must account exactly once for every active municipality.')
    records, used = {}, set()
    for uid in sorted(population):
        match = plan.matches.get(uid)
        selection = match or plan.unavailable[uid]
        require(selection.target_sha256 == territory_fingerprint(data, uid), 'Population crosswalk target changed.')
        keys, calculation = [], None
        if not match:
            value = Metadata(population=None, population_unavailable_reason=selection.reason)
        else:
            validate_match(data, uid, match, plan.sources, used)
            source, fact = plan.sources[match.source], facts[match.source].get(match.record_id)
            require(fact is not None, 'Unknown municipal population source record.')
            keys.append(match.source)
            count, flags = fact['count'], fact['quality_flags']
            calculation = {'source_count': count, 'source_unavailable_reason': fact['reason'],
                           'quality_flags': flags, 'transfers': []}
            transfers = set()
            for adjustment in match.adjustments:
                key = (adjustment.source, adjustment.record_id)
                require(key not in transfers and adjustment.source in plan.sources
                        and plan.sources[adjustment.source].format == 'statcan_interim_csv', 'Duplicate or unsupported population adjustment.')
                transfers.add(key)
                transaction = facts[adjustment.source].get(adjustment.record_id)
                require(transaction is not None and transaction['count'] is not None and count is not None,
                        'Official population transfer is unavailable; it cannot be assumed zero.')
                require(transaction[adjustment.direction] == match.record_id.removeprefix('2021A0005'),
                        'Official population transfer concerns a different municipality.')
                count += transaction['count'] * (1 if adjustment.direction == 'gain' else -1)
                keys.append(adjustment.source)
                calculation['transfers'].append({**adjustment.model_dump(), 'population_affected': transaction['count'],
                    'file_number': transaction['file_number'], 'effective_date': transaction['effective_date']})
            if count is None:
                value = Metadata(population=None, population_unavailable_reason=fact['reason'])
            else:
                value = validate(Metadata, {'population': {'count': count, 'reference_year': plan.reference_year,
                    'method': 'census_count_boundary_adjusted' if match.adjustments else 'census_count',
                    'source': {'publisher': source.publisher, 'dataset': source.dataset, 'record_id': match.record_id, 'url': source.url},
                    'geography_reference': match.geography_reference, 'quality_flags': flags}, 'population_unavailable_reason': None})
        record = {'metadata': value.model_dump(), 'target_sha256': selection.target_sha256,
                  'source_keys': sorted(set(keys)), 'evidence': selection.model_dump(), 'calculation': calculation}
        require(len(encoded(record)) <= MAX_RECORD_BYTES, 'Population evidence record exceeds its bound.')
        records[uid] = record
    return records


def import_population(dataset, output, *, plan_path, source_dir, expected_sha256, retrieval_date_correction_reason=None):
    from .dataset import Dataset
    data = Dataset(dataset, expected_sha256)
    plan = validate(Plan, read_json(plan_path, 32 * 1024 * 1024))
    require(plan.base_dataset_version == data.version, 'Population plan pins a different input dataset.')
    facts = {key: source_rows(Path(source_dir) / source.filename, source) for key, source in sorted(plan.sources.items())}
    records = prepare_records(data, plan, facts)
    output = Path(output).resolve()
    require(not output.is_relative_to(data.root), 'Population output must be outside the input release.')
    existing = Dataset(output) if output.exists() else None
    require(retrieval_date_correction_reason is None or isinstance(retrieval_date_correction_reason, str)
            and 1 <= len(retrieval_date_correction_reason) <= 200 and bool(retrieval_date_correction_reason.strip()),
            'Expected a bounded retrieval-date correction reason.')
    # Refresh attempt dates are audit logs, not a reason to mint another dataset.
    source_records = {k: v.model_dump() for k, v in sorted(plan.sources.items())}
    date_corrections = {}
    for key, source in source_records.items():
        for old in (data.population_sources.get(key), existing.population_sources.get(key) if existing else None):
            if old and {k: v for k, v in old.items() if k != 'retrieved_on'} == {k: v for k, v in source.items() if k != 'retrieved_on'}:
                if retrieval_date_correction_reason is None:
                    source['retrieved_on'] = old['retrieved_on']
                elif source['retrieved_on'] != old['retrieved_on']:
                    date_corrections[key] = {'previous': old['retrieved_on'], 'corrected': source['retrieved_on']}
                break
    previous = data.report.get('population', {})
    if records == data.populations and previous.get('source_records_sha256') == digest(source_records):
        return {'status': 'unchanged', 'dataset_version': data.version, 'output': str(data.root)}
    summary = {'reference_year': plan.reference_year, 'reviewed_on': plan.reviewed_on, 'base_dataset_version': data.version,
               'records_sha256': digest(records), 'source_records_sha256': digest(source_records),
               'coverage': coverage(data, records),
               'sources': source_citations({key: validate(Source, value) for key, value in source_records.items()})}
    if date_corrections:
        summary['retrieval_date_correction'] = {'reason': retrieval_date_correction_reason, 'sources': date_corrections}
    if existing:
        require(existing.report.get('population', {}).get('base_dataset_version') == data.version
                and existing.populations == records and existing.population_sources == source_records,
                'Population output exists with different inputs; choose a new destination.')
        return {'status': 'unchanged', 'dataset_version': existing.version, 'output': str(output)}
    with new_directory(output) as staging:
        for name in data.manifest['files']:
            target = staging / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(data.root / name, target)
            require(sha256(target) == data.manifest['files'][name]['sha256'], 'Input release changed while preparing population.')
        with closing(sqlite3.connect(staging / 'catalogue.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS area_population (area_id TEXT PRIMARY KEY, record TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS population_source (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
            db.execute('DELETE FROM area_population'); db.execute('DELETE FROM population_source')
            db.executemany('INSERT INTO area_population VALUES (?, ?)', [(uid, encoded(row).decode()) for uid, row in sorted(records.items())])
            db.executemany('INSERT INTO population_source VALUES (?, ?)', [(uid, encoded(row).decode()) for uid, row in source_records.items()])
        report = {**data.report, 'catalogue_sha256': sha256(staging / 'catalogue.sqlite3'), 'population': summary}
        write_json(staging / 'report.json', report)
        manifest = {**data.manifest, 'files': {name: {'bytes': (staging / name).stat().st_size, 'sha256': sha256(staging / name)}
                                             for name in data.manifest['files']}}
        validate_manifest(manifest); write_json(staging / 'manifest.json', manifest)
        Dataset(staging)  # All old geometry checks and population bindings before atomic publication.
    return {'status': 'prepared', 'dataset_version': sha256(output / 'manifest.json'), 'output': str(output),
            'coverage': summary['coverage']}
