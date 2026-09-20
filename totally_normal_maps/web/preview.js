/* Local display only. External names are always assigned as text, never HTML. */
"use strict";
const el = id => document.getElementById(id);
const normal = text => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const map = L.map("map", {crs: L.CRS.EPSG4326, minZoom: 1, zoomSnap: 0});
map.createPane("surroundingAreas").style.zIndex = 380;
const surroundingAreas = L.featureGroup().addTo(map);
map.createPane("comparison").style.zIndex = 450;
map.getPane("comparison").style.pointerEvents = "none";
const comparisonOutlines = L.layerGroup().addTo(map);
const contextOutline = L.featureGroup().addTo(map);
const drawn = L.featureGroup().addTo(map);
map.createPane("regionNames").style.pointerEvents = "none";
map.getPane("regionNames").style.zIndex = 620;
const regionNames = L.layerGroup().addTo(map);
let backgroundLayer = null, reliefLayer = null, backgroundGeneration = 0;
let boundaryOpacity = .2;
let backgroundOpacity = .65, selectionGeneration = 0;
const viewCanada = () => map.fitBounds([[41, -142], [84, -50]], {padding: [10, 10], animate: false});
viewCanada();
map.attributionControl.setPrefix(false);
map.attributionControl.addAttribution("Simplified display boundaries");
const colours = ["#426f59", "#8b773e", "#5a7795", "#98645b", "#367c6a", "#759458", "#8c7698"];
let data, selected = null, shown = 100, generation = 0, searchTimer;
let locationState = {province: "", region: "", city: "", area: ""};
const layers = new Map(), loading = new Map(), byId = new Map();
const cityChildren = new Map(), cityCoverage = new Map();
const activeFamily = () => el("map-layer").value;
const electoralEditions = () => [...(data.report.electoral?.editions || []), ...(data.report.municipal_elections?.editions || [])];
const municipalCoverage = () => data.report.municipal_elections?.coverage || {};
const coverageLabel = status => ({included: "Wards available", reference: "Reference boundaries", at_large: "Elected at large", unverified: "Not yet verified", unavailable: "Boundaries unavailable", partial: "Partial coverage", historical_only: "Historical editions only"})[status] || status;
function updateMunicipalAuthorities() {
  const control = el("municipal-authority");
  el("municipal-control").hidden = activeFamily() !== "municipal";
  control.replaceChildren(new Option("All available local boundaries", ""));
  const rows = Object.values(municipalCoverage()).filter(r => !locationState.province || r.province === locationState.province)
    .sort((a,b) => a.name.localeCompare(b.name) || a.authority_id.localeCompare(b.authority_id));
  for (const r of rows) control.append(new Option(`${r.name} · ${byId.get(r.province).code} · ${coverageLabel(r.status)}`, r.authority_id));
  control.value = locationState.city;
}
function electoralRows(family, province = locationState.province, edition = "") {
  const chosen = new Set(electoralEditions().filter(e => e.layer === family &&
    (edition ? e.id === edition : e.default)).map(e => e.id));
  return data.electoral_areas.filter(r => r.layer === family && chosen.has(r.edition) && (!province || r.province === province) &&
    (family !== "municipal" || activeFamily() !== "municipal" || !locationState.city || r.authority_id === locationState.city));
}
function updateEditions() {
  const old = el("edition").value;
  const choices = electoralEditions().filter(e => e.layer === activeFamily() &&
    (!locationState.province || e.provinces.includes(locationState.province)) &&
    (activeFamily() !== "municipal" || !locationState.city || e.authority_id === locationState.city));
  el("edition").replaceChildren(new Option(activeFamily() === "municipal" ? "Latest available · per local authority" : "Default editions · per province", ""));
  for (const e of choices) el("edition").append(new Option(`${e.label} · ${e.status}`, e.id));
  if (choices.some(e => e.id === old)) el("edition").value = old;
  el("edition-control").hidden = activeFamily() === "administrative";
  for (const option of el("comparison-layer").options) option.disabled = option.value === activeFamily();
  if (el("comparison-layer").value === activeFamily()) el("comparison-layer").value = "";
}
function comparisonRows() {
  const family = el("comparison-layer").value, p = locationState.province;
  if (!family) return [];
  if (family !== "administrative") return electoralRows(family);
  return p ? provinceChildren(p) : data.provinces;
}
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
  const counts = {province: 0, region: 0, municipality: 0, city_area: 0, electoral_district: 0};
  rows.forEach(row => counts[row.level]++);
  const parts = [];
  if (counts.province) parts.push(countText(counts.province, "province / territory", "provinces / territories"));
  if (counts.region) parts.push(countText(counts.region, "region"));
  if (counts.municipality) parts.push(countText(counts.municipality, "municipality", "municipalities"));
  if (counts.city_area) parts.push(areaCounts(rows.filter(row => row.level === "city_area")));
  if (counts.electoral_district) parts.push(countText(counts.electoral_district, "electoral district"));
  return (parts.join(" · ") || "0 areas") + (boundaries ? " · Simplified boundaries" : "");
}
function currentRows() {
  if (activeFamily() !== "administrative") return electoralRows(activeFamily(), locationState.province, el("edition").value);
  const {province, region, city, area} = locationState;
  if (area) return cityChildren.get(area) || [];
  if (city) return (cityChildren.get(city) || []).filter(r => !el("city-scheme").value || (r.scheme || "default") === el("city-scheme").value);
  if (!province) return data.provinces;
  if (region) return data.areas.filter(row => row.region_id === region);
  // Ungrouped municipalities stay directly reachable, without inventing a region.
  return provinceChildren(province);
}
function provinceChildren(province) {
  return [...data.regions.filter(row => row.province === province),
    ...data.areas.filter(row => row.province === province && !row.region_id)];
}
function siblings(row) {
  if (row.level === "province") return data.provinces;
  if (row.level === "region" || row.level === "municipality" && !row.region_id) return provinceChildren(row.province);
  if (row.level === "municipality") return data.areas.filter(other => other.region_id === row.region_id);
  return (cityChildren.get(row.parent_area_id || row.parent_csd_id) || [])
    .filter(other => (other.scheme || "default") === (row.scheme || "default"));
}
function surroundingRows() {
  if (activeFamily() !== "administrative") return [
    ...data.provinces.filter(r => r.id !== locationState.province),
    ...(activeFamily() === "municipal" && locationState.province ? data.areas.filter(r => r.province === locationState.province && r.id !== locationState.city) : [])];
  const rows = new Map();
  // Preserve each ancestor's siblings, from provinces down to city areas.
  for (const id of Object.values(locationState).filter(Boolean)) {
    for (const row of siblings(byId.get(id))) if (row.id !== id) rows.set(row.id, row);
  }
  return [...rows.values()];
}
function boundaryKey(row) {
  return row.level === "electoral_district" ? `${row.layer === "municipal" ? "municipal" : "electoral"}-${row.province}` : row.level === "province" ? "provinces" : row.level === "region" ? `regions-${row.province}` :
    row.level === "city_area" ? `city-areas-${row.province}` : row.province;
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
    fillColor: colour, dashArray: repair ? "4 3" : null,
    fillOpacity: boundaryOpacity === 0 ? 0 : Math.min(.75, boundaryOpacity + (active ? .15 : 0))};
}
function surroundingStyle(feature) {
  const row = byId.get(feature.properties.id);
  return {color: row.assignment_status?.startsWith("unreviewed_") ? "#ad6328" : "#7f9189",
    weight: 1, opacity: .75, fillColor: "#aab9b0", fillOpacity: boundaryOpacity * .25,
    dashArray: row.assignment_status?.startsWith("unreviewed_") ? "4 3" : null};
}

