"""Build the two-city source notes, or verify them against the archived files."""
import argparse
import hashlib
import json
import re
from html import escape
from pathlib import Path

from scripts.preview_rush_hour import render as render_rush_hour

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def street_timing(release):
    traces = json.loads((PUBLIC / "data/overview" / (release + "-traces.json")).read_text())
    if "timing" not in traces:
        return ""
    rows = []
    for mode, counts in sorted(traces["timing"].items()):
        shown = counts.get("shown", 0) + counts.get("rerouted", 0)
        rows.append(f'<tr><td>{escape(mode)}</td><td>{shown:,}</td><td>{sum(counts.values()):,}</td></tr>')
    return ('<details id="street-timing"><summary>How fast do Stuttgart travellers move?</summary>'
            '<p>The animation follows each street segment on the simulation clock. Walking uses up to 5 km/h '
            '(3 on steps), cycling up to 20 on cycleways and 18 on ordinary streets. The driving assumptions '
            'range from 7 on living streets to 30 on residential streets, 45 on primary roads and 90 on motorways. '
            'Lower numeric OpenStreetMap speed limits take precedence. Motor trips starting at 07:00–09:00 or '
            '16:00–18:00 use 75% of the usual speed. This is an assumed weekday traffic pattern.</p>'
            '<p>When the diary allows extra time, movement slows proportionally. For motor trips whose archived '
            'path fails, a travel-time A* search tries a directed road route and allows walking time to its endpoints. '
            'Transit uses a road proxy capped at 35 km/h. Paths that still exceed the time budget or cannot be '
            'routed are omitted from the moving sample. The population and economic calculations use the full diaries.</p>'
            '<table><thead><tr><th>Mode</th><th>Animated trips</th><th>Archived sample trips with positive duration</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></details>')


def vancouver_street_timing(release):
    run = json.loads((PUBLIC / "data/runs" / (release + ".json")).read_text())
    root = PUBLIC / "data/vancouver"
    if run["coverage"] == "region":
        root /= "region"
    profile_path = root / "drive-profile" / (run["streets"] + ".json")
    profile = json.loads(profile_path.read_text())
    if profile["streets"] != run["streets"]:
        raise ValueError("Vancouver speed profile belongs to a different road graph")
    coverage = profile["coverage"]
    total = coverage["posted"] + coverage["byClass"]
    return ('<details id="vancouver-street-timing"><summary>How does Vancouver choose a driving route?</summary>'
            '<p>A* minimizes estimated time along directed streets. A numeric speed limit for the travel direction '
            'takes precedence over the general limit. Where neither is available the model uses a road-class speed. '
            f'In this run {coverage["posted"]:,} of {total:,} drivable OpenStreetMap way directions '
            f'({100 * coverage["posted"] / total:.1f}%) have numeric limits. Defaults include '
            f'{profile["defaults"]["residential"]} km/h on residential streets and '
            f'{profile["defaults"]["motorway"]} km/h on motorways.</p>'
            '<p>The regional weekday uses free-flow driving times. Extra time in a diary slot slows the animation. '
            'Separate corridor experiments apply observed time-of-day factors to particular road segments.</p>'
            f'<a href="{profile_path.relative_to(PUBLIC).as_posix()}">Directional speed profile and defaults</a></details>')


def opening_example(release, *, summary_only=False):
    overview = PUBLIC / "data/overview"
    pointer = json.loads((overview / (release + "-cases.json")).read_text())
    cases = json.loads((overview / (pointer["cases"] + ".json")).read_text())
    for index, case in enumerate(cases):
        if case.get("query") != {"shop": "3738", "hours": "full"}:
            continue
        url = f"explorer.html?city=vancouver&amp;release={release}&amp;metric=case-{index}&amp;basket=25"
        if summary_only:
            visits = len(case["visitEvents"])
            diverted = sum(origin is not None for _, origin in case["visitEvents"])
            return (f'<p>With 08:00–20:00 trading, the shop receives <strong>{visits:,} walking visits</strong>. '
                    f'{diverted:,} switch from incumbent grocers and {visits-diverted:,} become feasible with the opening. '
                    f'At CAD 25 per visit that yields CAD {visits*25:,} in modeled sales, '
                    f'including CAD {diverted*25:,} diverted from competitors.</p>')
        rows = []
        for hour in (8, 12, 17, 20):
            events = [origin for minute, origin in case["visitEvents"] if minute <= 60 * hour]
            diverted = sum(origin is not None for origin in events)
            rows.append(f'<tr><td><a href="{url}&amp;minute={hour * 60}">{hour:02}:00</a></td>'
                        f'<td>{len(events)}</td><td>{len(events) * 25:,}</td><td>{diverted * 25:,}</td></tr>')
        return ('<details id="opening-example"><summary>East Hastings sales through the day</summary>'
                '<p>Open the map at any time below. The shop opens from 08:00 to 20:00. Each modeled '
                'grocery arrival on foot spends an assumed CAD 25. When the baseline shopper would have '
                'visited another grocer, that grocer loses the same sale.</p>'
                '<table><thead><tr><th>Local time</th><th>Arrivals so far</th><th>Sales (CAD)</th>'
                '<th>Diverted sales (CAD)</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></details>')
    return ""


