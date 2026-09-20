"""Real local electoral browser acceptance; all external requests are blocked."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def check(url, output):
    if urlsplit(url).hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('Use a loopback map URL.')
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1050})
        page.set_default_timeout(45000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request):
            if urlsplit(request.request.url).hostname in {'localhost','127.0.0.1'}: request.continue_()
            else: request.abort()
        page.route('**/*', route)
        page.goto(url.rstrip('/')+'/?background=none', wait_until='networkidle')
        expect(page.locator('#map-status')).to_contain_text('13 provinces')
        page.locator('#map-layer').select_option('federal')
        expect(page.locator('#map-status')).to_contain_text('343 electoral districts')
        assert page.evaluate('drawn.getLayers().every(l => byId.get(l.feature.properties.id).layer === "federal")')
        page.locator('#search').fill('Cape Spear')
        expect(page.locator('#results .result')).to_have_count(1)
        page.locator('#results .result').click()
        expect(page.locator('#selection h2')).to_contain_text('Cape Spear')
        expect(page.locator('#province')).to_have_value('10')
        expect(page.locator('#map-status')).to_contain_text('7 electoral districts')
        # A sibling stays selectable after a leaf receives focus.
        page.locator('#results [data-area-id="ca-fed-2023-10001"]').click()
        expect(page.locator('#selection h2')).to_have_text('Avalon')
        page.locator('#search').fill('ca-fed-2023-10001')
        expect(page.locator('#results .result')).to_have_count(1)
        expect(page.locator('#results .result')).to_have_attribute('data-area-id', 'ca-fed-2023-10001')
        page.locator('#search').fill('')
        expect(page.locator('#results .result')).to_have_count(7)
        page.locator('#province').select_option('24')
        expect(page.locator('#map-status')).to_contain_text('78 electoral districts')
        # Optional comparison failures must not take down the active layer.
        page.route('**/regions-24.geojson', lambda route: route.fulfill(status=503, body='unavailable'))
        page.locator('#comparison-layer').select_option('administrative')
        expect(page.locator('#retry-boundaries')).to_be_visible()
        expect(page.locator('#map-status')).to_contain_text('78 electoral districts')
        assert page.evaluate('drawn.getLayers().length === 78')
        page.unroute('**/regions-24.geojson')
        page.locator('#retry-boundaries').click()
        page.wait_for_function('() => comparisonOutlines.getLayers().length === 17')
        expect(page.locator('#retry-boundaries')).to_be_hidden()
        page.locator('#comparison-layer').select_option('provincial')
        page.wait_for_function('() => comparisonOutlines.getLayers().length === 127')
        page.screenshot(path=str(output/'quebec-federal-comparison.png'), full_page=True)
        page.locator('#map-layer').select_option('provincial')
        expect(page.locator('#map-status')).to_contain_text('127 electoral districts')
        page.locator('#edition').select_option('qc-2017')
        expect(page.locator('#map-status')).to_contain_text('125 electoral districts')
        expect(page.locator('#coverage-note')).to_contain_text('historical')
        assert page.evaluate('drawn.getLayers().every(l => byId.get(l.feature.properties.id).edition === "qc-2017")')
        # Province changes clear an incompatible selected historical edition.
        page.locator('#map path[data-context-area-id="35"]').press('Enter')
        expect(page.locator('#province')).to_have_value('35')
        expect(page.locator('#edition')).to_have_value('')
        expect(page.locator('#map-status')).to_contain_text('124 electoral districts')
        page.locator('#province').select_option('')
        expect(page.locator('#map-status')).to_contain_text('783 electoral districts')
        # Every province/territory has its own current branch.
        counts = page.evaluate('data.report.electoral.coverage.provincial')
        for province, spec in counts.items():
            page.locator('#province').select_option(province)
            expect(page.locator('#map-status')).to_contain_text(f"{spec['expected_count']} electoral districts")
        page.locator('#province').select_option('24')
        page.locator('#comparison-layer').select_option('administrative')
        page.wait_for_function('() => comparisonOutlines.getLayers().length === 17')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(output/'electoral-mobile.png'), full_page=True)
        page.locator('#map-layer').select_option('administrative')
        expect(page.locator('#map-status')).to_contain_text('17 regions')
        page.locator('#results [data-area-id="ca-qc-ra-07"]').click()
        expect(page.locator('#breadcrumbs [aria-current]')).to_have_text('Outaouais')
        assert not errors, errors
        browser.close()
    print('Electoral map passed: national/provincial layers, 13 jurisdictions, history, comparisons, sibling focus, mobile, administrative return.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:9010')
    parser.add_argument('--output', type=Path, default=Path('.local/electoral-browser'))
    args = parser.parse_args()
    check(args.url, args.output)
