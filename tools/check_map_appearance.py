"""Optional offline browser acceptance for backgrounds, labels and opacity.

Uses the real local site and mocked image responses; never contacts map providers.
"""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import expect, sync_playwright


def check(url, output):
    if urlsplit(url).hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('Use a loopback website URL.')
    output.mkdir(parents=True, exist_ok=True)
    png = (Path(__file__).resolve().parents[1] / 'totally_normal_maps/vendor/leaflet/images/layers.png').read_bytes()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors, tiles = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(request):
            host = urlsplit(request.request.url).hostname
            if host in {'localhost', '127.0.0.1'}:
                if request.request.url.endswith('/favicon.ico'): request.fulfill(status=204)
                else: request.continue_()
            elif host in {'maps.geogratis.gc.ca', 'geoappext.nrcan.gc.ca'}:
                tiles.append(request.request.url)
                request.fulfill(content_type='image/png', body=png)
            else: raise AssertionError('Unexpected external request: ' + host)
        page.route('**/*', route)
        page.goto(url, wait_until='networkidle')
        expect(page.locator('#background-status')).to_contain_text('Online background')
        assert any('toporama_en' in t for t in tiles)
        page.locator('#relief').check()
        expect(page.locator('#background-status')).to_contain_text('shaded relief')
        assert any('WMSServer' in t and 'layers=4' in t for t in tiles)
        page.locator('#background').select_option('none')
        expect(page.locator('#relief')).to_be_disabled()
        expect(page.locator('#background-status')).to_contain_text('Offline view')
        assert page.locator('.leaflet-tile-pane img').count() == 0
        page.locator('#province').select_option('24')
        expect(page.locator('#map-status')).to_contain_text('17 regions')
        page.wait_for_function('() => regionNames.getLayers().length > 0')
        # Each label must stay in its polygon, be unclipped and avoid other labels.
        def labels_fit():
            return page.evaluate('''() => {
              const labels = [...document.querySelectorAll('.region-name-text[data-region-id]')];
              const bounds = document.getElementById('map').getBoundingClientRect();
              const boxes = labels.map(n => n.getBoundingClientRect());
              return labels.length > 0 && labels.every((n, i) => {
                const b = boxes[i], feature = drawn.getLayers().find(l => l.feature.properties.id === n.dataset.regionId).feature;
                const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.coordinates;
                const inside = [b.left, (b.left+b.right)/2, b.right].every(x => [b.top, (b.top+b.bottom)/2, b.bottom].every(y => {
                  const ll = map.containerPointToLatLng([x-bounds.left, y-bounds.top]);
                  return polygons.some(poly => polygonContains(poly, [ll.lng, ll.lat]));
                }));
                return inside && b.left >= bounds.left && b.right <= bounds.right && b.top >= bounds.top && b.bottom <= bounds.bottom &&
                  boxes.every((other,j) => i===j || b.right <= other.left || b.left >= other.right || b.bottom <= other.top || b.top >= other.bottom);
              });
            }''')
        assert labels_fit()
        page.screenshot(path=str(output/'labels-desktop.png'), full_page=True)
        page.locator('#region-labels').uncheck()
        expect(page.locator('.region-name-text[data-region-id]')).to_have_count(0)
        page.locator('#region-labels').check()
        assert labels_fit()
        page.evaluate('map.fitBounds([[44.8,-80],[50.2,-67]], {padding: [25,25], animate: false})')
        expect(page.locator('.region-name-text[data-region-id="ca-qc-ra-07"]')).to_be_visible()
        assert labels_fit()
        assert page.locator('.region-name-text[data-region-id]').count() >= 5
        page.screenshot(path=str(output/'labels-zoomed.png'), full_page=True)
        label = page.locator('.region-name-text[data-region-id="ca-qc-ra-07"]').bounding_box()
        page.mouse.click(label['x'] + label['width']/2, label['y'] + label['height']/2)
        expect(page.locator('#breadcrumbs [aria-current]')).to_have_text('Outaouais')
        page.locator('#province').select_option('24')
        expect(page.locator('#map-status')).to_contain_text('17 regions')
        page.locator('#boundary-opacity').fill('0')
        expect(page.locator('#opacity-value')).to_have_text('0%')
        assert page.evaluate('drawn.getLayers().every(l => l.options.fillOpacity === 0)')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_function('() => map.getSize().x < 500')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.evaluate('map.fitBounds(drawn.getBounds(), {padding: [25,25], animate: false})')
        if page.locator('.region-name-text[data-region-id]').count(): assert labels_fit()
        page.screenshot(path=str(output/'labels-mobile.png'), full_page=True)
        page.locator('#results [data-area-id="ca-qc-ra-09"]').click()
        expect(page.locator('#map-status')).to_contain_text('54 municipalities')
        expect(page.locator('.region-name-text[data-region-id]')).to_have_count(0)
        page.locator('#results [data-area-id="2498015"]').click()
        expect(page.locator('#selection')).to_contain_text('Reviewed topology repair')
        assert page.evaluate('drawn.getLayers().every(l => l.options.fillOpacity === 0)')
        # A failed provider remains non-blocking and is clearly explained.
        page.route('https://maps.geogratis.gc.ca/**', lambda r: r.abort())
        page.locator('#background').select_option('topographic')
        expect(page.locator('#background-status')).to_contain_text('tiles are unavailable')
        expect(page.locator('#map path[data-area-id]')).to_have_count(54)
        page.locator('#background').select_option('none')
        expect(page.locator('#background-status')).to_contain_text('Offline view')
        tile_count = len(tiles)
        page.goto(urlunsplit(urlsplit(url)._replace(query='background=none')), wait_until='networkidle')
        expect(page.locator('#background-status')).to_contain_text('Offline view')
        assert len(tiles) == tile_count
        assert not errors, errors
        browser.close()
    print('Passed: background, relief, offline mode, provider failure, opacity, region labels, desktop/mobile, repaired boundary details.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9010')
    parser.add_argument('--output', type=Path, default=Path('.local/appearance-check'))
    args = parser.parse_args()
    check(args.url, args.output)