def model_page(key, title, content, map_url, script=""):
    navigation = []
    for name, page, label in (("shared", "weekday-sources.html", "Shared model"),
                              ("stuttgart", "stuttgart-model.html", "Stuttgart"),
                              ("vancouver", "vancouver-model.html", "Vancouver")):
        selected = ' aria-current="page"' if name == key else ''
        navigation.append(f'<a href="{page}"{selected}>{label}</a>')
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} · City laboratory</title>'
            '<link rel="stylesheet" href="lab/explorer.css"><link rel="stylesheet" href="lab/replay-shell.css">'
            '<link rel="stylesheet" href="lab/model-notes.css"></head><body class="replay-shell model-notes">'
            '<header class="masthead"><a class="wordmark" href="https://simm.is">simm<span>is</span></a>'
            f'<nav aria-label="Model pages">{" ".join(navigation)}</nav>'
            f'<a class="map-link" href="{map_url}">Open map</a></header>'
            f'<main><h1 id="{key}">{title}</h1>{content}</main>{script}</body></html>\n')


def render(register):
    docs = PUBLIC.parent / "doc"
    pages = {}
    redirects = {}
    for run in register["runs"]:
        city, release = run["city"], run["release"]
        filename = city + "-model.html"
        page = f'explorer.html?city={city}&amp;release={release}'
        content = (docs / "explorer" / (city + ".html")).read_text()
        manifest = json.loads((PUBLIC / "data/runs" / (release + ".json")).read_text())
        def populate(text):
            return (text.replace("{{RESIDENTS}}", f'{manifest["population"]:,}')
                    .replace("{{INCOMING}}", f'{manifest["inbound"]:,}')
                    .replace("{{RELEASE}}", release))
        content = populate(content)
        if city == "stuttgart":
            model = (docs / "model.md").read_text()
            start = model.index("<figure")
            figure = model[start:model.index("</figure>", start) + len("</figure>")]
            content = content.replace("{{STUTTGART_FIGURE}}", figure)
            content += street_timing(release)
        else:
            diagram = populate((docs / "explorer/vancouver-pipeline.html").read_text())
            content = content.replace("{{PIPELINE}}", diagram)
            methods = populate((docs / "explorer/vancouver-methods.html").read_text())
            methods = methods.replace("{{PIPELINE}}", diagram).replace("{{RESULT}}", opening_example(release, summary_only=True))
            pages["vancouver-methods.html"] = model_page(city, "The Vancouver weekday model", methods, page)
            content += opening_example(release) + vancouver_street_timing(release)
        if run.get("rushHourAudit"):
            content += render_rush_hour(PUBLIC, release)
        entries = []
        for key in run["sources"]:
            source = register["sources"][key]
            entries.append(f'<li><a href="{escape(source["url"])}">{escape(source["title"])}</a>'
                           f'<p>{escape(source["role"])} · {escape(source["locator"])}</p></li>')
        content += (f'<h2 id="{release}">Sources for this weekday</h2><p>{escape(run["limitation"])}</p>'
                    f'<a href="{page}">Explore this run</a> · '
                    f'<a href="data/runs/{release}.json">Run manifest</a> · '
                    '<a href="sources/weekday.json">Source records and checksums</a>'
                    f'<ul class="sources">{"".join(entries)}</ul>')
        pages[filename] = model_page(city, city.title() + " weekday model", content, page)
        # Preserve old evidence bookmarks, including specific validation tables.
        for anchor in re.findall(r'<(?:h[1-6]|details) id="([^"]+)"', pages[filename]):
            redirects[anchor] = filename
    redirect = ('<script>const pages=' + json.dumps(redirects) + ';const id=location.hash.slice(1);'
                'if(Object.hasOwn(pages,id))location.replace(pages[id]+location.search+location.hash);</script>')
    pages["weekday-sources.html"] = model_page("shared", "The shared city simulator",
                                               (docs / "explorer/shared.html").read_text(), "explorer.html", redirect)
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the published page and run references")
    parser.add_argument("--archive", type=Path, help="Also verify the source files in this city archive")
    args = parser.parse_args()
    register = json.loads((PUBLIC / "sources/weekday.json").read_text())
    for run in register["runs"]:
        record = json.loads((PUBLIC / "data/runs" / (run["release"] + ".json")).read_text())
        if any(run[key] != record[key] for key in ("city", "release")):
            raise ValueError(f"Run identity mismatch for {run['release']}")
    for source in register["sources"].values():
        for name, expected in source.get("repositoryFiles", {}).items():
            if hashlib.sha256((PUBLIC.parent / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Repository source file changed: {name}")
    if args.archive:
        for source in register["sources"].values():
            for name, expected in source["files"].items():
                with (args.archive / name).open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        raise ValueError(f"Source file changed: {name}")
    for filename, content in render(register).items():
        page = PUBLIC / filename
        if args.check:
            if page.read_text() != content:
                raise ValueError(f"Regenerate {filename} with python -m scripts.preview_sources")
        else:
            page.write_text(content)


if __name__ == "__main__":
    main()
