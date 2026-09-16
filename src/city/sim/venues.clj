(ns city.sim.venues
  "Non-commercial destinations for the day, read out of the cached OSM pulls.

   The diary carries a *location* for every episode (TUS 3300–3312). Four of
   them (home, work or school, store, restaurant) already have a place to go:
   the person's home, their workplace, and the retail and food firms. The rest
   (a park, a clinic, a gym, a church, a museum) get theirs from OSM here, as a
   *small flat table* (class, lon, lat) in the same shape the gravity tables
   consume, so an :outdoors episode takes exactly the same code path as a
   store episode.

   Two pull formats are read, because the Stuttgart districts were pulled
   differently:

   - **Overpass JSON** (`{\"elements\": [{\"tags\": …, \"lat\"/\"center\": …}]}`):
     seven of the Stuttgart Stadtbezirke, and any bbox pull made with
     `city.intake.overpass/acquire-bbox!`;
   - **ohsome GeoJSON** (`{\"features\": [{\"geometry\": {\"coordinates\": …},
     \"properties\": {tags…}}]}`) — the sixteen Stuttgart Stadtbezirke Overpass
     would not serve (`city.load.stuttgart`). Its properties *are* the tags
     (plus `@osmId`, `@validFrom`, `@validTo`), so the same classifier reads
     both.

   Nothing here is downloaded: only the receipts already in the cache are read,
   and only those whose pull covers the world's bbox. Every file is streamed
   one element at a time (`city.sim.network/stream-array!`) — a 14 MB ohsome
   pull held as one Clojure value is a hundred megabytes of heap."
  (:require [city.intake.core :as acq]
            [city.sim.network :as net]
            [clojure.string :as str]))

