# Imagery for VLM-based estimation of business and building properties

## Tier 1 — free, permissive
### Street-level
- **Mapillary** Graph API v4 (`graph.mapillary.com/images?bbox=…&fields=thumb_2048_url,computed_geometry,compass_angle,is_pano,captured_at,sequence`): bbox < 0.01 deg², tile the city; rate limits generous. Images CC BY-SA 4.0; terms allow commercial algorithm/dataset development; logo + link required on displayed images; no un-blurring; use the API (their "data mining" clause). **Needs a free client token.** Vancouver likely dense; Stuttgart being refreshed 2026.
- **Panoramax** (`api.panoramax.xyz/api/search?bbox=…`, STAC, no key): Stuttgart 50,760 pictures / 220 sequences / 87% 360° (2024–25); Vancouver 35 pictures. CC BY-SA 4.0.
- **Wikimedia Commons** geosearch (`list=geosearch&gsnamespace=6`): landmark-biased; per-file free licences. User-Agent required.
- KartaView: moribund, skip.

### Aerial / lidar / 3D — Vancouver (OGL Vancouver/BC/Metro/Canada; commercial + ML fine)
- City of Vancouver orthophoto 2022 (7.5 cm; also 2015…2006): 470 MrSID/ECW zips (`webtransfer.vancouver.ca/opendata/2022sid/…`).
- Metro Vancouver ortho 2025 (7.5 cm RGBA), 6.47 GB MrSID for Vancouver area (ArcGIS Hub).
- CoV LiDAR 2022: 49 pts/m², 8 classes incl. buildings, 181 LAS zips; LidarBC 2025 (8 pts/m² LAZ + 1 m DSM).
- Building footprints 2009 (with height AGL, roof type) / 2015 (2D); NRCan HRDEM 1 m DSM/DTM.
- Overture buildings: 168k in bbox, 62% with height (CoV source 100%).
- No open CityGML; BC provincial orthos are pay-per-use.

### Aerial / lidar / 3D — Stuttgart (LGL BW dl-de/by-2.0; commercial + ML + derived works fine)
- LGL DOP20 RGBI TrueDOP (20 cm, tiles dated Mar 2026): `opengeodata.lgl-bw.de/data/dop20/dop20rgbi_32_<E>_<N>_2_bw.zip`; WMS/WMTS `owsproxy.lgl-bw.de`.
- LGL LoD2 CityGML (roof forms, ~1 m height): `/data/lod2/LoD2_32_<E>_<N>_2_bw.zip`; LoD1; DGM1/DOM1/nDOM1; ALS_3 point cloud; Hausumringe `/data/hu/hu_bw.zip` (552 MB).
- Stadt Stuttgart Luftbilder 2025/2023/2021… (20 cm) WMS `geoserver.stuttgart.de/geoserver/Base/wms`, layer `Base:A62_Luftbild_2025_EPSG25832` (licence note: portal CC BY vs WMS fees text).
- BKG basemap.de 3D Gebäude LoD2-DE 3D Tiles (CC BY 4.0).
- Overture buildings: 215k in bbox, 32% with height (no LoD2 in Overture).

### Place metadata
Overture Places: Vancouver 43,950 places (38.9k websites, 31.8k socials); Stuttgart 36,877 (33.4k websites). OSM shop+amenity: Vancouver 25.6k, Stuttgart 45.6k (with mapillary/panoramax/wikimedia_commons image tags in Stuttgart).

## Tier 2 — free but restrictive
Flickr (non-commercial key, ~24 h caching), Yelp Places API (no storage >24 h, no ML), OSM Buildings / Cesium ion (non-commercial), Apple Look Around (no API; reverse-engineered access violates ToS).

## Tier 3 — contractually unusable for ML
Google Street View Static / Places / Photorealistic 3D Tiles (Maps Platform Terms §3.2.3: no bulk, no caching, no ML training or geodata extraction); Foursquare Places API (7.5.8: no POI dataset/ML development); Tripadvisor Terra (excludes AI/ML); Bing Streetside (dead); Instagram/Facebook (no automated collection).

Business websites as photo fallback: Germany §44b UrhG permits commercial TDM absent machine-readable opt-out (§60d research); Canada only fair dealing for research. Honour robots.txt.

## Prior work
Gebru et al. PNAS 2017 (Street View cars → demographics); Naik et al. Streetscore / PNAS 2017; Movshovitz-Attias CVPR 2015 (storefront classification); Yu et al. arXiv:1512.05430 (storefront detection); Law, Paige & Russell ACM TIST 2019 (house prices from street + satellite); Li et al. arXiv:2307.02574 (building height from Mapillary + OSM); Sun et al. arXiv:2505.18021 (floor counts); Yang et al. arXiv:2408.12821 (foundation models on street view for building function/age/height); Liang et al. OpenFACADES arXiv:2504.02866 (Mapillary + OSM + open VLMs, 7 cities — closest template); Shabrina et al. arXiv:2607.14756 (VLM vs expert agreement); Zhuo et al. arXiv:2604.19798 (storefront economics, closures); Han et al. arXiv:2609.02012 (GeoStore benchmark).

## Recommended stack
Vancouver: Mapillary (street) + Commons; Metro 2025 / CoV 2022 ortho + LiDAR 2022 for heights/storeys; Overture + OSM for places and website links.
Stuttgart: Panoramax + Mapillary (street); LGL DOP20 + LoD2 + nDOM1 + Hausumringe; Overture + OSM.
Keep OSM-derived attributes as a separate ID-keyed layer (ODbL share-alike). Do not use Google, Foursquare, Tripadvisor, or Apple imagery.

## Signups
Mapillary developer token (free, the one that matters); optional Copernicus account (Sentinel-2), Flickr non-commercial key (exploration only), Cesium ion (viewer only). Consider emailing Mapillary for written approval of city-scale pulls.