function setBackgroundOpacity() {
  backgroundOpacity = Number(el("background-opacity").value) / 100;
  el("background-opacity-value").value = `${Math.round(backgroundOpacity * 100)}%`;
  // Fade the composed background once, keeping the terrain blend consistent.
  map.getPane("tilePane").style.opacity = backgroundOpacity;
}

function setBackground() {
  const version = ++backgroundGeneration;
  if (backgroundLayer) map.removeLayer(backgroundLayer);
  if (reliefLayer) map.removeLayer(reliefLayer);
  backgroundLayer = reliefLayer = null;
  const online = el("background").value === "topographic";
  el("relief").disabled = !online;
  el("background-opacity").disabled = !online;
  if (!online) { el("background-status").textContent = "Offline view · boundary files only"; return; }
  el("background-status").textContent = "Loading Natural Resources Canada background…";
  let failed = false;
  function watch(layer) {
    layer.on("tileerror", () => {
      if (version !== backgroundGeneration) return;
      failed = true;
      el("background-status").textContent = "Some background tiles are unavailable. Boundaries still work; select None for an offline view.";
    });
    layer.on("load", () => {
      if (version === backgroundGeneration && !failed) el("background-status").textContent =
        "Online background · Natural Resources Canada" + (el("relief").checked ? " · shaded relief" : "");
    });
    return layer;
  }
  backgroundLayer = watch(L.tileLayer.wms("https://maps.geogratis.gc.ca/wms/toporama_en", {
    layers: "WMS-Toporama", version: "1.1.1", format: "image/png", transparent: false,
    attribution: 'Background: <a href="https://natural-resources.canada.ca/maps-tools-publications/maps/atlas-canada" target="_blank" rel="noreferrer">Natural Resources Canada</a> · <a href="https://open.canada.ca/en/open-government-licence-canada" target="_blank" rel="noreferrer">Open Government Licence</a>',
    maxZoom: 18, noWrap: true, updateWhenIdle: true, keepBuffer: 1, referrerPolicy: "no-referrer"
  })).addTo(map);
  if (el("relief").checked) {
    reliefLayer = watch(L.tileLayer.wms("https://geoappext.nrcan.gc.ca/arcgis/services/NRCAN/Digital_Relief_EN/MapServer/WMSServer", {
      layers: "4", version: "1.3.0", format: "image/png", transparent: true, opacity: .28,
      attribution: "Relief: Natural Resources Canada", maxZoom: 18, noWrap: true,
      updateWhenIdle: true, keepBuffer: 1, referrerPolicy: "no-referrer"
    })).addTo(map);
  }
}

