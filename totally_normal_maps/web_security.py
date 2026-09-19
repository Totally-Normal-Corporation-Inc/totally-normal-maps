"""Allow only the optional, named map-image providers; scripts remain local."""

MAP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://maps.geogratis.gc.ca https://geoappext.nrcan.gc.ca; "
    "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'none'"
)
