"""Render the release's hourly validation records on its evidence page."""
from html import escape
import json


def table(headers, rows):
    head = ''.join(f'<th scope="col">{escape(h)}</th>' for h in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{v:,}</td>' if isinstance(v, int)
                                    else f'<td>{escape(str(v))}</td>' for v in row) + '</tr>'
                   for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def bridge_fit(records):
    """Compare equal-weight two-hour windows at each physical counter."""
    rows = []
    scores = []
    hour_scores = []
    losses = [0, 0]
    count = closer = tied = 0
    for corridor, key in (("False Creek", "roads"), ("Burrard Inlet", "inlet")):
        record = records[key]
        if (record["fittedDay"] != records["demand"]["workplaceSensitivity"]["day"]
                or record["workplaceReport"] != records["demand"]["workplaces"]["report"]
                or record["routing"] != records["roads"]["routing"]):
            raise ValueError("Bridge and demand comparisons must use the same workplace fit and road speeds")
        hour_errors = [0, 0]
        hours = 0
        errors = [0, 0]
        n = wins = ties = 0
        for site in record["sites"]:
            for i, counter in enumerate(site["counters"]):
                if len(counter["counts"]) != 24:
                    raise ValueError("Expected a full day of hourly bridge counts")
                hourly = [(resident + incoming, fitted + incoming, observed)
                          for resident, fitted, observed, incoming in zip(
                              site["resident"][i], site["fittedResident"][i], counter["counts"],
                              site["incoming"][i], strict=True)]
                for base, fit, observed in hourly:
                    hour_errors[0] += abs(base - observed)
                    hour_errors[1] += abs(fit - observed)
                    hours += 1
                for start, window in [(7, "07–09"), (16, "16–18")]:
                    base, fit, observed = map(sum, zip(*hourly[start:start+2], strict=True))
                    rows.append([site["name"] + " " + counter["direction"],
                                 f'{counter["month"]} {counter["year"]}', window, base, fit, observed])
                    before, after = abs(base - observed), abs(fit - observed)
                    errors[0] += before
                    errors[1] += after
                    wins += after < before
                    ties += after == before
                    n += 1
        hour_scores.append([corridor, hours, *[f"{e/hours:,.0f}" for e in hour_errors]])
        scores.append([corridor, n, *[f"{e/n:,.0f}" for e in errors], wins, ties])
        count += n
        closer += wins
        tied += ties
        for j, error in enumerate(errors):
            losses[j] += error
    scores.append(["All counters", count, *[f"{e/count:,.0f}" for e in losses], closer, tied])
    return ('<h4 id="workplace-bridge-check">Do census-based workplaces improve bridge traffic?</h4>'
            '<p>Each comparison covers one bridge direction from 07:00 to 09:00 or 16:00 to 18:00. '
            'Both assignments use the same resident driver diaries, external commuters and free-flow road speeds. '
            'Observed counts include all vehicles, including commercial traffic. Each direction and window receives '
            'equal weight. Mean absolute error is the average gap in vehicles per two-hour window.</p>'
            + table(["Bridges", "Windows", "Baseline mean error", "Workplace fit mean error", "Fit closer", "Tied"], scores)
            + '<p>The explorer uses the baseline workplace assignment. The census fit improves the municipal '
            'workplace shares and lowers the average peak error across the five bridges. Lions Gate accounts for most '
            'of the improvement. Average peak error rises at Ironworkers and across False Creek. The fitted day '
            'remains available here as a sensitivity comparison.</p>'
            + '<details><summary>Counts by bridge, direction and observation month</summary>'
            + table(["Counter", "Observation", "Hours", "Baseline", "Workplace fit", "Observed"], rows)
            + '<p>Across all 24 hours, each direction and hour receives equal weight.</p>'
            + table(["Bridges", "Direction-hours", "Baseline mean hourly error", "Fit mean hourly error"], hour_scores)
            + '<p>Lions Gate and Ironworkers use the published counter direction labels. '
            f'<a href="{escape(records["inlet"]["sites"][-1]["source"])}">Ironworkers vehicle counts</a>.</p></details>')


