// Necessary timing bounds for a walking leg with fixed endpoints and a maximum pace.
export function possibleHours(origin, destination, start, duration, speed, limit, radius, hours){
  if(origin<=radius||destination<=radius)return [];
  const before=origin-radius,after=destination-radius;
  if(before+after>limit+1e-7)return [];
  const earliest=start+before/speed,latest=start+duration-after/speed;
  if(earliest>latest+1e-7)return [];
  return hours.filter(hour=>earliest<hour+60+1e-7&&hour<=latest+1e-7);
}
