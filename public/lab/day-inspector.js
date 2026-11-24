import {mountInspector} from "../js/replay/replay.js";

const evidenceLinks=["bridge","bridgeChoice","downtown","departures","zones","northDemand","northWorkplace","crossing",
  "cycleCheck","cycleTours","demand","service","workTransit","roadGate","personalTransit","scheduled","commute","workplaces","roadTraffic","hiredRides","dispatchRun","departureClock"];
const scenarioLinks=["marketRun","shop","shopPlay","basket","housingRun","shelterShock","voting","votingRun","votingLayout","policy","cafe",
  "outings","outingsRun","schoolRun","schools","easternOutingRun","easternOutings","recreationRun","recreation","attendanceRun","attendance","granville","granvilleRun"];

export function inspector(){
  const params=new URLSearchParams(location.search);
  const view=["bridge","bridgeChoice","personalTransit","tripTiming","shoppingClock"].some(key=>params.has(key))?"evidence":
    scenarioLinks.some(key=>params.has(key))?"scenarios":evidenceLinks.some(key=>params.has(key))?"evidence":null;
  return mountInspector(view??"map",!!view&&!params.has("street"));
}
