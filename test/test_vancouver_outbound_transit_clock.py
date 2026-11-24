import pytest

from scripts.vancouver_outbound_transit_clock import departure_band, departure_check, trip_clock


def test_retiming_uses_the_same_vehicles_and_preserves_boarding_margin():
    data = {"bus":{"rides":[[0,800,[0,0,160,160],""]]},
            "train":{"rides":[[0,1210,[0,0,300,300],""]]}}
    row = ["DA",4,6,24,0,1,"bus",0,0,1,44,22,["train",0,0,1,70,250,[]]]
    leave,arrival,components = trip_clock(row,data,180)
    assert (leave,arrival)==(9,1532)
    assert components==(136,396,180,460)
    assert sum(components)==arrival-row[2]*60
    assert leave*60+row[10]+180<=800<(leave+1)*60+row[10]+180

    row[3]=18
    with pytest.raises(ValueError, match="original travel window"):
        trip_clock(row,data,180)


def test_vancouver_reference_wraps_noon_through_the_next_morning():
    assert [departure_band(t) for t in (240,299,300,360,420,480,540,720,1500)] == [5,5,0,1,2,3,4,5,5]
    check = departure_check([(0,480,540),(1,300,360),(0,245,299)],{0:[0,0,0,1,1,2]})
    assert check["compared"]==2
    assert check["recorded"]==[0,0,0,1,0,1]
    assert check["timed"]==[0,0,0,0,1,1]
    assert check["expected"]==[0,0,0,.5,.5,1]
