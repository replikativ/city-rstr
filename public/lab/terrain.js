const sourceId = "ground-elevation";
const attribution = '<a href="https://open.canada.ca/data/en/dataset/0fe65119-e96e-4a57-8bfe-9d9245fba06b">Natural Resources Canada · Elevation</a>';

export async function attachTerrain(map, button, root, json) {
  if (typeof map.setTerrain !== "function") return;
  const {version} = await json(root + "current.json");
  if (!/^[a-f0-9]{20}$/.test(version)) throw Error("Invalid terrain release.");
  const directory = new URL(root + version + "/", document.baseURI).href;
  const {bounds, tileSize, encoding, minzoom, maxzoom} = await json(directory + "manifest.json");
  const preference = new URL(location.href).searchParams.get("terrain");
  let override = preference === "on" ? true : preference === "off" ? false : null;

  function sync() {
    const enabled = override ?? (map.getPitch() >= 25);
    if (enabled !== (map.getTerrain()?.source === sourceId)) {
      if (enabled && !map.getSource(sourceId)) {
        map.addSource(sourceId, {type:"raster-dem", tiles:[directory + "{z}/{x}/{y}.png"],
          bounds, tileSize, encoding, minzoom, maxzoom, attribution});
      }
      map.setTerrain(enabled ? {source:sourceId, exaggeration:1} : null);
    }
    button.setAttribute("aria-pressed", String(enabled));
  }

  sync();
  map.on("pitchend", sync);
  button.onclick = () => {
    override = map.getTerrain()?.source !== sourceId;
    const url = new URL(location.href);
    url.searchParams.set("terrain", override ? "on" : "off");
    history.replaceState(null, "", url);
    sync();
  };
  button.hidden = false;
}
