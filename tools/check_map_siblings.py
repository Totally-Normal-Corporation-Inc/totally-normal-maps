"""Offline browser acceptance of surrounding-area navigation on the local Canada site."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import expect, sync_playwright
from shapely.geometry import shape


def check(url, output):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('Use a loopback website URL.')
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url))
        page.route('**/favicon.ico', lambda route: route.fulfill(status=204))
        page.goto(urlunsplit(parsed._replace(query='background=none')), wait_until='networkidle')

        def current(name):
            expect(page.locator('#breadcrumbs [aria-current]')).to_have_text(name)
            expect(page.locator('#map-status')).not_to_have_text('Loading boundaries…')

        def context(uid):
            return page.locator(f'#map path[data-context-area-id="{uid}"]')

        def click_area(uid, surrounding=False):
            # Find an interior point independently using Shapely, then perform a
            # real mouse click and verify which SVG path is on top at that point.
            geom = page.evaluate('''([uid, surrounding]) => {
              const group = surrounding ? surroundingAreas : drawn;
              return group.getLayers().find(l => l.feature.properties.id === uid).feature.geometry;
            }''', [uid, surrounding])
            point = shape(geom).representative_point()
            page.evaluate('([lat,lon]) => { map.panTo([lat,lon], {animate:false}); }', [point.y, point.x])
            page.locator('#map').scroll_into_view_if_needed()
            pixel = page.evaluate('''([lat,lon]) => {
              const p = map.latLngToContainerPoint([lat,lon]), b = document.getElementById('map').getBoundingClientRect();
              return {x:b.left+p.x, y:b.top+p.y};
            }''', [point.y, point.x])
            key = 'contextAreaId' if surrounding else 'areaId'
            assert page.evaluate('([p,key]) => document.elementFromPoint(p.x,p.y)?.dataset[key]', [pixel,key]) == uid
            page.mouse.click(pixel['x'], pixel['y'])

        page.locator('#province').select_option('24'); current('Quebec')
        expect(context('35')).to_have_count(1)
        expect(context('24')).to_have_count(0)
        expect(page.locator('#results .result')).to_have_count(17)
        click_area('35', True); current('Ontario')
        expect(page.locator('#province')).to_have_value('35')
        expect(page.locator('#results .result')).to_have_count(57)
        expect(context('24')).to_have_count(1)
        click_area('24', True); current('Quebec')
        # Foreground regions still receive clicks above all surrounding outlines.
        click_area('ca-qc-ra-07'); current('Outaouais')
        expect(page.locator('#results .result')).to_have_count(75)
        click_area('ca-qc-ra-15', True); current('Laurentides')
        context('ca-qc-ra-07').press('Enter'); current('Outaouais')
        page.locator('#results [data-area-id="2481017"]').click(); current('Gatineau')
        expect(page.locator('#results .result')).to_have_count(5)
        expect(context('2481017')).to_have_count(0)
        page.screenshot(path=str(output/'gatineau-surroundings.png'), full_page=True)
        # Chelsea has no added city-area layer: switching must restore the
        # municipality list and breadcrumbs instead of retaining Gatineau's sectors.
        click_area('2482025', True)
        current('Outaouais')
        expect(page.locator('#selection h2')).to_have_text('Chelsea')
        expect(page.locator('#results .result')).to_have_count(75)
        expect(page.locator('#results [data-area-id="2482025"]')).to_have_attribute('aria-pressed','true')
        click_area('2481017'); current('Gatineau')
        click_area('ca-qc-2481017-sector-20')
        expect(page.locator('#selection h2')).to_have_text('Hull')
        click_area('ca-qc-2481017-sector-25')
        expect(page.locator('#selection h2')).to_have_text('Aylmer')
        # Nested city areas retain their sibling parents too.
        page.locator('#province').select_option('24'); current('Quebec')
        page.locator('#results [data-area-id="ca-qc-ra-03"]').click(); current('Capitale-Nationale')
        page.locator('#search').fill('2423027')
        page.locator('#results [data-area-id="2423027"]').click(); current('Québec')
        page.locator('#results [data-area-id="ca-qc-arr-req01"]').click()
        expect(context('ca-qc-arr-req02')).to_have_count(1)
        click_area('ca-qc-arr-req02', True)
        expect(page.locator('#breadcrumbs [aria-current]')).to_have_text('Les Rivières')
        expect(page.locator('#results .result')).to_have_count(3)
        # Filters affect the active list only; parents are never reintroduced over
        # the active children and alternate city boundary schemes stay separate.
        page.locator('#province').select_option('35'); current('Ontario')
        page.locator('#results [data-area-id="3520005"]').click(); current('Toronto')
        page.locator('#city-scheme').select_option('neighbourhood')
        expect(page.locator('#map-status')).to_contain_text('158 neighbourhoods')
        assert page.evaluate("!surroundingAreas.getLayers().some(l => byId.get(l.feature.properties.id).level === 'city_area')")
        page.locator('#search').fill('no-such-area')
        expect(page.locator('#results .result')).to_have_count(0)
        expect(context('24')).to_have_count(1)
        page.set_viewport_size({'width':390, 'height':844})
        context('24').press('Space'); current('Quebec')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.locator('#search')).to_have_value('')
        # Late requests from the former scope cannot overwrite the final scope.
        page.evaluate("navigate('35'); navigate('24'); navigate('10')")
        current('Newfoundland and Labrador')
        expect(page.locator('#province')).to_have_value('10')
        expect(context('24')).to_have_count(1)
        assert all(urlsplit(r).hostname in {'localhost','127.0.0.1'} for r in requests)
        assert not errors, errors
        browser.close()
    print('Passed: province, region, municipality and nested-area siblings; foreground hit testing; leaf context; keyboard/mobile; filters, schemes and rapid navigation; no external requests.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9010')
    parser.add_argument('--output', type=Path, default=Path('.local/sibling-check'))
    args = parser.parse_args()
    check(args.url, args.output)
