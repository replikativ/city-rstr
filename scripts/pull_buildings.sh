#!/usr/bin/env bash
# Building footprints for one city, tiled. A tile that fails costs one tile.
#   scripts/pull_buildings.sh stuttgart 48.69 9.038 48.87 9.315 4
set -u
CITY=$1; S=$2; W=$3; N=$4; E=$5; TILES=${6:-4}
OUT=data/raw/osm-buildings
mkdir -p $OUT
EP=${OVERPASS:-https://overpass-api.de/api/interpreter}
python3 - "$CITY" "$S" "$W" "$N" "$E" "$TILES" <<'PY' > /tmp/tiles.$$ 
import sys
city,s,w,n,e,t=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4]),float(sys.argv[5]),int(sys.argv[6])
for i in range(t):
    for j in range(t):
        s0=s+(n-s)*i/t; n0=s+(n-s)*(i+1)/t
        w0=w+(e-w)*j/t; e0=w+(e-w)*(j+1)/t
        print(f"{city}_{i}_{j} {s0:.5f} {w0:.5f} {n0:.5f} {e0:.5f}")
PY
while read -r name s0 w0 n0 e0; do
  f=$OUT/$name.json
  if [ -s "$f" ] && [ "$(stat -c%s "$f")" -gt 2000 ]; then echo "skip $name"; continue; fi
  Q="[out:json][timeout:300];way[\"building\"]($s0,$w0,$n0,$e0);out geom;"
  for attempt in 1 2 3; do
    curl -s --max-time 600 -A "city-sim/0.1 (research; contact via repo)" \
         --data-urlencode "data=$Q" "$EP" -o "$f"
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
    if [ "$sz" -gt 2000 ] && head -c 1 "$f" | grep -q '{'; then
      echo "ok   $name $sz bytes"; break
    fi
    echo "retry $name (attempt $attempt, $sz bytes)"; sleep 20
  done
  sleep 4
done < /tmp/tiles.$$
rm -f /tmp/tiles.$$
echo "done: $(ls -1 $OUT/${CITY}_*.json 2>/dev/null | wc -l) tiles, $(du -sh $OUT | cut -f1)"