def render(public, release):
    base = f'data/vancouver/downtown-audit/{release}-'
    records = {}
    links = []
    for key in ('demand', 'roads', 'inlet', 'rail', 'bicycles'):
        url = base + key + '.json'
        record = json.loads((public / url).read_text())
        if record['release'] != release:
            raise ValueError(f'Audit release mismatch in {url}')
        records[key] = record
        links.append(f'<a href="{url}">{key.title()} hourly data</a>')

    demand = records['demand']
    windows = [(7, 0), (7, 1), (16, 0), (16, 1)]

    def trips(groups, modes):
        return [sum(demand[g][h][d][m] for g in groups for h in (start, start+1) for m in modes)
                for start, d in windows]

    groups = ['resident', 'incoming']
    modes = range(len(demand['modes']))
    headers = ['Modeled trips', '07–09 in', '07–09 out', '16–18 in', '16–18 out']
    rows = [[name, *trips([g], modes)] for name, g in zip(['Residents', 'External workers'], groups)]
    rows.append(['Combined', *trips(groups, modes)])
    work_rows = []
    for d, label in enumerate(["Arrival at a Downtown job", "Departure from a Downtown job"]):
        work_rows.append([label, *[sum(demand["residentWorkplaceEnds"][h][d] for h in (start, start+1))
                                   for start in (7, 16)]])
    mode_rows = [[name, *trips(groups, [i])] for i, name in enumerate(demand['modes'])]

    morning = demand["morningDepartures"]
    destination_rows = []
    for i, area in enumerate(demand["areas"]):
        trips_to_area = sum(v[1][i] for v in morning.values())
        if trips_to_area:
            destination_rows.append([area, trips_to_area, morning["job"][1][i]])
    destination_rows.sort(key=lambda row: -row[1])
    total_jobs = sum(row[2] for row in destination_rows)
    workplace = demand["workplaces"]
    def north_share(key):
        vancouver = workplace[key][0]
        return f"{100 * sum(vancouver[1:]) / sum(vancouver):.1f}%"
    variant = demand["workplaceSensitivity"]["counts"]
    experiment_rows = [rows[-1], ["Municipal workplace fit", *[sum(variant[h][d] for h in (start, start+1))
                                                              for start, d in windows]]]
    diagnostic = (
        '<details id="morning-destinations"><summary>Where do Downtown residents go from 07:00 to 09:00?</summary>'
        f'<p>{sum(row[1] for row in destination_rows):,} trips leave Downtown for a known destination '
        f'elsewhere by someone who lives Downtown. Of these, {total_jobs:,} end at a job.</p>'
        + table(["Destination", "Trips", "Ending at job"], destination_rows)
        + '<p>Among City of Vancouver residents with an assigned workplace in Vancouver or the three North Shore '
        f'municipalities, {north_share("modeled")} of modeled workers go to the North Shore. The 2021 Census '
        f'usual-workplace share is {north_share("observed")}. Both shares exclude UBC and workplaces beyond these '
        'four municipalities. The census describes workers across the municipality and provides no hourly Downtown target. '
        f'<a href="{escape(workplace["source"])}">Statistics Canada commuting flows</a>.</p>'
        f'<p>A sensitivity run reassigns resident workplaces using those census flows, bringing the share to '
        f'{north_share("fitted")}. The following trip counts include all purposes and hold the external cohort fixed.</p>'
        + table(headers, experiment_rows) + '</details>')
    comparisons = []

    def compare(name, unit, model, obs):
        comparisons.append([name, unit, sum(model[7:9]), sum(obs[7:9]), sum(model[16:18]), sum(obs[16:18])])

    roads = records['roads']
    for site in roads['sites']:
        for i, counter in enumerate(site['counters']):
            series = [a+b for a, b in zip(site['resident'][i], site['incoming'][i], strict=True)]
            compare(site['name'] + ' ' + counter['direction'], f"Vehicles · {counter['month']} {counter['year']}",
                    series, counter['counts'])
    rail = records['rail']
    for i, action in enumerate(['Alightings', 'Boardings']):
        compare('Six Downtown SkyTrain stations', action + ' · 2025 weekdays',
                [a[i]+b[i] for a, b in zip(rail['resident'], rail['incoming'], strict=True)],
                [h[i] for h in rail['observed']])
    bike = records['bicycles']
    site = next(s for s in bike['sites'] if s['observation']['key'] == 'powell')
    obs = site['observation']
    hours = obs['hours']
    comparisons.append([obs['name'], 'Bicycles · ' + obs['date'],
                        *[sum(series[hours.index(h)] for h in [start, start+1])
                          for start in (7, 16) for series in (site['modeled'], obs['observed'])]])
    for title, dataset in [('Road counters', roads), ('Station counts', rail), ('Bicycle counts', bike)]:
        links.append(f'<a href="{escape(dataset["source"])}">{title}</a>')
    return ('<h3 id="downtown-rush-hour">Downtown rush hour</h3>'
            '<p>Trips between Downtown and another known area, including external worker origins. Local time, all purposes. '
            'Arrivals and departures use the published weekday’s rounded diary times. '
            'The map spreads events within each five-minute diary bin.</p>'
            + table(headers, rows)
            + '<details><summary>Trip ends by mode</summary>' + table(headers, mode_rows) + '</details>'
            + '<details><summary>Resident trips with a workplace at the Downtown end</summary>'
            + table(['Downtown trip end', '07–09', '16–18'], work_rows)
            + '<p>This subset uses the job location in the resident diary. '
            'Morning departures from Downtown homes to jobs elsewhere fall outside this subset.</p></details>'
            + diagnostic + bridge_fit(records)
            + '<h4>Crossings and station activity</h4><p>Each row compares the same site, direction and two-hour window. '
            'Bridge estimates route resident and incoming commuter drivers. Counters include all vehicles. '
            'The weekday timetable contains no SkyTrain lines. The rail estimates use a supplemental timetable '
            'for the same service date and match direct rides only. The Powell cycling comparison covers routed '
            'resident trips and one observed day on the east approach.</p>'
            + table(['Site', 'Measurement', '07–09 model', '07–09 observed', '16–18 model', '16–18 observed'], comparisons)
            + '<p>' + ' · '.join(links) + '</p>')