(def class-rules
  "[diary-class tag-key #{tag-values}] — the first rule an element matches wins,
   so a `healthcare=dentist` with `amenity=dentist` is one clinic, not two.

   The classes are the diary's own vocabulary:
   :school     :work-or-school for a person with no workplace (a student)
   :clinic     :clinic
   :outdoors   :outdoors
   :sports     :sports-venue
   :culture    :culture
   :worship    :worship"
  [[:school   :amenity  #{"school" "kindergarten" "college" "university" "music_school" "childcare"}]
   [:clinic   :amenity  #{"clinic" "doctors" "dentist" "hospital"}]
   [:clinic   :healthcare #{"clinic" "doctor" "dentist" "physiotherapist" "alternative" "centre" "midwife" "optometrist"}]
   [:outdoors :leisure  #{"park" "playground" "pitch" "dog_park" "nature_reserve" "common"}]
   [:sports   :leisure  #{"sports_centre" "fitness_centre" "fitness_station" "swimming_pool" "track" "sports_hall" "stadium"}]
   [:sports   :amenity  #{"dojo" "gym"}]
   [:culture  :tourism  #{"museum" "gallery"}]
   [:culture  :amenity  #{"library" "theatre" "cinema" "arts_centre" "community_centre" "social_centre"}]
   [:worship  :amenity  #{"place_of_worship"}]])

(defn- classify [tags]
  (some (fn [[c k vs]] (when (vs (get tags k)) c)) class-rules))

(defn- element-point
  "Node coordinates, or the `out center` centroid of a way/relation."
  [e]
  (let [lon (or (:lon e) (get-in e [:center :lon]))
        lat (or (:lat e) (get-in e [:center :lat]))]
    (when (and lon lat) [(double lon) (double lat)])))

(defn- feature-point
  "An ohsome `/centroid` feature's point."
  [f]
  (let [[lon lat] (get-in f [:geometry :coordinates])]
    (when (and (number? lon) (number? lat)) [(double lon) (double lat)])))

(defn- overlaps? [{:keys [west south east north]} b]
  (and b (<= (:west b) east) (>= (:east b) west) (<= (:south b) north) (>= (:north b) south)))

(def stuttgart-bbox
  "The bbox the Stuttgart POI pulls cover. They carry no bbox in their receipt
   note (they were pulled per Stadtbezirk, by polygon, not by rectangle), so
   the city's own envelope stands in for one — it is only used to decide
   whether a pull is worth opening at all, and every row is bbox-filtered
   against the world's grid afterwards."
  {:west 9.0 :south 48.68 :east 9.33 :north 48.88})

(defn- stuttgart-pull? [r]
  (and (= :osm-overpass (:acq/source r))
       (str/starts-with? (str (:acq/dataset r)) "stuttgart/")))

(defn- ohsome? [r] (str/ends-with? (str (:acq/path r)) ".geojson"))

(defn- stadtbezirk [r]
  (-> (str (:acq/dataset r)) (str/replace #"^stuttgart/" "") (str/replace #"\.(ohsome\.geojson|json)$" "")))

(defn receipts-for
  "Cached POI pulls whose coverage intersects `bbox`.

   Bbox pulls are the `pois-and-buildings` receipts, selected by the bbox in
   their own note. Stuttgart's are the per-Stadtbezirk pulls under
   `data/raw/osm-overpass/stuttgart/`; thirteen of the twenty-three exist in
   **both** formats, and where they do the **ohsome** pull wins — an Overpass
   `out center` is the centre of a way's bounding box and an ohsome
   `/centroid` is the polygon's centroid, so keeping both would put the same
   park on the map twice, a few tens of metres apart, and no coordinate-level
   dedup could see it."
  [bbox]
  (let [rs (acq/receipts)
        by-bbox (filter #(and (= :osm-overpass (:acq/source %))
                          (= "pois-and-buildings" (:acq/dataset %))
                          (overlaps? bbox (get-in % [:acq/note :bbox])))
                    rs)
        stu (when (overlaps? bbox stuttgart-bbox)
              (->> (filter stuttgart-pull? rs)
                   (group-by stadtbezirk)
                   (map (fn [[_ pulls]] (or (first (filter ohsome? pulls)) (first pulls))))))]
    (concat by-bbox stu)))

(defn- read-rows!
  "Stream one pull into `acc`, keeping `[class lon-e6 lat-e6]` for every
   classified element inside `bbox`."
  [acc {:keys [west south east north]} r]
  (let [path (:acq/path r)
        geo? (ohsome? r)
        keep! (fn [acc c [lon lat]]
                (if (and (<= (double west) (double lon) (double east))
                         (<= (double south) (double lat) (double north)))
                  (conj! acc [c (Math/round (* (double lon) 1.0e6)) (Math/round (* (double lat) 1.0e6))])
                  acc))]
    (if geo?
      (net/stream-array! path "features"
                         (fn [acc f]
                           (if-let [c (classify (:properties f))]
                             (if-let [p (feature-point f)] (keep! acc c p) acc)
                             acc))
                         acc)
      (net/stream-array! path "elements"
                         (fn [acc e]
                           (if-let [c (classify (:tags e))]
                             (if-let [p (element-point e)] (keep! acc c p) acc)
                             acc))
                         acc))))

(defn table
  "Venue table over `bbox` = {:n :class keyword[] :lon double[] :lat double[]},
   deduplicated by (class, 1e-6° lon/lat) because the district pulls overlap —
   and because an ohsome `elementsFullHistory` pull repeats an object once per
   validity window, which is the same duplicate seen from the time axis.
   Returns nil when no pull covers the bbox."
  [bbox]
  (let [rs (receipts-for bbox)
        rows (persistent! (reduce (fn [acc r] (read-rows! acc bbox r)) (transient []) rs))
        rows (vec (distinct rows))
        n (count rows)]
    (when (pos? n)
      {:n n
       :receipts (count rs)
       :class (into-array clojure.lang.Keyword (map first rows))
       :lon (double-array (map #(/ (double (nth % 1)) 1.0e6) rows))
       :lat (double-array (map #(/ (double (nth % 2)) 1.0e6) rows))})))

(defonce ^{:doc "bbox → venue table; the pulls are on disk and never change
                 inside a run, so one parse per world is enough."}
  cache (atom {}))

(defn table-cached [bbox]
  (let [k (mapv #(/ (Math/round (* 1.0e5 (double (bbox %)))) 1.0e5) [:west :south :east :north])]
    (if (contains? @cache k)
      (@cache k)
      (let [t (table bbox)] (swap! cache assoc k t) t))))

(defn summary [t]
  (when t (frequencies (seq ^objects (:class t)))))
