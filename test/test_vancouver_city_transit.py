from pathlib import Path
import math
import tempfile
import unittest

from scripts.artifacts import write_json
from scripts.vancouver_campus import access_routes, WALK_METRES_PER_SECOND
from scripts.vancouver_city_transit import DirectService, transit_parts
from scripts.vancouver_commuter_coverage import carry_bookings, passenger_walks
from scripts.vancouver_downtown import STATIONS, station_counts
from scripts.vancouver_transit_transfers import Footpath, OneTransfer, TwoTransfers, walk_transfers
from scripts.vancouver_transit_load import BusSpaces, book_connections, book_direct, bus_load_evidence, observed_spare_capacity, ride_legs


class DirectServiceTest(unittest.TestCase):
    def test_connections_recover_a_denied_direct_booking_without_consuming_partial_space(self):
        spaces = BusSpaces(dict.fromkeys(["direct", "first", "other-first", "second"], 1))
        earlier = ["da", 0, 0, 10, 0, 1]
        later = ["da", 1, 0, 20, 0, 1]
        direct = ["direct", 0, 0, 1, 0, 0]
        booked, denied, rerouted = book_direct([[*later, *direct], [*earlier, *direct]], spaces, lambda *args: None)
        self.assertEqual(booked, [[*earlier, *direct]])
        self.assertEqual(denied, [later])
        self.assertEqual(rerouted, 0)

        class Planner:
            def latest(self, end, origin, destination, available=None, *, earliest_minute):
                route = "first" if destination == 1 else "other-first"
                if available is None or available("second", 0, 0, 1):
                    return [earliest_minute, end, [route, 0, 0, 1, 0, 0, ["second", 0, 0, 1, 0, 0, []]]]

        other = ["da", 2, 0, 30, 0, 2]
        connections, missing, capacity, recovered = book_connections([other, later], Planner(), spaces, {tuple(later[:3])})
        self.assertEqual([row[:6] for row in connections], [later])
        self.assertEqual((missing, capacity, recovered), (0, 1, 1))
        self.assertTrue(spaces.available("other-first", 0, 0, 1))

    def test_two_transfers_respect_walks_clock_and_all_three_vehicle_reservations(self):
        names = ["first", "middle", "last"]
        positions = [[0, 0], [100, 0], [140, 0], [300, 0], [340, 0], [450, 0]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_json(path / "transit.json", {"routes": [{"id": name} for name in names]})
            for i, (name, clock) in enumerate(zip(names, (600, 740, 900), strict=True)):
                write_json(path / f"{name}.json", dict(stations=positions[2*i:2*i+2],
                           stopIds=[str(2*i), str(2*i+1)], patterns=[dict(stops=[0, 1], access=[1, 2], mapped=True)],
                           rides=[[0, clock, [0, 0, 100, 100], ""]]))
            service = DirectService(path)
        links = {"2": {"1": Footpath(30, 40, positions[1:3])}, "4": {"3": Footpath(30, 45, positions[3:5])}}
        one = OneTransfer(service, {0: {0: 10}, 1: {5: 20}}, links, margin=10)
        self.assertIsNone(one.latest(1020, 0, 1))
        search = TwoTransfers(one)
        self.assertIsNone(search.journey(581, 1020, 0, 1))
        self.assertIsNone(search.journey(580, 1019, 0, 1))
        choice = search.journey(580, 1020, 0, 1)
        self.assertEqual(list(ride_legs(choice)), [[name, 0, 0, 1] for name in names])
        self.assertEqual(choice[6][4:7], [30, 40, positions[1:3]])
        self.assertEqual(choice[6][7][4:7], [30, 45, positions[3:5]])
        spaces = BusSpaces(dict.fromkeys(names, 1))
        spaces.reserve(choice)
        self.assertFalse(spaces.available("last", 0, 0, 1))
        self.assertIsNone(search.journey(580, 1020, 0, 1, spaces.available))

    def test_expanded_service_translates_bookings_to_the_same_run_after_reordering(self):
        manifest = dict(date="2026-09-15", feed="local", feedDigest="same", routes=[dict(id="1", trips=2)])
        old = dict(stations=[[0, 0, "Home"], [120, 0, "Work"]], stopIds=["a", "b"],
                   patterns=[dict(stops=[0, 1], access=[1, 2], mapped=True, line=[[0, 0], [120, 0]], dist=[0, 120])],
                   rides=[[0, 600, [0, 0, 120, 120], "Work"], [0, 600, [0, 0, 120, 120], "Work"]])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base, expanded = root / "base", root / "expanded"
            for path in (base, expanded):
                path.mkdir()
                write_json(path / "transit.json", manifest)
            write_json(base / "1.json", old)
            new = dict(old, stations=old["stations"][::-1], stopIds=old["stopIds"][::-1],
                       patterns=[dict(old["patterns"][0], stops=[1, 0])],
                       rides=[[0, 580, [0, 0, 120, 120], "Work"], *old["rides"]])
            write_json(expanded / "1.json", new)
            self.assertEqual(carry_bookings(base, expanded, [("1", 1, 0, 1), ("1", 0, 0, 1)]),
                             [("1", 2, 0, 1), ("1", 1, 0, 1)])
            write_json(expanded / "1.json", dict(new, rides=new["rides"][:-1]))
            with self.assertRaises(ValueError):
                carry_bookings(base, expanded, [("1", 1, 0, 1)])

    def test_expanded_journey_replays_home_to_platform_walk_in_the_right_direction(self):
        from types import SimpleNamespace

        service = SimpleNamespace(stations=[(0, 0), (300, 0)], ride_platforms={"1": [(0, 1)]})
        nodes = [[0, 0], [20, 20], [40, 0], [300, 0], [310, 0]]
        network = dict(nodes=nodes, ways=[[1, 0, [0, 1, 2]], [1, 0, [3, 4]]])
        correct = math.ceil(2 * math.dist(nodes[0], nodes[1]) / WALK_METRES_PER_SECOND)
        trip = ["group", 0, 480, 20, 0, 1, "1", 0, 0, 1, correct, 8]
        walks = passenger_walks(network, service, [nodes[2], nodes[4]], [trip])
        self.assertEqual(walks["group"], [[0, 480, nodes[2::-1], nodes[3:]]])

    def test_skytrain_interchange_counts_actual_fare_gate_crossings(self):
        routes = [{"id": route, "name": name, "type": 1} for route, name in
                  [("expo", "Expo Line"), ("millennium", "Millennium Line"), ("canada", "Canada Line")]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            observations = path / "stations.csv"
            observations.write_text(
                "StationName,CalendarYear,DayType,Hour,Average_Daily_Station_Alightings,Average_Daily_Station_Boardings\n"
                + "".join(f"{station},2025,MF,{hour}:00 {'AM' if hour < 12 else 'PM'} to "
                          f"{(hour + 1) % 24}:00 {'AM' if (hour + 1) % 24 < 12 else 'PM'},1,1\n"
                          for station in sorted(STATIONS) for hour in range(24)))
            for route, names in [
                ("expo", ["Away", "Waterfront Station @ Expo"]),
                ("millennium", ["Waterfront Station @ Millennium", "Away"]),
                ("canada", ["Waterfront Station @ Canada", "Away"]),
            ]:
                write_json(path / f"{route}.json", {"stations": [[i, 0, name] for i, name in enumerate(names)],
                           "patterns": [{"stops": [0, 1]}],
                           "rides": [[0, 8 * 3600, [0, 0, 240, 240], ""]] if route == "expo" else
                                    [[0, 8 * 3600 + 600, [0, 0, 240, 240], ""]]})
            first = ["DA", 2, 477, 25, 0, 1, "expo", 0, 0, 1, 0, 0]
            trips = [first + [[route, 0, 0, 1]] for route in ("millennium", "canada")]
            result = station_counts(observations, path, {"routes": routes}, {"DA": trips})
            by_origin = station_counts(observations, path, {"routes": routes},
                                       {"first": trips[:1], "second": trips[1:]}, by_origin=True)
        self.assertEqual(result["matched"][8], [1, 1])
        self.assertEqual(sum(sum(hour) for hour in result["matched"]), 2)
        self.assertEqual(by_origin["matched"], result["matched"])
        self.assertEqual(by_origin["byOrigin"]["first"][8], [0, 0])
        self.assertEqual(by_origin["byOrigin"]["second"][8], [1, 1])

    def test_access_time_uses_replay_node_when_two_street_entrances_are_equidistant(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            venue, stop = [1885, 3510], [1900, 3400]
            nodes = [[1866, 3456], [1859, 3459], [1750, 3440], stop]
            write_json(path / "network.json", {"nodes": nodes, "ways": [[1, 0, [0, 2, 3]], [1, 0, [1, 3]]]})
            length = sum(math.dist(a, b) for a, b in zip([venue, nodes[0], nodes[2]], [nodes[0], nodes[2], stop]))
            self.assertEqual(access_routes([venue], {0}, [stop], path)[0][0], math.ceil(length / WALK_METRES_PER_SECOND))

    def test_overtaking_boarding_rules_and_walk_window(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_json(path / "transit.json", {"routes": [{"id": "1"}]})
            write_json(path / "1.json", {
                "stations": [[0, 0], [100, 0], [200, 0], [300, 0]],
                "patterns": [{"stops": [0, 1, 2, 3], "access": [1, 2, 1, 2], "mapped": True}],
                "rides": [[0, 600, [0, 20, 120, 120, 180, 180, 240, 240], ""],
                          [0, 605, [0, 20, 95, 95, 115, 115, 130, 130], ""]]})
            service = DirectService(path)
            match = service.matcher({0: {0: 20}, 1: {1: 0}, 2: {2: 0}, 3: {3: 45}})
            self.assertEqual(match(10, 3, 0, 3), ("1", 1, 0, 3, 20, 45))
            self.assertIsNone(match(10, 2, 0, 3))
            self.assertIsNone(match(10, 5, 1, 3))
            self.assertIsNone(match(10, 5, 0, 2))
            self.assertIsNone(match(11, 5, 0, 3))
            latest = service.latest_departure({0: {0: 20}, 1: {1: 0}, 2: {2: 0}, 3: {3: 45}}, margin=180)
            self.assertEqual(latest(780, 0, 3), (7, 780, ["1", 1, 0, 3, 20, 45]))
            self.assertIsNone(latest(779, 0, 3))
            self.assertIsNone(latest(900, 1, 3))
            self.assertIsNone(latest(900, 0, 2))
            spaces = BusSpaces({"1": 1})
            spaces.reserve(["1", 1, 0, 3, 0, 0])
            alternative = service.latest_departure({0: {0: 20}, 3: {3: 45}}, 180, spaces.available)
            self.assertEqual(alternative(900, 0, 3), (7, 885, ["1", 0, 0, 3, 20, 45]))
            home_and_store = {0: {0: 20}, 3: {3: 45}}
            return_ride = service.matcher(home_and_store, boarding_margin=180, mapped_only=True,
                                          available=spaces.available, arrival_time=True)
            self.assertEqual(return_ride(7, 9, 0, 3), (885, ("1", 0, 0, 3, 20, 45)))
            self.assertIsNone(return_ride(8, 9, 0, 3))
            self.assertIsNone(return_ride(7, 7, 0, 3))
            self.assertEqual(service.ride_times(("1", 0, 0, 3, 20, 45)), (620, 840))

    def test_walk_dominant_bout_and_mixed_vehicle_modes(self):
        tpl = {"parts": [[600, 30, "walk", 0, 1], [630, 30, "car-driver", 1, 2]]}
        source = {"episodes": [[600, 20, "travel", "walk"], [620, 10, "travel", "transit"],
                               [630, 20, "travel", "car-driver"], [650, 10, "travel", "transit"]]}
        self.assertEqual(list(transit_parts(tpl, source)),
                         [(600, 30, 0, 1, True), (630, 30, 1, 2, False)])

    def test_transfer_respects_direction_physical_walk_and_feed_minimum(self):
        from types import SimpleNamespace

        service = SimpleNamespace(platforms={"a": 0, "b": 1}, stations=[(0, 0), (100, 0)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "network.json"
            write_json(path, {"nodes": [[0, 0], [50, 50], [100, 0]], "ways": [[1, 0, [0, 1, 2]]]})
            graph = walk_transfers(service, [("a", "b", 2, 310), ("b", "a", 3, 0)], path, margin=180)
        self.assertEqual(graph["b"]["a"], Footpath(107, 310, [[0, 0], [50, 50], [100, 0]]))
        self.assertNotIn("b", graph["a"])
        self.assertEqual(graph["a"]["a"].seconds, 0)

    def test_transfer_chooses_latest_first_ride_that_can_reach_second(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_json(path / "transit.json", {"routes": [{"id": "first"}, {"id": "second"}]})
            for name, coordinates, ids, schedule in [
                ("first", [[0, 0], [100, 0]], ["home", "arrival"],
                 [[0, 980, [0, 0, 120, 120], ""], [0, 1000, [0, 0, 120, 120], ""]]),
                ("second", [[150, 0], [250, 0]], ["boarding", "job"],
                 [[0, 1350, [0, 0, 150, 150], ""], [0, 1380, [0, 0, 150, 150], ""]]),
            ]:
                write_json(path / (name + ".json"), {"stations": coordinates, "stopIds": ids,
                            "patterns": [{"stops": [0, 1], "access": [1, 2], "mapped": True}], "rides": schedule})
            service = DirectService(path)
        access = {0: {service.platforms["home"]: 10}, 1: {service.platforms["job"]: 20}}
        walk = Footpath(60, 240, [[100, 0], [150, 0]])
        planner = OneTransfer(service, access, {"boarding": {"arrival": walk}}, margin=180)
        self.assertEqual(planner.latest(1520, 0, 1), (13, 1520, [
            "first", 0, 0, 1, 10, 20, ["second", 0, 0, 1, 60, 240, walk.points]]))
        self.assertIsNone(planner.latest(1519, 0, 1))
        self.assertEqual(planner.latest(1550, 0, 1)[2][6][1], 1)
        self.assertEqual(planner.latest(1520, 0, 1, earliest_minute=13), planner.latest(1520, 0, 1))
        self.assertIsNone(planner.latest(1520, 0, 1, earliest_minute=14))
        spaces = BusSpaces({"first": 1, "second": 1})
        spaces.reserve(["second", 1, 0, 1, 0, 0])
        earlier = planner.latest(1550, 0, 1, spaces.available)
        self.assertEqual(earlier[2], ["first", 0, 0, 1, 10, 20, ["second", 0, 0, 1, 60, 240, walk.points]])
        spaces.reserve(earlier[2])
        self.assertIsNone(planner.latest(1550, 0, 1, spaces.available))

    def test_a_full_second_bus_does_not_reserve_the_first_bus(self):
        spaces = BusSpaces({"a": 1, "b": 1})
        spaces.reserve(["b", 4, 1, 3, 0, 0])
        with self.assertRaises(ValueError):
            spaces.reserve(["a", 8, 0, 2, 0, 0, ["b", 4, 2, 5]])
        self.assertTrue(spaces.available("a", 8, 0, 2))
        self.assertTrue(spaces.available("b", 4, 0, 1))
        self.assertFalse(spaces.available("b", 4, 0, 2))
        self.assertTrue(spaces.available("b", 4, 3, 5))

    def test_observed_background_occupancy_reserves_the_stricter_peak(self):
        with tempfile.TemporaryDirectory() as folder:
            table = Path(folder) / "loads.csv"
            table.write_text("SeasonYear,Season,DayType,Lineno_renamed,Average_Peak_Passenger_Load\n"
                             "2025,Fall,MF,010,17.2\n2025,Fall,MF,10,4\n2025,Fall,SA,10,20\n")
            manifest = {"routes": [{"id": "a", "name": "10"}, {"id": "b", "name": "11"}]}
            profile = observed_spare_capacity(manifest, table, {"a": 20, "b": 30})
        self.assertEqual(profile, dict(observedReserve={"a": 18, "b": None}, spare={"a": 2, "b": 0}))
        spaces = BusSpaces({"a": 2}, {"b"})
        self.assertFalse(spaces.available("b", 1, 0, 2))
        spaces.reserve(["a", 0, 0, 2, 0, 0])
        spaces.reserve(["a", 0, 1, 3, 0, 0])
        self.assertFalse(spaces.available("a", 0, 1, 2))
        self.assertTrue(spaces.available("a", 0, 2, 3))

    def test_bus_peak_load_counts_transfers_and_turnover(self):
        manifest = {"routes": [{"id": "route", "name": "10", "type": 3}]}
        first = ["DA", 7, 1, 10, 0, 1, "route", 0, 0, 1, 0, 0]
        second = ["DA", 8, 1, 10, 0, 1, "train", 0, 0, 1, 0, 0, ["route", 0, 1, 2]]
        last = ["DA", 9, 1, 10, 0, 1, "route", 0, 1, 2, 0, 0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_json(path / "route.json", {"rides": [[0, 3600, [0, 0, 60, 61, 120, 120], ""]],
                                            "patterns": [{"stops": [0, 1, 2]}],
                                            "stations": [[0, 0, "A"], [1, 0, "B"], [2, 0, "C"]]})
            table = path / "peaks.csv"
            table.write_text("SeasonYear,DayType,Season,Lineno_renamed,Average_Peak_Passenger_Load,Average_Peak_Load_Factor\n"
                             "2025,MF,Fall,10,0.5,50\n"
                             "2025,MF,Summer,10,500,50\n")
            summary = bus_load_evidence(path, manifest, [first, second, last], table)
        self.assertEqual((summary["busTrips"], summary["compared"], summary["above"]), (1, 1, 1))
        self.assertEqual(summary["highest"], dict(route="10", stop="B", minute=61, riders=2, capacityProxy=1))

    def test_service_review_clock_crosses_noon_and_midnight(self):
        from scripts.vancouver_downtown import hour
        labels = ["12:00 to 1:00 AM", "8:00 to 9:00 AM", "11:00 AM to 12:00 PM",
                  "12:00 to 1:00 PM", "4:00 to 5:00 PM", "11:00 PM to 12:00 AM"]
        self.assertEqual([hour(label) for label in labels], [0, 8, 11, 12, 16, 23])
