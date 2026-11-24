export function rideTiming(row,data,waitAtDestination=false){
  const [,,start,duration,,,,trip,board,alight,access,egress]=row;
  const ride=data.rides[trip],pat=data.patterns[ride[0]];
  const boardAt=ride[1]+ride[2][2*board+1],alightAt=ride[1]+ride[2][2*alight];
  return {ride,pat,boardAt,alightAt,from:data.stations[pat.stops[board]],to:data.stations[pat.stops[alight]],
    accessStart:start*60,access,egressStart:waitAtDestination?alightAt:(start+duration)*60-egress,egress};
}

export function onwardRide(row){
  const onward=row[12];
  if(!onward)return null;
  const next=[...row.slice(0,6),...onward.slice(0,4),0,row[11]];
  if(onward[7])next.push(onward[7]);
  return next;
}
