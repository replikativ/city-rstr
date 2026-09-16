(ns city.synth.retail
  "Venue size for the destination kernel, measured rather than synthesized,
   and the retail concept's published district figures.

   The kernel's size term carries most of its effect, and a *synthesized*
   employee count put 2,889 employees on a convenience store and 1 on the
   median Königstraße shop. The size term is instead two measurements layered
   the way the population synthesis layers its own: **shape from one source,
   level from another**.

   - **Shape**: each firm's building footprint, from an OpenStreetMap
     `way[building]` pull with geometry. A firm is matched to the smallest
     polygon containing it, or the nearest centroid within 25 m; a building
     holding n firms gives each of them area/n. 22,863 of 25,743 Stuttgart
     firms match (88.8 %), median 114 m², 99th percentile 2,205 m².
   - **Level**: the retail floor area the 2021 establishment census publishes
     for each of the 23 Stadtbezirke (`doc/sources/economy.md`). Each district's
     retail firms are scaled so their footprints sum to the measured
     Verkaufsfläche.

   Scored against that census's own retail centrality, over 23 districts:

   | size term | log-corr | mean abs log ratio | Mitte (observed 10.54) |
   |---|---|---|---|
   | synthesized payroll | 0.328 | 1.058 | 1.72 |
   | street-density count | 0.752 | 0.760 | 11.46 |
   | footprint alone | 0.605 | 0.661 | 1.93 |
   | count × footprint | 0.776 | 0.633 | 8.80 |
   | **footprint raked to the census** | **0.786** | **0.509** | 7.23 |

   A mean absolute log ratio of 0.509 is a typical district missed by a factor
   of 1.66, against 2.88 for the synthesized payroll.

   **What each proxy is actually measuring**, since the ranking is not obvious.
   The density count measures *agglomeration* — it puts the centre far ahead
   because a hundred shops share a block, and it alone reaches Mitte's observed
   draw. The footprint measures *unit size* — it is much better across ordinary
   districts, where a big-box store on its own site should beat a corner shop,
   and much worse at the centre, where shops are small units inside shared
   buildings. Summing split footprints over a block recovers only the building
   area and so cancels the agglomeration entirely, which is why that variant
   scores worse than either parent. Raking keeps the footprint's within-district
   shape and takes the level from a measurement, which is why it wins on the
   honest metrics while the count still wins on the centre alone."
  (:require [clojure.data.json :as json]
            [clojure.string :as str]
            [clojure.java.io :as io]))

(def size-path "data/derived/stuttgart_firm_size_m2.json")
(def census-path "data/derived/stuttgart_retail_districts.json")
(def areas-path "data/derived/stuttgart_areas.jsonl")

(defn firm-sizes
  "{firm-eid → footprint share in m²}, or nil when the file is absent."
  ([] (firm-sizes size-path))
  ([path]
   (when (.exists (io/file path))
     (into {} (for [[k v] (json/read-str (slurp path))] [(parse-long k) (double v)])))))

