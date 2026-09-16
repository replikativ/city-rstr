(ns city.econ.household
  "Purchasing power per resident, the money every economic quantity starts
   from.

   **Purchasing power, not income, and the distinction matters.** The Jahrbuch
   publishes two different things: VGR *disposable income* at 31,390 EUR per
   inhabitant for the city (2023), and IFH *Kaufkraft* per Stadtbezirk (2024),
   23 measured values from 25,369 in Stammheim to 37,970 in Nord. The model
   carries the second, because it is the denominator the retail study's own
   centrality is computed against, so spending is consistent with the
   turnover the destination model is scored on. Carrying income instead would
   make the two incomparable at exactly the point they must meet.

   The two are not equal and should not be expected to agree: Kaufkraft is a
   retail-relevant measure net of committed expenditure, disposable income is a
   national-accounts aggregate, and they are a year apart. The city figure is a
   sanity band, not a target."
  (:require [clojure.data.json :as json]
            [clojure.java.io :as io]))

(def income-path "data/derived/stuttgart_jahrbuch_einkommen.json")

(def ^:private aggregate-rows
  "Table 6.5.2 mixes three aggregates in with the 23 Stadtbezirke. No person maps
   to them, so they cannot corrupt the raking, but they would silently double a
   city total — so they are excluded by name and kept separately as the check."
  #{"Stuttgart" "Inneres Stadtgebiet" "Äußeres Stadtgebiet"})

(defn- kk-rows [path]
  (when (.exists (io/file path))
    (->> (:table_6_5_2_kaufkraft_stadtbezirke (json/read-str (slurp path) :key-fn keyword))
         (filter :kaufkraft_je_einwohner_eur))))

(defn- kk-entry [r]
  [(:stadtbezirk r)
   {:per-inhabitant (double (:kaufkraft_je_einwohner_eur r))
    :total-eur (* 1000.0 (double (:kaufkraft_absolut_1000_eur r)))
    :index (:kaufkraftniveau_index_de100 r)}])

(defn kaufkraft
  "{Stadtbezirk → {:per-inhabitant eur :total-eur eur :index n}}, the 23
   districts only."
  ([] (kaufkraft income-path))
  ([path]
   (when-let [rs (kk-rows path)]
     (into {} (for [r rs :when (not (aggregate-rows (:stadtbezirk r)))] (kk-entry r))))))

(defn city-kaufkraft
  "The published city row, which the assignment is **not** raked to and can
   therefore be checked against."
  ([] (city-kaufkraft income-path))
  ([path]
   (when-let [rs (kk-rows path)]
     (second (first (for [r rs :when (= "Stuttgart" (:stadtbezirk r))] (kk-entry r)))))))

(defn relative-weight
  "The assumed within-district purchasing-power ratio of one resident, by
   census AGEGRP code (see `assign-purchasing-power!`) and employment: under
   15, 15–19, in work, 65 and over, everyone else."
  ^double [^long agegrp working?]
  (cond
    (<= agegrp 2) 0.25
    (= agegrp 3) 0.45
    working? 1.30
    (>= agegrp 12) 0.85
    :else 0.70))

(defn assign-purchasing-power!
  "Give every **resident** a purchasing power in euros per year, and return the
   world with `:persons :pp` added.

   Three layers, in the order the population synthesis itself uses — shape from
   one source, level from another:

   1. **Shape within a district** comes from labour status and age group
      (`:age` is the census AGEGRP code of `city.synth.stuttgart/grid-bands`,
      1 = 0–9, 2 = 10–14, 3 = 15–19, …, 12 = 65–74, 13 = 75+; not years): a person in
      work carries more than one not in work, and the young and the very old
      carry less. These are ratios, not levels, and they are `:assumed` — no
      source in hand gives purchasing power by person type at Stadtbezirk level.
      They are declared here rather than buried so that the first thing anyone
      checks is whether they matter.
   2. **Level per district** is the measured IFH figure, and the district's
      people are raked to its published *total* so the district sums are exact
      by construction.
   3. **In-commuters get nothing.** Their purchasing power is spent where they
      live, which is outside the city and outside this model. Giving them a
      share would inflate the city aggregate by a third and silently break the
      comparison with the retail census, whose Kaufkraft is residents only.

   The scored claim is therefore *not* the district totals — those are raked and
   cannot fail. It is the city aggregate against an independent VGR figure, and
   the shape, which shows up later as whether spending lands where the retail
   census says it does."
  [world & {:keys [kk by-district] :or {kk (kaufkraft)}}]
  (if-not (seq kk)
    world
    (let [ps (:persons world) n (:n ps)
          ^ints ext (or (:external ps) (int-array n))
          ^objects la (:la ps)
          ^ints emp (:employed ps) ^ints age (:age ps)
          dist (or by-district identity)
          ;; layer 1: relative weight within a district — assumed, see docstring
          w (fn ^double [^long i] (relative-weight (aget age i) (= 1 (aget emp i))))
          raw (double-array n)
          sums (java.util.HashMap.)]
      (dotimes [i n]
        (when (zero? (aget ext i))
          (let [d (dist (aget la i)) x (w i)]
            (aset raw i x)
            (.put sums d (+ (double (or (.get sums d) 0.0)) x)))))
      (let [pp (double-array n)]
        (dotimes [i n]
          (when (and (zero? (aget ext i)) (pos? (aget raw i)))
            (let [d (dist (aget la i))
                  s (double (or (.get sums d) 0.0))
                  t (double (get-in kk [d :total-eur] 0.0))]
              (aset pp i (if (and (pos? s) (pos? t)) (* (aget raw i) (/ t s)) 0.0)))))
        (-> world
            (assoc-in [:persons :pp] pp)
            (assoc :purchasing-power
                   {:districts (count kk)
                    :residents-with-pp (count (filter #(pos? (aget pp %)) (range n)))
                    :city-total-eur (reduce + (map #(aget pp %) (range n)))}))))))
