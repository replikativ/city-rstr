from types import SimpleNamespace

import numpy as np

from scripts.vancouver_outbound_transit import Bookings
from scripts.vancouver_transit_load import BusSpaces
from scripts.vancouver_transit_reach import INF, Reach
from scripts.vancouver_transit_trace import JourneyTrace
from scripts.vancouver_transit_transfers import Footpath


def service():
    return SimpleNamespace(
        platforms={s:i for i,s in enumerate("ABXYZC")},
        patterns=[(line,[],[0],np.asarray([[dep,dep,arr,arr]]))
                  for line,dep,arr in (("1",600,780),("2",930,1110),("3",1240,1440))],
        mapped=[True]*3, pattern_platforms=[("A","B"),("X","Y"),("Z","C")],
        access_rules=[[1,2]]*3)


def test_reach_respects_asymmetric_transfers_and_walk_margins():
    access = {0:{0:30},1:{5:45},2:{4:0}}
    paths = {"X":{"B":Footpath(30,120,[])},"Z":{"Y":Footpath(10,100,[])}}
    reach = Reach(service(),access,paths,60)
    # Last arrival is 24:00 plus 45 seconds. The latest doorstep
    # departure is 10:00 minus the first walk and boarding margin.
    dest = reach.destinations([1,2])
    assert reach.query(0,8,17,False,dest).tolist() == [1485,INF]
    assert reach.query(0,8,17,False,dest,rides=2).tolist() == [INF,INF]
    assert reach.query(1,8,17,True,reach.destinations([0])).tolist() == [-510]
    assert reach.query(1,8,16,True,reach.destinations([0])).tolist() == [INF]
    assert reach.query(0,9,16,False,dest).tolist() == [INF,INF]


def test_complete_shift_reservations_are_atomic():
    booking = Bookings.__new__(Bookings)
    booking.spaces = BusSpaces({"r":1})
    legs = [[10,20,0,False],[90,20,0,True]]
    outward, back = ["r",1,0,2,10,10],["r",2,0,1,10,10]

    def unavailable_return(start,dur,a,b,available=None):
        return outward if a==0 else None

    booking.itinerary = unavailable_return
    assert booking.circuit("DA",3,legs,5) is None
    assert not booking.spaces.loads
    booking.itinerary = lambda start,dur,a,b,available=None: outward if a==0 else back
    assert len(booking.circuit("DA",3,legs,5)) == 2
    assert not booking.spaces.fits(outward)
    assert not booking.spaces.fits(back)


def test_trace_recovers_three_vehicles_and_checks_each_segment():
    access = {0: {0: 30}, 1: {5: 45}}
    paths = {"X": {"B": Footpath(30, 120, [])}, "Z": {"Y": Footpath(10, 100, [])}}
    trace = JourneyTrace(service(), access, paths, 60)
    assert trace.journey(8, 25, 0, 1) == (
        8, 1485, ["1", 0, 0, 1, 30, 45, ["2", 0, 0, 1, 30, 120, [], ["3", 0, 0, 1, 10, 100, []]]])
    assert trace.journey(9, 25, 0, 1) is None
    assert trace.journey(8, 24, 0, 1) is None
    assert not trace.fits(8, 24, 0, 1)
    assert trace.fits(8, 25, 0, 1)
    assert trace.journey(8, 25, 0, 1, lambda route, *_: route != "2") is None


def test_through_rider_can_pass_a_stop_with_no_boarding_or_alighting():
    trip = SimpleNamespace(platforms={"A":0,"B":1,"C":2},mapped=[True],
                           patterns=[("1",[],[],np.asarray([[600,600,700,700,800,800]]))],
                           pattern_platforms=[("A","B","C")],access_rules=[[1,0,2]])
    reach = Reach(trip,{0:{0:0},1:{1:0},2:{2:0}}, {}, 60)
    assert reach.query(0,8,10,False,reach.destinations([1,2])).tolist() == [INF,800]
    assert reach.query(2,8,10,True,reach.destinations([0,1])).tolist() == [-540,INF]