function ringContains(ring, point) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > point[1]) !== (yj > point[1]) && point[0] < (xj - xi) * (point[1] - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function polygonContains(polygon, point) {
  return ringContains(polygon[0], point) && !polygon.slice(1).some(ring => ringContains(ring, point));
}
function labelCandidates(feature) {
  const polygons = feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  const candidates = [];
  for (const polygon of polygons) {
    const ring = polygon[0];
    let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
    for (const [x, y] of ring) { west = Math.min(west, x); east = Math.max(east, x); south = Math.min(south, y); north = Math.max(north, y); }
    for (let x = 1; x <= 7; x++) for (let y = 1; y <= 7; y++) {
      const point = [west + (east - west) * x / 8, south + (north - south) * y / 8];
      if (polygonContains(polygon, point)) candidates.push({point, polygon,
        score: (east - west) * (north - south) / (1 + (x - 4) ** 2 + (y - 4) ** 2)});
    }
  }
  return candidates.sort((a, b) => b.score - a.score);
}
function drawRegionNames() {
  regionNames.clearLayers();
  if (!data || !el("region-labels").checked) return;
  const size = map.getSize(), occupied = [];
  const visible = drawn.getLayers().filter(layer => byId.get(layer.feature.properties.id)?.level === "region" || byId.get(layer.feature.properties.id)?.level === "electoral_district");
  // Larger regions get first choice; tiny regions remain identifiable on hover.
  visible.sort((a, b) => b.getBounds().getNorthEast().distanceTo(b.getBounds().getSouthWest()) - a.getBounds().getNorthEast().distanceTo(a.getBounds().getSouthWest()));
  for (const layer of visible) {
    const bounds = layer.getBounds();
    if (!map.getBounds().intersects(bounds)) continue;
    const northwest = map.latLngToContainerPoint(bounds.getNorthWest()), southeast = map.latLngToContainerPoint(bounds.getSouthEast());
    if (southeast.x - northwest.x < 30 || southeast.y - northwest.y < 14) continue;
    const row = byId.get(layer.feature.properties.id);
    const label = document.createElement("span"); label.className = "region-name-text"; label.textContent = row.name;
    label.style.visibility = "hidden"; el("map").append(label);
    const measured = label.getBoundingClientRect(); label.remove(); label.style.visibility = "";
    const width = measured.width + 8, height = measured.height + 6;
    layer.labelCandidates ||= labelCandidates(layer.feature);
    for (const {point, polygon} of layer.labelCandidates) {
      const anchor = map.latLngToContainerPoint([point[1], point[0]]);
      const box = {left: anchor.x - width / 2, right: anchor.x + width / 2, top: anchor.y - height / 2, bottom: anchor.y + height / 2};
      if (box.left < 8 || box.right > size.x - 8 || box.top < 8 || box.bottom > size.y - 8) continue;
      if (occupied.some(b => box.left < b.right + 6 && box.right > b.left - 6 && box.top < b.bottom + 6 && box.bottom > b.top - 6)) continue;
      const fits = [box.left, anchor.x, box.right].every(x => [box.top, anchor.y, box.bottom].every(y => {
        const latlng = map.containerPointToLatLng([x, y]);
        return polygonContains(polygon, [latlng.lng, latlng.lat]);
      }));
      if (!fits) continue;
      label.dataset.regionId = row.id;
      L.marker([point[1], point[0]], {pane: "regionNames", interactive: false, keyboard: false,
        icon: L.divIcon({className: "region-name", html: label, iconSize: [width, height], iconAnchor: [width / 2, height / 2]})}).addTo(regionNames);
      occupied.push(box); break;
    }
  }
}
map.on("zoomend moveend resize", drawRegionNames);
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
    el("selection").append(line(activeFamily() === "administrative" ?
      "Choose a province or territory on the map or in the list to open the next level." :
      "Choose an electoral district on the map or in the list. Select a province to narrow the view."));
    return;
  }
  if (row.level === "electoral_district") {
    const edition = electoralEditions().find(e => e.id === row.edition);
    el("selection").append(line(`${row.type} · ${byId.get(row.province).name} · Source identifier: ${row.source_id}`),
      line(`${edition.label} · ${edition.status} · ${edition.electoral_event}`),
      line(`Source: ${edition.authority}.`),
      ...(row.authority_name ? [line(`Local authority: ${row.authority_name}`)] : []));
    if (edition.status === "reference") el("selection").append(line(`Reference snapshot ${edition.source_date || "(date unavailable)"}; applicability to the current election is unverified.`, "issue"));
    const evidence = document.createElement("a"); evidence.textContent = "Boundary source and edition evidence";
    if (new URL(edition.evidence_url).protocol === "https:") evidence.href = edition.evidence_url;
    evidence.target = "_blank"; evidence.rel = "noreferrer"; el("selection").append(evidence);
    if (row.assignment_status !== "validated_source") el("selection").append(line(
      row.assignment_status === "missing_geometry" ? "Boundary unavailable pending source review." :
      "Outline shown for review; this district is unavailable for point assignment.", "issue"));
  } else if (activeFamily() === "municipal" && municipalCoverage()[row.id]) {
    const coverage = municipalCoverage()[row.id];
    el("selection").append(line(coverageLabel(coverage.status)), line(coverage.note), line(`${coverage.district_count} districts in the latest available editions.`));
  } else if (row.level === "province" && activeFamily() !== "administrative") {
    el("selection").append(line(`${countText(currentRows().length, "electoral district")} in the selected layer and edition.`));
  } else if (row.level === "province") {
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
    const reviewed = row.repair.status === "reviewed_topology";
    el("selection").append(line(`${reviewed ? "Reviewed topology repair" : "Unreviewed repair"} · Area change ${row.repair.area_change_m2.toFixed(3)} m² · Parts ${row.repair.source_parts} → ${row.repair.candidate_parts} · Holes ${row.repair.source_holes} → ${row.repair.candidate_holes}`, reviewed ? "" : "issue"));
  }
}
async function openRow(id) {
  const row = byId.get(id);
  if (!row) return;
  if (activeFamily() === "municipal" && municipalCoverage()[row.id]) navigate(row.province, "", row.id);
  else if (row.level === "province") navigate(row.id);
  else if (row.level === "region") navigate(row.province, row.id);
  else if (hasChildren(row)) navigate(row.province, row.region_id || "", row.level === "city_area" ? row.parent_csd_id : row.id, row.level === "city_area" ? row.id : "");
  else {
    const parent = {province: row.province, region: row.region_id || "",
      city: row.layer === "municipal" ? row.authority_id : row.level === "city_area" ? row.parent_csd_id : "",
      area: row.level === "city_area" ? row.parent_area_id || "" : ""};
    const refreshed = Object.keys(parent).some(key => parent[key] !== locationState[key]) ?
      navigate(parent.province, parent.region, parent.city, parent.area) : Promise.resolve();
    const request = ++selectionGeneration;
    await refreshed;
    if (request !== selectionGeneration) return;
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
    if ((row.level === "city_area" || row.level === "municipality" || row.level === "electoral_district") && !hasChildren(row)) item.setAttribute("aria-pressed", String(row.id === selected));
    const title = document.createElement("span"), name = document.createElement("strong"), note = document.createElement("small"), code = document.createElement("span");
    name.textContent = row.name;
    note.textContent = (row.level === "province" ? `${countText(row.count, "municipal-level area")} · Open →` :
      row.level === "region" ? `${row.member_count} areas · ${row.type}${row.coverage_policy === "selected_members" ? " · Partial coverage" : ""} · Open →` :
      row.level === "electoral_district" ? `${row.authority_name ? row.authority_name + " · " : ""}${row.type} · ${row.source_id} · ${row.edition_status}` :
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
  el("search").placeholder = activeFamily() !== "administrative" ? "Find an electoral district or source ID" : city ? "Find a city area or source ID" : !province ? "Find a province or territory" : region || !data.regions.some(r => r.province === province) ?
    "Find a municipality or source ID" : "Find a region or municipality";
}
function coverageNote() {
  if (activeFamily() === "municipal") {
    const scope = municipalCoverage()[locationState.city];
    const selected = electoralEditions().find(e => e.id === el("edition").value);
    const inventory = Object.values(municipalCoverage()).filter(r => !locationState.province || r.province === locationState.province);
    const count = status => inventory.filter(r => r.status === status).length;
    el("coverage-note").textContent = selected ? `${selected.label} · ${selected.status} · ${currentRows().length} districts. ${selected.status === "reference" ? "Current applicability is unverified." : ""}` : scope ?
      `${scope.name} · ${coverageLabel(scope.status)}. ${scope.note}` :
      `${count("included")} authorities with current boundaries · ${count("reference")} with reference snapshots · ${count("at_large")} elected at large · ${count("unverified")} not yet verified. Select a local authority to inspect coverage.`;
    return;
  }
  if (activeFamily() !== "administrative") {
    const scope = locationState.province ? byId.get(locationState.province).name : "Canada";
    const visibleEditions = new Set(currentRows().map(r => r.edition));
    const editions = electoralEditions().filter(e => visibleEditions.has(e.id));
    const inventory = data.report.electoral?.edition_coverage || {};
    const scopeProvinces = locationState.province ? [locationState.province] : data.provinces.map(p => p.id);
    const gaps = scopeProvinces.flatMap(p => {
      const selected = editions.filter(e => e.provinces.includes(p));
      if (!selected.length) return el("edition").value ? [] : [[p, {note: "No default edition available."}]];
      return selected.flatMap(e => inventory[e.id]?.[p]?.status === "partial" || inventory[e.id]?.[p]?.status === "unavailable" ?
        [[p, inventory[e.id][p]]] : []);
    });
    const pending = currentRows().filter(r => r.assignment_status !== "validated_source").length;
    el("coverage-note").textContent = `${scope} · ${countText(currentRows().length, "electoral district")} · ` +
      editions.map(e => `${e.label} (${e.status})`).join("; ") +
      (gaps.length ? ` · Coverage notes: ${gaps.map(([p, v]) => `${byId.get(p)?.name}: ${v.note}`).join("; ")}` : "") +
      (pending ? ` · ${pending} district boundaries need review before point assignment.` : "");
    return;
  }
  const {province, region, city, area} = locationState;
  const entry = data.report.regions?.jurisdictions.find(j => j.province === province);
  el("coverage-note").textContent = city ? `${byId.get(area || city).name} · ${areaCounts(cityChildren.get(area || city))}. The outer line shows the parent boundary.` :
    !province ? "Choose one of Canada's 13 provinces and territories to begin." :
    region ? `${byId.get(region).name} · ${byId.get(region).coverage_policy === "selected_members" ? "Selected communities; outlines show their combined footprint, not the complete region." : "Municipalities within this region."}` :
      !entry || entry.status === "deferred" ? "No regional layer selected. Showing municipalities directly." :
        `${countText(entry.expected_region_count, "region")}${entry.unassigned_member_count ? ` · ${countText(entry.unassigned_member_count, "municipality", "municipalities")} shown directly without a regional grouping` : ""}. Click to explore.`;
}
function bindArea(feature, child, surrounding = false) {
  const row = byId.get(feature.properties.id);
  const label = document.createElement("span");
  label.textContent = surrounding ? `${row.name} · Click to switch` : row.level === "province" ? row.code :
    `${row.name} · ${row.level === "city_area" ? row.type : row.code}`;
  child.bindTooltip(label, !surrounding && row.level === "province" ?
    {permanent: true, direction: "center", className: "province-label"} : {sticky: true});
  child.on("click", () => openRow(row.id));
  child.on("add", () => {
    if (!surrounding && row.label_point) child.getTooltip().setLatLng(row.label_point);
    else if (!surrounding && row.level === "province") child.getTooltip().setLatLng(child.getBounds().getCenter());
    const path = child.getElement(), key = surrounding ? "contextAreaId" : "areaId";
    if (!path || path.dataset[key]) return;
    path.dataset[key] = row.id;
    path.setAttribute("role", "button");
    path.setAttribute("tabindex", "0");
    path.setAttribute("aria-label", `${surrounding ? "Switch to" :
      (row.level === "city_area" || row.level === "municipality" || row.level === "electoral_district") && !hasChildren(row) ? "Inspect" : "Open"} ${row.name}`);
    path.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); event.stopPropagation(); openRow(row.id);
      }
    });
  });
}
async function boundaryLayer(key) {
  if (layers.has(key)) return layers.get(key);
  if (!loading.has(key)) {
    loading.set(key, getJSON(`${key}.geojson`).then(geojson => {
      const layer = L.geoJSON(geojson, {
        style, smoothFactor: .2,
        onEachFeature: (feature, child) => bindArea(feature, child)
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
  const surrounding = surroundingRows(), comparison = comparisonRows();
  const compared = new Set(comparison.map(r => r.edition).filter(Boolean));
  const comparisonLabels = electoralEditions().filter(e => compared.has(e.id)).map(e => `${e.label} (${e.status})`);
  el("comparison-note").hidden = !el("comparison-layer").value;
  el("comparison-note").textContent = "Purple dashed outlines: " +
    (comparisonLabels.length === 1 ? comparisonLabels[0] : el("comparison-layer").selectedOptions[0].text +
      (comparisonLabels.length ? " · default editions per province" : ""));
  comparisonOutlines.clearLayers();
  drawn.clearLayers(); contextOutline.clearLayers(); regionNames.clearLayers(); surroundingAreas.clearLayers();
  el("map-status").textContent = "Loading boundaries…";
  try {
    const keys = activeFamily() !== "administrative" ? ["provinces", ...rows.map(boundaryKey), ...(city ? [boundaryKey(byId.get(city))] : [])] : city ? [province, `city-areas-${province}`] : !province ? ["provinces"] : region ? [province, `regions-${province}`] :
      ["provinces", ...(rows.some(r => r.level === "region") ? [`regions-${province}`] : []),
        ...(rows.some(r => r.level === "municipality") ? [province] : [])];
    const loads = await Promise.allSettled([...new Set([...keys, ...surrounding.map(boundaryKey), ...comparison.map(boundaryKey)])].map(boundaryLayer));
    if (current !== generation) return;
    const available = loads.filter(result => result.status === "fulfilled").map(result => result.value);
    const failed = loads.some(result => result.status === "rejected");
    el("retry-boundaries").hidden = !failed;
    for (const layer of available) layer.eachLayer(child => {
      const id = child.feature.properties.id;
      if (id === (area || city || region || province)) {
        L.geoJSON(child.feature, {interactive: false, style: {color: "#60756b", weight: 2, fill: false}}).addTo(contextOutline);
      }
      if (ids.has(id)) { child.setStyle(style(child.feature)); drawn.addLayer(child); }
    });
    // Coarse outlines sit behind finer context and all active children. Clones
    // avoid moving the cached interactive layer into two groups at once.
    const features = new Map();
    for (const layer of available) layer.eachLayer(child => features.set(child.feature.properties.id, child.feature));
    for (const row of comparison) {
      const feature = features.get(row.id);
      if (feature) L.geoJSON(feature, {pane: "comparison", interactive: false,
        style: {color: "#705796", weight: 1.5, dashArray: "5 4", fill: false, opacity: .85}}).addTo(comparisonOutlines);
    }
    for (const row of surrounding) {
      const feature = features.get(row.id);
      if (feature && !ids.has(row.id)) {
        L.geoJSON(feature, {pane: "surroundingAreas", style: surroundingStyle, smoothFactor: .2,
          onEachFeature: (f, child) => bindArea(f, child, true)}).eachLayer(child => surroundingAreas.addLayer(child));
      }
    }
    const visible = drawn.getLayers().map(layer => byId.get(layer.feature.properties.id));
    const missing = rows.length - visible.length;
    el("map-status").textContent = describeRows(visible, true) + (missing ? ` · ${missing} without an available outline` : "") +
      (failed ? " · Some boundaries failed to load. Retry to restore them." : "");
    if (fit) {
      map.invalidateSize({pan: false});
      if (province) fitRow(byId.get(area || city || region || province));
      else viewCanada();
    }
    drawRegionNames();
  } catch (error) {
    if (current === generation) el("map-status").textContent = `Boundary load failed: ${error.message}`;
    console.error(error);
  }
}
function refresh(fit = false) {
  ++selectionGeneration;
  clearTimeout(searchTimer);
  shown = 100; selected = null;
  showDetails(byId.get(locationState.area || locationState.city || locationState.region || locationState.province));
  renderNavigation(); coverageNote(); renderResults();
  return showMap(fit);
}
function navigate(province = "", region = "", city = "", area = "", fit = true) {
  if (activeFamily() !== "administrative") { region = ""; area = ""; if (activeFamily() !== "municipal") city = ""; }
  if (province && byId.get(province)?.level !== "province") return;
  if (region && (byId.get(region)?.level !== "region" || byId.get(region).province !== province)) return;
  if (city && activeFamily() === "municipal" && (!municipalCoverage()[city] || byId.get(city)?.province !== province)) return;
  if (city && activeFamily() !== "municipal" && (!cityChildren.has(city) || byId.get(city)?.province !== province || (byId.get(city).region_id || "") !== region)) return;
  if (area && (!cityChildren.has(area) || byId.get(area)?.parent_csd_id !== city)) return;
  clearTimeout(searchTimer);
  locationState = {province, region, city, area};
  updateMunicipalAuthorities();
  updateEditions();
  const children = activeFamily() === "administrative" && city && !area ? cityChildren.get(city) || [] : [];
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
  const refreshed = refresh(fit);
  el("results").closest("aside").scrollTop = 0;
  return refreshed;
}
async function start() {
  const requestedBackground = new URLSearchParams(location.search).get("background");
  if (requestedBackground === "none") el("background").value = "none";
  el("background").addEventListener("change", setBackground);
  el("background-opacity").addEventListener("input", setBackgroundOpacity);
  el("relief").addEventListener("change", setBackground);
  el("region-labels").addEventListener("change", drawRegionNames);
  el("boundary-opacity").addEventListener("input", () => {
    boundaryOpacity = Number(el("boundary-opacity").value) / 100;
    el("opacity-value").value = `${Math.round(boundaryOpacity * 100)}%`;
    drawn.eachLayer(layer => layer.setStyle(style(layer.feature)));
    surroundingAreas.eachLayer(layer => layer.setStyle(surroundingStyle(layer.feature)));
  });
  setBackgroundOpacity();
  setBackground();
  data = await getJSON("catalogue.json");
  data.electoral_areas = data.electoral_areas || [];
  data.regions = data.regions || [];
  data.city_areas = data.city_areas || [];
  for (const [rows, level] of [[data.areas, "municipality"], [data.regions, "region"], [data.provinces, "province"], [data.city_areas, "city_area"], [data.electoral_areas, "electoral_district"]]) {
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
  for (const row of data.electoral_areas) row.searchText = normal(`${row.name} ${row.id} ${row.source_id} ${row.catalogue_code || ""} ${row.authority_name || ""} ${row.code} ${(row.aliases || []).join(" ")}`);
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
  el("source-summary").textContent = el("attribution").textContent;
  if (data.report.province_display_source) el("attribution").textContent += ` Province overview (display only): ${statcanCredit(data.report.province_display_source)}`;
  el("attribution").textContent += ` ${regionalSources.map(s => `Regional grouping reference: ${s.authority}, ${s.release}.`).join(" ")}`;
  const additionalSources = [...Object.values(data.report.city_areas?.sources || {}), ...Object.values(data.report.ontario_refresh?.sources || {}), ...Object.values(data.report.electoral?.sources || {}), ...Object.values(data.report.municipal_elections?.sources || {}),
    ...Object.values(data.report.jurisdiction_refreshes || {}).flatMap(report => Object.values(report.sources || {}))];
  const statements = new Set(additionalSources.map(item => item.attribution_statement).filter(Boolean));
  el("required-attributions").replaceChildren(...[...statements].map(statement => line(statement)));
  const credited = new Set();
  for (const item of additionalSources) {
    const key = `${item.authority}|${item.licence}`;
    if (credited.has(key)) continue;
    credited.add(key);
    el("attribution").textContent += ` Additional geography: ${item.authority}.`;
    if (item.authority === "City of Toronto") el("attribution").textContent += " Contains information licensed under the Open Government Licence – Toronto.";
    if (item.attribution) el("attribution").textContent += ` ${item.attribution}`;
    else if (item.attribution_statement) el("attribution").textContent += ` ${item.attribution_statement}`;
    const link = document.createElement("a"), url = new URL(item.licence, location.href);
    link.textContent = `${item.authority} ${item.redistribution_status === "unconfirmed" ? "reuse information (unconfirmed)" : "licence"}`;
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
  updateMunicipalAuthorities();
  updateEditions();
  el("municipal-authority").addEventListener("change", () => {
    el("edition").value = "";
    const row = byId.get(el("municipal-authority").value);
    navigate(row?.province || locationState.province, "", row?.id || "");
  });
  el("map-layer").addEventListener("change", () => { el("edition").value = ""; navigate(locationState.province, "", "", "", false); });
  el("edition").addEventListener("change", () => refresh());
  el("comparison-layer").addEventListener("change", () => showMap());
  el("retry-boundaries").addEventListener("click", () => showMap());
  el("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => refresh(), 150); });
  el("issues-only").addEventListener("change", () => refresh());
  el("city-scheme").addEventListener("change", () => refresh());
  el("province").addEventListener("change", () => navigate(el("province").value));
  el("more").addEventListener("click", () => { shown += 100; renderResults(); });
  el("back").addEventListener("click", () => locationState.area ? navigate(locationState.province, locationState.region, locationState.city) : locationState.city ? navigate(locationState.province, locationState.region) : navigate(locationState.region ? locationState.province : ""));
  await refresh(true);
}
start().catch(error => { el("result-count").textContent = `Catalogue load failed: ${error.message}`; console.error(error); });
