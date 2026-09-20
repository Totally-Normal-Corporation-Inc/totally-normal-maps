"""Explicit offline browser checks for municipality focus, wards and coverage."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect,sync_playwright

def check(url,output):
    assert urlsplit(url).hostname in {'localhost','127.0.0.1'}
    output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050});page.set_default_timeout(90000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in {'localhost','127.0.0.1'} else route.abort())
        page.goto(url.rstrip('/')+'/?background=none',wait_until='networkidle')
        expect(page.locator('#map-status')).to_contain_text('13 provinces')
        page.locator('#map-layer').select_option('municipal')
        expect(page.locator('#municipal-control')).to_be_visible()
        page.wait_for_function('() => drawn.getLayers().length > 2000 && !document.getElementById("map-status").textContent.includes("Loading")')
        assert page.evaluate('drawn.getLayers().every(l => byId.get(l.feature.properties.id).layer === "municipal")')
        page.locator('#province').select_option('24')
        page.locator('#municipal-authority').select_option('2466023')
        expect(page.locator('#map-status')).to_contain_text('58 electoral districts')
        expect(page.locator('#coverage-note')).to_contain_text('Montréal')
        assert page.evaluate('drawn.getLayers().every(l => byId.get(l.feature.properties.id).authority_id === "2466023")')
        page.locator('#results .result').first.click()
        expect(page.locator('#selection')).to_contain_text('2025 municipal election')
        page.wait_for_function('() => regionNames.getLayers().length > 0')
        assert page.locator('#results .result').count()==58
        page.locator('#results .result').nth(1).click()
        assert page.evaluate('currentRows().length === 58')
        # A neighbouring municipality changes focus without returning to a parent.
        page.evaluate('() => { const l = surroundingAreas.getLayers().find(l => l.feature.properties.id === "2465005"); if (!l) throw new Error("Laval is not clickable context"); l.fire("click"); }')
        expect(page.locator('#municipal-authority')).to_have_value('2465005')
        expect(page.locator('#map-status')).to_contain_text('22 electoral districts')
        expect(page.locator('#coverage-note')).to_contain_text('Reference')
        page.locator('#results .result').first.click()
        expect(page.locator('#selection')).to_contain_text('applicability to the current election is unverified')
        page.locator('#comparison-layer').select_option('federal')
        page.wait_for_function('() => comparisonOutlines.getLayers().length > 0')
        page.screenshot(path=str(output/'laval-wards-federal-comparison.png'),full_page=True)
        page.locator('#comparison-layer').select_option('')
        page.locator('#province').select_option('59')
        page.locator('#municipal-authority').select_option('5915022')
        expect(page.locator('#coverage-note')).to_contain_text('Elected at large')
        expect(page.locator('#map-status')).to_contain_text('0 areas')
        assert page.evaluate('contextOutline.getLayers().length > 0')
        page.locator('#municipal-authority').select_option('5935016')
        expect(page.locator('#map-status')).to_contain_text('4 electoral districts')
        page.screenshot(path=str(output/'lake-country-wards.png'),full_page=True)
        page.locator('#province').select_option('60')
        page.locator('#municipal-authority').select_option('6001009')
        expect(page.locator('#coverage-note')).to_contain_text('Elected at large')
        page.locator('#municipal-authority').select_option('6001003')
        expect(page.locator('#coverage-note')).to_contain_text('Not yet verified')
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#province').select_option('24');page.locator('#municipal-authority').select_option('2466023')
        expect(page.locator('#map-status')).to_contain_text('58 electoral districts')
        page.screenshot(path=str(output/'municipal-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert not errors,errors
        browser.close()
    print('Municipal browser checks passed: dated wards, sibling focus, neighbouring municipalities, at-large/unknown coverage, comparison, labels and mobile.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args();check(args.url,args.output)
