"""Optional browser acceptance against the real pinned Canada regional run.

Run separately from unit tests with Playwright and system Chromium installed.
The only requests are to the supplied loopback preview; no application writes.
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def check_preview(url, output):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Use the local loopback preview URL.")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" and "favicon" not in msg.text else None)
        # Avoid Chromium's unrelated automatic favicon request.
        page.route("**/favicon.ico", lambda route: route.fulfill(status=204))
        page.goto(url, wait_until="networkidle")
        city_areas = page.request.get(url.rstrip("/") + "/catalogue.json").json().get("city_areas", [])

        def status(text):
            expect(page.locator("#map-status")).to_have_text(text + " · Simplified boundaries")

        def rows(count):
            expect(page.locator("#results .result")).to_have_count(count)

        def current(text):
            expect(page.locator('#breadcrumbs [aria-current="location"]')).to_have_text(text)

        def click_map(lat, lon):
            point = page.evaluate("([lat, lon]) => { const p = map.latLngToContainerPoint([lat, lon]); return {x:p.x, y:p.y}; }", [lat, lon])
            bounds = page.locator("#map").bounding_box()
            page.mouse.click(bounds["x"] + point["x"], bounds["y"] + point["y"])

        status("13 provinces / territories")
        rows(13)
        current("Canada")
        expect(page.locator('#map path[data-area-id]')).to_have_count(13)
        expect(page.locator("#back")).to_be_hidden()
        page.screenshot(path=str(output / "levels-canada.png"), full_page=True)
        click_map(54, -72)
        status("17 regions")
        rows(17)
        current("Quebec")
        page.screenshot(path=str(output / "levels-quebec.png"), full_page=True)
        click_map(46.61, -76.77)
        status("75 municipalities")
        rows(75)
        current("Outaouais")
        page.screenshot(path=str(output / "levels-outaouais.png"), full_page=True)
        page.locator('#results [data-area-id="2481017"]').click()
        expect(page.locator("#selection h2")).to_have_text("Gatineau")
        expect(page.locator("#selection")).to_contain_text("Region: Outaouais")
        if city_areas:
            status("5 secteurs")
            current("Gatineau")
            rows(5)
            expect(page.locator('#map path[data-area-id]')).to_have_count(5)
            click_map(45.44, -75.73)
            expect(page.locator("#selection h2")).to_have_text("Hull")
            expect(page.locator("#selection")).to_contain_text("Secteur · City: Gatineau")
            page.locator('#results [data-area-id="ca-qc-2481017-sector-15"]').click()
            expect(page.locator("#selection")).to_contain_text("Secteur · City: Gatineau · Source ID: 15")
            expect(page.locator('#results [data-area-id="ca-qc-2481017-sector-15"]')).to_have_attribute("aria-pressed", "true")
            page.locator("#search").fill("aylmer")
            status("1 secteur")
            page.locator("#breadcrumbs").get_by_role("button", name="Outaouais", exact=True).click()
            status("75 municipalities")
            page.locator('#map path[data-area-id="2481017"]').press("Enter")
            status("5 secteurs")
            page.locator('#map path[data-area-id="ca-qc-2481017-sector-20"]').press("Space")
            expect(page.locator("#selection h2")).to_have_text("Hull")
            page.screenshot(path=str(output / "city-areas-hull.png"), full_page=True)
            page.locator("#back").click()
            status("75 municipalities")
        else:
            expect(page.locator('#results [data-area-id="2481017"]')).to_have_attribute("aria-pressed", "true")
        page.screenshot(path=str(output / "levels-gatineau.png"), full_page=True)
        page.locator("#back").click()
        status("17 regions")
        if city_areas:
            for uid, label, count in [("2466023", "19 arrondissements", 19), ("2423027", "6 arrondissements", 6),
                ("2425213", "3 arrondissements", 3), ("2443027", "4 arrondissements", 4),
                ("2494068", "3 arrondissements", 3), ("2458227", "3 arrondissements", 3),
                ("2476052", "2 arrondissements", 2), ("2409048", "1 arrondissement", 1)]:
                area = next(r for r in city_areas if r["parent_csd_id"] == uid)
                page.locator("#province").select_option("24")
                status("17 regions")
                page.locator(f'#results [data-area-id="{area["region_id"]}"]').click()
                page.locator("#search").fill(uid)
                expect(page.locator("#results .result")).to_have_count(1)
                page.locator(f'#results [data-area-id="{uid}"]').click()
                status(label); rows(count); current(area["parent_name"])
                expect(page.locator('#map path[data-area-id]')).to_have_count(count)
                if uid == "2466023":
                    page.screenshot(path=str(output / "city-areas-montreal.png"), full_page=True)
                    page.locator("#search").fill("cote-des-neiges")
                    status("1 arrondissement")
                    page.locator('#results [data-area-id="ca-qc-arr-rem34"]').click()
                    expect(page.locator("#selection")).to_contain_text("Arrondissement · City: Montréal")
                if uid == "2409048":
                    expect(page.locator("#selection")).to_contain_text("Partial city coverage")
                    expect(page.locator("#selection")).to_contain_text("8.9%")
                    page.screenshot(path=str(output / "city-areas-metis.png"), full_page=True)
            # Searching a sector finds its parents at each higher level.
            page.locator("#province").select_option("")
            status("13 provinces / territories")
            page.locator("#search").fill("Hull")
            expect(page.locator('#results [data-area-id="24"]')).to_have_count(1)
            page.locator('#results [data-area-id="24"]').click()
            page.locator("#search").fill("Hull")
            expect(page.locator('#results [data-area-id="ca-qc-ra-07"]')).to_have_count(1)
            page.locator('#results [data-area-id="ca-qc-ra-07"]').click()
            page.locator("#search").fill("Hull")
            status("1 municipality")
            page.locator('#results [data-area-id="2481017"]').click()
            status("5 secteurs")
            # A city without imported areas remains inspectable.
            page.locator("#province").select_option("24")
            status("17 regions")
            page.locator('#results [data-area-id="ca-qc-ra-13"]').click()
            page.locator('#results [data-area-id="2465005"]').click()
            expect(page.locator("#selection h2")).to_have_text("Laval")
            expect(page.locator("#selection")).to_contain_text("City areas have not been added here yet")
            current("Laval")  # Region stays current; municipality is selected, not another level.
            page.locator("#province").select_option("24")
            status("17 regions")
        page.locator("#back").click()
        status("13 provinces / territories")
        # Map polygons are also keyboard-operable after returning to cached layers.
        page.locator('#map path[data-area-id="24"]').press("Enter")
        status("17 regions")
        page.locator('#map path[data-area-id="ca-qc-ra-07"]').press("Space")
        status("75 municipalities")
        page.locator("#search").fill("Gatineau")
        status("2 municipalities")  # Gatineau and Lac-Gatineau.
        expect(page.locator('#results [data-area-id="2481017"]')).to_have_count(1)
        page.locator("#breadcrumbs").get_by_role("button", name="Quebec", exact=True).click()
        status("17 regions")
        expect(page.locator("#search")).to_have_value("")
        page.locator("#search").fill("no-such-area-xyz")
        status("0 areas")
        page.get_by_role("button", name="Clear filters", exact=True).click()
        status("17 regions")
        for code, label, count in [
            ("11", "3 regions", 3), ("12", "18 regions", 18), ("13", "12 regions", 12),
            ("24", "17 regions", 17), ("35", "40 regions · 17 municipalities", 57),
            ("59", "28 regions · 5 municipalities", 33), ("62", "3 regions", 3),
            ("10", "372 municipalities", 100), ("46", "241 municipalities", 100),
            ("47", "995 municipalities", 100), ("48", "419 municipalities", 100),
            ("60", "33 municipalities", 33), ("61", "41 municipalities", 41),
        ]:
            page.locator("#province").select_option(code)
            status(label)
            rows(count)
        page.locator("#province").select_option("35")
        status("40 regions · 17 municipalities")
        page.locator('#results [data-area-id="3506008"]').click()
        expect(page.locator("#selection h2")).to_have_text("Ottawa")
        expect(page.locator("#selection")).to_contain_text("No regional grouping")
        page.locator('#results [data-area-id="3520005"]').click()
        expect(page.locator("#selection h2")).to_have_text("Toronto")
        page.locator("#issues-only").check()
        expect(page.locator("#map-status")).to_have_text(re.compile(r"^7 regions"))
        page.locator("#province").select_option("48")
        status("419 municipalities")
        expect(page.locator("#issues-only")).not_to_be_checked()
        page.locator("#more").click()
        rows(200)
        page.locator("#breadcrumbs").get_by_role("button", name="Canada", exact=True).click()
        status("13 provinces / territories")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        page.locator('#results [data-area-id="24"]').click()
        status("17 regions")
        page.locator('#results [data-area-id="ca-qc-ra-07"]').click()
        status("75 municipalities")
        current("Outaouais")
        expect(page.locator("#province")).to_be_in_viewport()
        assert page.locator("aside").evaluate("node => node.scrollTop") == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "levels-mobile.png"), full_page=True)
        if city_areas:
            page.locator('#results [data-area-id="2481017"]').click()
            status("5 secteurs"); current("Gatineau")
            assert page.locator("aside").evaluate("node => node.scrollTop") == 0
            expect(page.locator("#province")).to_be_in_viewport()
            page.locator('#results [data-area-id="ca-qc-2481017-sector-20"]').click()
            expect(page.locator("#selection h2")).to_have_text("Hull")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / "city-areas-mobile.png"), full_page=True)
            page.locator("#back").click()
            status("75 municipalities")
        page.locator("#back").click()
        status("17 regions")
        assert not errors, errors
        browser.close()
        print(json.dumps({"status": "passed", "city_areas_checked": len(city_areas), "checks": ["13 province outlines", "map click drilldown", "keyboard map navigation", "Outaouais 75 municipalities", "Gatineau identity", "breadcrumbs and back", "search reset and empty results", "all 13 jurisdiction child counts", "Ontario direct municipalities", "repair filter", "pagination", "mobile navigation and width"], "page_errors": errors}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9010")
    parser.add_argument("--output", type=Path, default=Path(".local/canada"))
    args = parser.parse_args()
    check_preview(args.url, args.output)