(defn district-of
  "Stadtteil → Stadtbezirk, from the areas file. The census publishes at
   Stadtbezirk level; firms carry a Stadtteil."
  ([] (district-of areas-path))
  ([path]
   (when (.exists (io/file path))
     (let [rows (with-open [r (io/reader path)]
                  (mapv #(json/read-str % :key-fn keyword) (line-seq r)))
           bez (into {} (for [x rows :when (= "stadtbezirk" (:level x))] [(:nr x) (:name x)]))]
       (into {} (for [x rows :when (and (= "stadtteil" (:level x)) (bez (:parent_nr x)))]
                  [(:name x) (bez (:parent_nr x))]))))))

(defn census-area
  "{Stadtbezirk → measured retail floor area in m²}."
  ([] (census-area census-path))
  ([path]
   (when (.exists (io/file path))
     (into {} (for [m (json/read-str (slurp path) :key-fn keyword)]
                [(:stadtbezirk m) (double (:verkaufsflaeche_m2 m))])))))

(defn- median-of [xs]
  (let [s (vec (sort xs))] (nth s (quot (count s) 2))))

(defn filled-footprints
  "double[n]: each firm's matched footprint share in m² (`sizes`, by firm
   eid), or, for a firm with no matched building, the median matched
   footprint of its district (`dist`, firm index → district), or of the city
   when its district has none; at least 1. A missing measurement is not a
   claim that the shop is tiny. Also returns the matched count."
  [firms sizes dist]
  (let [n (:n firms) ^longs eid (:eid firms)
        raw (double-array n)
        _ (dotimes [j n] (aset raw j (double (get sizes (aget eid j) 0.0))))
        med (let [by (reduce (fn [m j] (if (pos? (aget raw j)) (update m (dist j) (fnil conj []) (aget raw j)) m))
                             {} (range n))]
              (update-vals by median-of))
        all-med (let [s (remove zero? (seq raw))] (if (seq s) (median-of s) 1.0))
        filled (double-array n)]
    (dotimes [j n] (aset filled j (max 1.0 (if (pos? (aget raw j)) (aget raw j)
                                                (double (get med (dist j) all-med))))))
    {:filled filled
     :matched (count (filter #(pos? (aget raw %)) (range n)))}))

(defn district-fn
  "Firm index → Stadtbezirk, through the firm's Stadtteil (`:la`) and
   `st->bez`; a Stadtteil `st->bez` does not know is taken as a district name."
  [firms st->bez]
  (let [^objects la (:la firms)]
    (fn [^long j] (let [a (aget la j)] (get st->bez a a)))))

(defn attract
  "Per-firm attractiveness for the store kernel, as measured floor area:
   `filled-footprints` for the shape, raked per district so the retail firms'
   areas sum to the census's Verkaufsfläche. Returns
   `{:attract double[n] :matched :districts-raked}`, or nil when the inputs
   are missing.

   Raking is applied over the firms the kernel can actually choose, the
   retail flag, since the census total is a *retail* floor area; every firm in
   the district is scaled by the same factor."
  [firms & {:keys [sizes census st->bez flag]
            :or {sizes (firm-sizes) census (census-area) st->bez (district-of)}}]
  (when (and sizes census st->bez)
    (let [n (:n firms)
          ^ints flag (or flag (:retail firms))
          dist (district-fn firms st->bez)
          {:keys [^doubles filled matched]} (filled-footprints firms sizes dist)
          sums (reduce (fn [m j] (if (= 1 (aget flag j)) (update m (dist j) (fnil + 0.0) (aget filled j)) m))
                       {} (range n))
          out (double-array n)]
      (dotimes [j n]
        (let [d (dist j) s (double (get sums d 0.0)) t (double (get census d 0.0))]
          (aset out j (max 1.0 (if (and (pos? s) (pos? t)) (* (aget filled j) (/ t s)) (aget filled j))))))
      {:attract out
       :matched matched
       :districts-raked (count (filter (fn [[d s]] (and (pos? (double s)) (pos? (double (get census d 0.0))))) sums))})))

;; ---- what the census says a district's retail is worth ------------------------------

(def detail-path "data/derived/stuttgart_retail_detail.json")

(defn read-detail
  "The extracted EZK 2024 detail tables, or nil when the file is absent."
  [path]
  (when (.exists (io/file path))
    (json/read-str (slurp path) :key-fn keyword)))

(defn district-entries
  "`[[Stadtbezirk entry] …]` for the district rows of the detail tables. Names
   are published as `Stuttgart-Mitte`; the prefix is stripped so they join the
   Stadtbezirk names the rest of the pipeline uses."
  [doc]
  (for [e (:entries doc) :when (= "stadtbezirk" (:scope e))]
    [(str/replace (:name e) #"^Stuttgart-" "") e]))

(defn mio-eur "Million euros → euros; nil stays nil." [x]
  (when x (* 1.0e6 (double x))))

(defn targets
  "{Stadtbezirk → {:umsatz-eur n :kaufkraft-eur n :zentralitaet n :verkaufsflaeche-m2 n
                   :betriebe n}} from the 2024 Einzelhandels- und Zentrenkonzept, survey
   year 2021 (`city.sim.validate/retail-revenue` scores against this).

   Two things here that `census-area` does not have, and both matter.

   **Turnover in euros.** 4,484.4 M € across the 23 Stadtbezirke, of which Mitte
   alone is 1,905.8 M € — 42 %. A destination model that only reproduces a
   *ratio* can be right about shape and wrong about scale; this is the level.

   **Measured purchasing power.** Without it `retail-centrality` proxies a
   district's purchasing power by its resident count, and the study's own
   Kaufkraft varies across districts by about ±35 % per resident; pass
   `:kaufkraft` from here and that error term disappears.

   The same file carries the 76 zentrale Versorgungsbereiche and a 20-group
   assortment breakdown per district. Neither is read here: the centres need a
   geometry we do not have, and on the centre rows the Kaufkraft column repeats
   the whole district's value rather than the centre's, so it cannot be used as
   published."
  ([] (targets detail-path))
  ([path]
   (some->> (read-detail path) district-entries
            (into {} (map (fn [[d e]]
                            (let [t (:total e)]
                              [d {:umsatz-eur (mio-eur (:umsatz_mio_eur t))
                                  :kaufkraft-eur (mio-eur (:kaufkraft_mio_eur t))
                                  :zentralitaet (:zentralitaet t)
                                  :verkaufsflaeche-m2 (:verkaufsflaeche_m2 t)
                                  :betriebe (:betriebe t)}])))))))
