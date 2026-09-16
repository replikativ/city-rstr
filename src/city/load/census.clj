(ns city.load.census
  "Small-area statistics into the evidence store: the Stadtbezirk and
   Stadtteil boundaries (Kleinräumige Gliederung) and the Zensus 2022 100 m
   grid, with each cell located in its Stadtteil. The heavy filtering is done
   by `scripts/stuttgart_klgl.py` and `scripts/zensus_grid.py` (DuckDB) into
   `data/derived/*.jsonl`; this namespace adopts those files with receipts and
   loads them."
  (:require [city.intake.core :as acq]
            [city.store :as store]
            [city.geo.core :as geo]
            [datahike.api :as d]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]))

(def zensus-source {:source/id :zensus-2022 :source/name "Zensus 2022 Gitterdaten (Statistische Ämter des Bundes und der Länder)"
                    :source/url "https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Bevoelkerung/Zensus2022/_inhalt.html"
                    :source/license "dl-de/by-2.0"})
(def klgl-source {:source/id :stuttgart-klgl :source/name "Landeshauptstadt Stuttgart, Kleinräumige Gliederung (generalisiert)"
                  :source/url "https://opendata.stuttgart.de/dataset/kleinraumige-gliederung"
                  :source/license "CC BY 4.0"})

(defn- jsonl [path] (with-open [r (io/reader path)] (mapv #(json/read-str % :key-fn keyword) (line-seq r))))
(defn- strip-nil [m] (into {} (remove (comp nil? val)) m))
(defn- num* [v] (cond (number? v) (double v) (string? v) (try (Double/parseDouble (str/replace v "," ".")) (catch Exception _ nil)) :else nil))
(defn- long* [v] (some-> (num* v) long))
(defn- centroid [geometry] (let [b (geo/bbox-of geometry)] [(/ (+ (:west b) (:east b)) 2.0) (/ (+ (:south b) (:north b)) 2.0)]))

;; ---- Stuttgart areas + grid --------------------------------------------------

(defn load-stuttgart-areas! []
  (store/ensure-source! klgl-source)
  (let [r (acq/adopt! {:source :stuttgart-klgl :dataset "Kleinräumige Gliederung" :path "data/derived/stuttgart_areas.jsonl"
                       :url "https://www.stuttgart.de/medien/ibs/OpenData-KLGL-Generalsisiert.zip"})
        acq-ref (store/record-receipt! r)
        recs (jsonl (:acq/path r))
        ent (fn [{:keys [level nr name parent_nr geometry]}]
              (let [[lon lat] (centroid geometry)]
                (strip-nil
                 {:entity/ext-id (str "stuttgart:" level ":" nr) :entity/kind :area :entity/acq acq-ref
                  :entity/name (or name (str level " " nr)) :entity/geometry (geo/geojson-str geometry)
                  :entity/lat lat :entity/lon lon
                  :area/name (str "Stuttgart " (or name (str level " " nr))) :area/code nr :area/city :stuttgart
                  :area/level (keyword level)
                  :area/parent (when parent_nr [:entity/ext-id (str "stuttgart:stadtbezirk:" parent_nr)])})))
        by-level (group-by :level recs)]
    ;; parents first so lookup refs resolve
    {:stadtbezirk (store/transact-batched! (map ent (by-level "stadtbezirk")))
     :stadtteil (store/transact-batched! (map ent (by-level "stadtteil")))
     :baublock (store/transact-batched! (map ent (by-level "baublock")))}))

(defn load-stuttgart-grid! []
  (store/ensure-source! zensus-source)
  (let [r (acq/adopt! {:source :zensus-2022 :dataset "100 m grid, Stuttgart bbox" :path "data/derived/stuttgart_zensus_100m.jsonl"
                       :url "https://www.destatis.de/static/DE/zensus/gitterdaten/"})
        acq-ref (store/record-receipt! r)
        recs (jsonl (:acq/path r))
        pick (fn [m re] (into {} (for [[k v] m :when (re-find re (name k)) :let [n (long* v)] :when n] [(name k) n])))
        ents (for [{:keys [gid x y lon lat] :as m} recs]
               (strip-nil
                {:entity/ext-id (str "zensus:" gid) :entity/kind :cell :entity/acq acq-ref
                 :entity/lat lat :entity/lon lon
                 :cell/gid gid :cell/x (num* x) :cell/y (num* y)
                 :cell/population (long* (or (:Einwohner m) (:Insgesamt_Bevoelkerung m)))
                 :cell/age (let [a (pick m #"^(unter5|a\d+bis\d+|a90undaelter)$")] (when (seq a) (pr-str a)))
                 ;; the size classes are named 1_Person, 2_Personen … 6_Personen_und_mehr
                 :cell/household-size (let [h (pick m #"^(Insgesamt_Haushalte|\d_Person(en)?(_und_mehr)?)$")] (when (seq h) (pr-str h)))
                 :cell/rent (num* (some m [:durchschnMieteQM :Durchschn_Nettokaltmiete :durchschnittliche_Nettokaltmiete]))
                 :cell/building-year (let [b (pick m #"^(Insgesamt_Gebaeude|Vor1919|a(19|20)\d\d)")] (when (seq b) (pr-str b)))}))]
    (store/transact-batched! ents :batch 2000)))

(defn locate-cells!
  "Assign each Stuttgart cell to its Stadtteil by point-in-polygon."
  []
  (let [db (store/db)
        areas (->> (d/q '[:find ?e ?g :where [?e :area/city :stuttgart] [?e :area/level :stadtteil] [?e :entity/geometry ?g]] db)
                   (map (fn [[e g]] (geo/with-bbox {:eid e :geometry (geo/parse-geojson g) :name e}))))
        cells (d/q '[:find ?e ?lon ?lat :where [?e :entity/kind :cell] [?e :entity/lon ?lon] [?e :entity/lat ?lat]] db)
        tx (for [[e lon lat] cells :let [a (geo/locate areas [lon lat])] :when a] [:db/add e :entity/area a])]
    (store/transact-batched! tx)))
