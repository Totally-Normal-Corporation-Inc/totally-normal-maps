/* Local display only. External names are always assigned as text, never HTML. */
"use strict";
const el = id => document.getElementById(id);
const normal = text => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const map = L.map("map", {crs: L.CRS.EPSG4326, minZoom: 1, zoomSnap: 0});
const contextOutline = L.featureGroup().addTo(map);
const drawn = L.featureGroup().addTo(map);
const viewCanada = () => map.fitBounds([[41, -142], [84, -50]], {padding: [10, 10], animate: false});
viewCanada();
map.attributionControl.setPrefix(false);
map.attributionControl.addAttribution("Simplified display boundaries");
const colours = ["#426f59", "#8b773e", "#5a7795", "#98645b", "#367c6a", "#759458", "#8c7698"];
let data, selected = null, shown = 100, generation = 0, searchTimer;
let locationState = {province: "", region: "", city: "", area: ""};
const layers = new Map(), loading = new Map(), byId = new Map();
const cityChildren = new Map(), cityCoverage = new Map();
const hasChildren = row => cityChildren.has(row.id);
const areaCounts = rows => [...new Set(rows.map(r => r.type))].map(type => countText(rows.filter(r => r.type === type).length, type.toLowerCase())).join(" · ");

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load ${url} (${response.status})`);
  return response.json();
}
function line(text, className) {
  const p = document.createElement("p");
  p.textContent = text;
  if (className) p.className = className;
  return p;
}
function button(text, action) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = text;
  node.addEventListener("click", action);
  return node;
}
function countText(count, singular, plural = `${singular}s`) {
  if (plural === `${singular}s` && singular.endsWith("y")) plural = singular.slice(0, -1) + "ies";
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}
function describeRows(rows, boundaries = false) {
  const counts = {province: 0, region: 0, municipality: 0, city_area: 0};
  rows.forEach(row => counts[row.level]++);
  const parts = [];
  if (counts.province) parts.push(countText(counts.province, "province / territory", "provinces / territories"));
  if (counts.region) parts.push(countText(counts.region, "region"));
  if (counts.municipality) parts.push(countText(counts.municipality, "municipality", "municipalities"));
  if (counts.city_area) parts.push(areaCounts(rows.filter(row => row.level === "city_area")));
  return (parts.join(" · ") || "0 areas") + (boundaries ? " · Simplified boundaries" : "");
}
function currentRows() {
  const {province, region, city, area} = locationState;
  if (area) return cityChildren.get(area) || [];
  if (city) return (cityChildren.get(city) || []).filter(r => !el("city-scheme").value || (r.scheme || "default") === el("city-scheme").value);
  if (!province) return data.provinces;
  if (region) return data.areas.filter(row => row.region_id === region);
  // Ungrouped municipalities stay directly reachable, without inventing a region.
  return [...data.regions.filter(row => row.province === province),
    ...data.areas.filter(row => row.province === province && !row.region_id)];
}
function matchingRows() {
  const query = normal(el("search").value.trim());
  return currentRows().filter(row => (!el("issues-only").checked || row.issues.length) &&
    (!query || row.searchText.includes(query)));
}
function style(feature) {
  const row = byId.get(feature.properties.id), active = row.id === selected;
  const repair = row.assignment_status?.startsWith("unreviewed_");
  const colour = colours[Array.from(row.id).reduce((sum, c) => sum + c.charCodeAt(0), 0) % colours.length];
  return {weight: active ? 3 : row.level === "province" ? 1.6 : 1,
    color: active ? "#173b2c" : repair ? "#ad6328" : "#658176",
    fillColor: colour, dashArray: repair ? "4 3" : null, fillOpacity: active ? .6 : .3};
}
function fitRow(row) {
  if (!row?.bbox) return;
  map.invalidateSize({pan: false});
  const [west, south, east, north] = row.bbox;
  map.fitBounds([[south, west], [north, east]], {padding: [25, 25], maxZoom: 12, animate: false});
}
function showDetails(row) {
  const heading = document.createElement("h2");
  heading.textContent = row?.name || "Explore Canada";
  el("selection").replaceChildren(heading);
  if (!row) {
    el("selection").append(line("Choose a province or territory on the map or in the list to open the next level."));
    return;
  }
  if (row.level === "province") {
    const regions = data.regions.filter(r => r.province === row.id);
    el("selection").append(line(`${row.code} · ${countText(row.count, "municipal-level area")}`),
      line(regions.length ? "Choose a region to open its municipalities. Municipalities without a region can be selected directly." :
        "No regional layer selected here. Choose a municipality to inspect it."));
  } else if (row.level === "region") {
    el("selection").append(line(`${row.code} · ${row.type} · ${countText(row.member_count, "municipal-level area")}`),
      line("Choose a municipality on the map or in the list to inspect it."));
    if (row.coverage_note) el("selection").append(line(row.coverage_note));
  } else if (row.level === "city_area") {
    el("selection").append(line(`${row.type} · City: ${row.parent_name}`));
    const source = data.report.city_areas.sources[row.source];
    if (source) el("selection").append(line(`${source.authority} · ${source.release} · Source ID: ${row.source_id}`));
    if (row.geometry_status === "unavailable") el("selection").append(line("Boundary unavailable. This sector's identity is documented, but a reusable boundary source is still needed.", "issue"));
    else el("selection").append(line(`${(row.vertices || 0).toLocaleString()} full-boundary vertices · Draft geography; source differences require review`));
    if (hasChildren(row)) el("selection").append(line(`${areaCounts(cityChildren.get(row.id))} · Select a boundary or name to inspect it.`));
  } else {
    el("selection").append(line(`${row.code} · ${row.boundary_basis === "predecessor_csd_union" ? "Municipality" : "Official CSD"} ${row.source_id || row.id} · Type ${row.type}`));
    if (row.coverage_note) el("selection").append(line(row.coverage_note));
    const region = byId.get(row.region_id);
    el("selection").append(line(region ? `Region: ${region.name} · ${region.type}` : "No regional grouping added for this municipality yet."));
    el("selection").append(line(`${(row.vertices || 0).toLocaleString()} full-boundary vertices · Draft geography; source differences require review`));
    if (hasChildren(row)) {
      el("selection").append(line(`${areaCounts(cityChildren.get(row.id))} · Select a boundary or name to inspect it.`));
      for (const coverage of cityCoverage.get(row.id) || []) {
        el("selection").append(line(coverage.coverage_policy === "unavailable" ?
          "Sector names are available; their boundaries still need a qualified source." :
          `${coverage.coverage_policy === "partial" ? "Partial city coverage: " : ""}${coverage.expected_count} source areas cover ${(coverage.covered_parent_fraction * 100).toFixed(1)}% of the national city outline. Boundaries from different sources may not align exactly.`));
      }
    } else el("selection").append(line("City areas have not been added here yet."));
  }
  if (row.issues.length) el("selection").append(line(row.issues.join("; "), "issue"));
  if (row.assignment_status?.startsWith("unreviewed_") && row.assignment_status !== "unreviewed_repair") {
    el("selection").append(line("Boundary shown for review only; unavailable for point assignment.", "issue"));
  }
  if (row.repair && Number.isFinite(row.repair.area_change_m2)) {
    el("selection").append(line(`Unreviewed repair · Area change ${row.repair.area_change_m2.toFixed(3)} m² · Parts ${row.repair.source_parts} → ${row.repair.candidate_parts} · Holes ${row.repair.source_holes} → ${row.repair.candidate_holes}`, "issue"));
  }
}
function openRow(id) {
  const row = byId.get(id);
  if (!row) return;
  if (row.level === "province") navigate(row.id);
  else if (row.level === "region") navigate(row.province, row.id);
  else if (hasChildren(row)) navigate(row.province, row.region_id || "", row.level === "city_area" ? row.parent_csd_id : row.id, row.level === "city_area" ? row.id : "");
  else {
    selected = id;
    showDetails(row);
    drawn.eachLayer(layer => layer.setStyle(style(layer.feature)));
    fitRow(row);
    renderResults();
  }
}
function renderResults() {
  const rows = matchingRows();
  el("result-count").textContent = describeRows(rows) + (rows.length > shown ? ` · showing ${shown}` : "");
  el("results").replaceChildren();
  for (const row of rows.slice(0, shown)) {
    const item = button("", () => openRow(row.id));
    item.className = "result";
    item.dataset.areaId = row.id;
    if ((row.level === "city_area" || row.level === "municipality") && !hasChildren(row)) item.setAttribute("aria-pressed", String(row.id === selected));
    const title = document.createElement("span"), name = document.createElement("strong"), note = document.createElement("small"), code = document.createElement("span");
    name.textContent = row.name;
    note.textContent = (row.level === "province" ? `${countText(row.count, "municipal-level area")} · Open →` :
      row.level === "region" ? `${row.member_count} areas · ${row.type}${row.coverage_policy === "selected_members" ? " · Partial coverage" : ""} · Open →` :
      row.level === "city_area" ? `${row.type}${hasChildren(row) ? ` · ${areaCounts(cityChildren.get(row.id))} · Open →` : row.geometry_status === "unavailable" ? " · Boundary unavailable" : ` · ${row.source_id}`}` :
      hasChildren(row) ? `${areaCounts(cityChildren.get(row.id))} · Open →` :
        `${row.id} · ${row.type}${!row.region_id ? " · No regional grouping" : ""}`) + (row.issues.length ? " · Review needed" : "");
    code.className = "code"; code.textContent = row.code;
    title.append(name, note); item.append(title, code);
    el("results").append(item);
  }
  if (!rows.length) {
    el("results").append(line("No areas match these filters."), button("Clear filters", () => {
      el("search").value = ""; el("issues-only").checked = false; refresh();
    }));
  }
  el("more").hidden = rows.length <= shown;
}
function renderNavigation() {
  const {province, region, city, area} = locationState;
  const regionLabel = region ? byId.get(region).name + (city && byId.get(city).name === byId.get(region).name ? " (region)" : "") : "";
  const trail = [{label: "Canada", action: () => navigate()}];
  if (province) trail.push({label: byId.get(province).name, action: () => navigate(province)});
  if (region) trail.push({label: regionLabel, action: () => navigate(province, region)});
  if (city) trail.push({label: byId.get(city).name, action: () => navigate(province, region, city)});
  if (area) trail.push({label: byId.get(area).name});
  el("breadcrumbs").replaceChildren();
  trail.forEach((part, index) => {
    if (index) {
      const separator = document.createElement("span");
      separator.textContent = "›"; separator.setAttribute("aria-hidden", "true");
      el("breadcrumbs").append(separator);
    }
    const node = index < trail.length - 1 ? button(part.label, part.action) : document.createElement("span");
    if (index === trail.length - 1) { node.textContent = part.label; node.setAttribute("aria-current", "location"); }
    el("breadcrumbs").append(node);
  });
  el("back").hidden = !province;
  el("back").textContent = area ? `Back to ${byId.get(city).name}` : city ? `Back to ${regionLabel || byId.get(province).name}` : region ? `Back to ${byId.get(province).name}` : "Back to Canada";
  el("search").placeholder = city ? "Find a city area or source ID" : !province ? "Find a province or territory" : region || !data.regions.some(r => r.province === province) ?
    "Find a municipality or source ID" : "Find a region or municipality";
}
function coverageNote() {
  const {province, region, city, area} = locationState;
  const entry = data.report.regions?.jurisdictions.find(j => j.province === province);
  el("coverage-note").textContent = city ? `${byId.get(area || city).name} · ${areaCounts(cityChildren.get(area || city))}. The outer line shows the parent boundary.` :
    !province ? "Choose one of Canada's 13 provinces and territories to begin." :
    region ? `${byId.get(region).name} · ${byId.get(region).coverage_policy === "selected_members" ? "Selected communities; outlines show their combined footprint, not the complete region." : "Municipalities within this region."}` :
      !entry || entry.status === "deferred" ? "No regional layer selected. Showing municipalities directly." :
        `${countText(entry.expected_region_count, "region")}${entry.unassigned_member_count ? ` · ${countText(entry.unassigned_member_count, "municipality", "municipalities")} shown directly without a regional grouping` : ""}. Click to explore.`;
}
async function boundaryLayer(key) {
  if (layers.has(key)) return layers.get(key);
  if (!loading.has(key)) {
    loading.set(key, getJSON(`${key}.geojson`).then(geojson => {
      const layer = L.geoJSON(geojson, {
        style, smoothFactor: .2,
        onEachFeature: (feature, child) => {
          const row = byId.get(feature.properties.id);
          const label = document.createElement("span");
          label.textContent = row.level === "province" ? row.code : `${row.name} · ${row.level === "city_area" ? row.type : row.code}`;
          child.bindTooltip(label, row.level === "province" ? {permanent: true, direction: "center", className: "province-label"} : {sticky: true});
          child.on("click", () => openRow(row.id));
          child.on("add", () => {
            if (row.label_point) child.getTooltip().setLatLng(row.label_point);
            else if (row.level === "province") child.getTooltip().setLatLng(child.getBounds().getCenter());
            const path = child.getElement();
            if (!path || path.dataset.areaId) return;
            path.dataset.areaId = row.id;
            path.setAttribute("role", "button");
            path.setAttribute("tabindex", "0");
            path.setAttribute("aria-label", `${(row.level === "city_area" || row.level === "municipality") && !hasChildren(row) ? "Inspect" : "Open"} ${row.name}`);
            path.addEventListener("keydown", event => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault(); event.stopPropagation(); openRow(row.id);
              }
            });
          });
        }
      });
      layers.set(key, layer);
      return layer;
    }).finally(() => loading.delete(key)));
  }
  return loading.get(key);
}
async function showMap(fit = false) {
  const current = ++generation;
  const {province, region, city, area} = locationState;
  const rows = matchingRows(), ids = new Set(rows.map(r => r.id));
  drawn.clearLayers(); contextOutline.clearLayers();
  el("map-status").textContent = "Loading boundaries…";
  try {
    const keys = city ? [province, `city-areas-${province}`] : !province ? ["provinces"] : region ? [province, `regions-${province}`] :
      ["provinces", ...(rows.some(r => r.level === "region") ? [`regions-${province}`] : []),
        ...(rows.some(r => r.level === "municipality") ? [province] : [])];
    const available = await Promise.all(keys.map(boundaryLayer));
    if (current !== generation) return;
    for (const layer of available) layer.eachLayer(child => {
      const id = child.feature.properties.id;
      if (id === (area || city || region || province)) {
        L.geoJSON(child.feature, {interactive: false, style: {color: "#60756b", weight: 2, fill: false}}).addTo(contextOutline);
      }
      if (ids.has(id)) { child.setStyle(style(child.feature)); drawn.addLayer(child); }
    });
    const visible = drawn.getLayers().map(layer => byId.get(layer.feature.properties.id));
    const missing = rows.length - visible.length;
    el("map-status").textContent = describeRows(visible, true) + (missing ? ` · ${missing} without an available outline` : "");
    if (fit) {
      map.invalidateSize({pan: false});
      if (province) fitRow(byId.get(area || city || region || province));
      else viewCanada();
    }
  } catch (error) {
    if (current === generation) el("map-status").textContent = `Boundary load failed: ${error.message}`;
    console.error(error);
  }
}
function refresh(fit = false) {
  clearTimeout(searchTimer);
  shown = 100; selected = null;
  showDetails(byId.get(locationState.area || locationState.city || locationState.region || locationState.province));
  renderNavigation(); coverageNote(); renderResults();
  return showMap(fit);
}
function navigate(province = "", region = "", city = "", area = "") {
  if (province && byId.get(province)?.level !== "province") return;
  if (region && (byId.get(region)?.level !== "region" || byId.get(region).province !== province)) return;
  if (city && (!cityChildren.has(city) || byId.get(city)?.province !== province || (byId.get(city).region_id || "") !== region)) return;
  if (area && (!cityChildren.has(area) || byId.get(area)?.parent_csd_id !== city)) return;
  clearTimeout(searchTimer);
  locationState = {province, region, city, area};
  const children = city && !area ? cityChildren.get(city) || [] : [];
  const schemes = [...new Set(children.map(r => r.scheme || "default"))].sort((a, b) =>
    a === "former_municipality" ? -1 : b === "former_municipality" ? 1 : a.localeCompare(b));
  el("city-scheme").replaceChildren();
  el("city-scheme-control").hidden = schemes.length < 2;
  if (schemes.length > 1) {
    for (const scheme of schemes) {
      const rows = children.filter(r => (r.scheme || "default") === scheme);
      el("city-scheme").append(new Option(areaCounts(rows), scheme));
    }
  }
  el("province").value = province;
  el("search").value = ""; el("issues-only").checked = false;
  const refreshed = refresh(true);
  el("results").closest("aside").scrollTop = 0;
  return refreshed;
}
async function start() {
  data = await getJSON("catalogue.json");
  data.regions = data.regions || [];
  data.city_areas = data.city_areas || [];
  for (const [rows, level] of [[data.areas, "municipality"], [data.regions, "region"], [data.provinces, "province"], [data.city_areas, "city_area"]]) {
    for (const row of rows) { row.level = level; row.issues = row.issues || []; byId.set(row.id, row); }
    rows.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
  }
  data.areas = data.areas.filter(row => row.lifecycle_status !== "superseded");
  data.regions = data.regions.filter(row => row.lifecycle_status !== "superseded");
  for (const row of data.city_areas) {
    const parent = row.parent_area_id || row.parent_csd_id;
    if (!cityChildren.has(parent)) cityChildren.set(parent, []);
    cityChildren.get(parent).push(row);
    row.searchText = normal(`${row.name} ${row.id} ${row.source_id} ${row.type} ${row.parent_name} ${(row.aliases || []).join(" ")}`);
  }
  for (const row of data.city_areas) if (hasChildren(row)) row.searchText += " " + cityChildren.get(row.id).map(a => a.searchText).join(" ");
  for (const row of data.report.city_areas?.municipalities || []) {
    if (!cityCoverage.has(row.parent_csd_id)) cityCoverage.set(row.parent_csd_id, []);
    cityCoverage.get(row.parent_csd_id).push(row);
  }
  for (const row of data.areas) row.searchText = normal(`${row.name} ${row.id} ${row.code} ${(row.aliases || []).join(" ")} ${byId.get(row.region_id)?.name || ""} ${(cityChildren.get(row.id) || []).map(a => a.searchText).join(" ")}`);
  for (const row of data.regions) row.searchText = normal(`${row.name} ${row.id} ${row.code} ${(row.aliases || []).join(" ")} ${data.areas.filter(a => a.region_id === row.id).map(a => a.searchText).join(" ")}`);
  for (const row of data.provinces) row.searchText = normal(`${row.name} ${row.code} ${data.regions.filter(r => r.province === row.id).map(r => r.searchText).join(" ")} ${data.areas.filter(a => a.province === row.id).map(a => a.searchText).join(" ")}`);
  el("area-count").textContent = data.areas.length.toLocaleString();
  el("region-count").textContent = data.regions.length.toLocaleString();
  el("city-area-count").textContent = data.city_areas.length.toLocaleString();
  el("issue-count").textContent = [...byId.values()].filter(row => row.lifecycle_status !== "superseded" &&
    (row.issues.length || row.level === "province" && row.display_reference_year && row.repair)).length;
  el("reference-date").textContent = data.report.source.reference_date + (data.report.quebec_refresh ? ` · Québec updates ${data.report.quebec_refresh.reviewed_on}` : "") + (data.report.ontario_refresh ? ` · Ontario updates ${data.report.ontario_refresh.reviewed_on}` : "");
  if (data.report.jurisdiction_refreshes) el("reference-date").textContent += ` · ${Object.keys(data.report.jurisdiction_refreshes).length} jurisdiction coverage reports`;
  const source = data.report.source;
  const regionalSources = (data.report.regions?.sources || []).slice(1);
  const statcanCredit = s => `Adapted from Statistics Canada, ${s.family}, ${s.reference_date}. This does not constitute an endorsement by Statistics Canada of this product.`;
  el("attribution").textContent = source.authority === "Statistics Canada" ? statcanCredit(source) : `Source: ${source.authority}, ${source.family}, ${source.reference_date}.`;
  if (data.report.province_display_source) el("attribution").textContent += ` Province overview (display only): ${statcanCredit(data.report.province_display_source)}`;
  el("attribution").textContent += ` ${regionalSources.map(s => `Regional grouping reference: ${s.authority}, ${s.release}.`).join(" ")}`;
  const additionalSources = [...Object.values(data.report.city_areas?.sources || {}), ...Object.values(data.report.ontario_refresh?.sources || {}),
    ...Object.values(data.report.jurisdiction_refreshes || {}).flatMap(report => Object.values(report.sources || {}))];
  const credited = new Set();
  for (const item of additionalSources) {
    const key = `${item.authority}|${item.licence}`;
    if (credited.has(key)) continue;
    credited.add(key);
    el("attribution").textContent += ` Additional geography: ${item.authority}.`;
    if (item.authority === "City of Toronto") el("attribution").textContent += " Contains information licensed under the Open Government Licence – Toronto.";
    if (item.attribution) el("attribution").textContent += ` ${item.attribution}`;
    if (item.attribution_statement) el("attribution").textContent += ` ${item.attribution_statement}`;
    const link = document.createElement("a"), url = new URL(item.licence, location.href);
    link.textContent = `${item.authority} licence`;
    if (url.protocol === "https:") link.href = url.href;
    link.target = "_blank"; link.rel = "noreferrer";
    el("additional-licences").append(link, document.createTextNode(" "));
  }
  const licence = new URL(source.licence, location.href);
  if (licence.protocol === "https:") el("licence").href = licence.href;
  else el("licence").removeAttribute("href");
  el("quebec-licence").hidden = !regionalSources.length;
  if (regionalSources.length) {
    const regionalLicence = new URL(regionalSources[0].licence, location.href);
    if (regionalLicence.protocol === "https:") el("quebec-licence").href = regionalLicence.href;
    else el("quebec-licence").removeAttribute("href");
  }
  for (const province of data.provinces) el("province").append(new Option(`${province.code} · ${province.name}`, province.id));
  for (const entry of data.report.regions?.jurisdictions || []) {
    const current = data.report.jurisdiction_refreshes?.[entry.province]?.migrations?.regional_coverage;
    el("coverage-decisions").append(line(current ?
      `${entry.code} · ${current.current_region_ids.length} regions · ${current.member_count} municipal members · ${current.unassigned_municipality_ids.length} municipalities without a regional grouping` :
      `${entry.code} · ${entry.status === "deferred" ? "Deferred" : `${entry.expected_region_count} regions`} — ${entry.reason}`));
  }
  for (const entry of data.report.city_areas?.municipalities || []) {
    el("city-area-decisions").append(line(`${entry.name} · ${entry.expected_count} areas${entry.coverage_policy === "partial" ? " · Partial city coverage" : entry.coverage_policy === "unavailable" ? " · Boundaries unavailable" : ""}`));
  }
  for (const note of data.report.ontario_refresh?.unresolved || []) el("city-area-decisions").append(line(note));
  for (const [province, report] of Object.entries(data.report.jurisdiction_refreshes || {})) {
    const pending = report.audit.municipalities.filter(row => row.status === "pending_municipal_site_review").length;
    el("city-area-decisions").append(line(`${byId.get(province).name} · ${report.added_city_area_count} added areas · ${pending} municipal source searches pending.`));
  }
  if (!data.city_areas.length) el("city-area-decisions").append(line("No city areas added to this run yet."));
  el("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => refresh(), 150); });
  el("issues-only").addEventListener("change", () => refresh());
  el("city-scheme").addEventListener("change", () => refresh());
  el("province").addEventListener("change", () => navigate(el("province").value));
  el("more").addEventListener("click", () => { shown += 100; renderResults(); });
  el("back").addEventListener("click", () => locationState.area ? navigate(locationState.province, locationState.region, locationState.city) : locationState.city ? navigate(locationState.province, locationState.region) : navigate(locationState.region ? locationState.province : ""));
  await refresh(true);
}
start().catch(error => { el("result-count").textContent = `Catalogue load failed: ${error.message}`; console.error(error); });
