(ns city.synth.stuttgart
  "A synthetic Stuttgart population from aggregates only.

   Germany publishes no public microdata seed at city level (the Mikrozensus
   SUF needs an FDZ contract), so there is no sample to reweight. What exists
   is a stack of marginals, and this namespace turns them into persons
   directly:

   - Zensus 2022 100 m grid (`:cell/population`, `:cell/age`,
     `:cell/household-size`) — the spatial backbone, one cell = one `:da`.
   - Zensus 2022 Gemeinde Regionaltabellen (Bildung + Erwerbstätigkeit) for
     08111000 — P(employed | age), the unemployment rate, the pupil count.
   - Regionalstatistik 12411-04-02-4 (Fortschreibung, Kreis 08111) — the
     age-specific sex ratio, so sex is not a flat coin flip.

   The output uses the Statistics Canada PUMF key vocabulary (`:AGEGRP`,
   `:LFACT`, `:ATTSCH`, …), the schema `city.sim.cityworld/persons-columns`
   reads; the model's first city was Vancouver."
  (:require [clojure.data.json :as json]
            [clojure.edn :as edn]
            [clojure.java.io :as io]
            [clojure.string :as str]))

;; ---- provenance -------------------------------------------------------------------

(def raw-sources
  "Everything fetched for the Stuttgart world that was not already adopted by
   `city.load.census` / `city.load.stuttgart`. Downloaded with curl (the
   Regionalstatistik endpoint and the destatis static files are large or
   latin-1 and are easier to pull outside `acquire!`), then adopted so each
   carries a receipt with its sha256."
  [{:source :zensus-2022 :dataset "Regionaltabelle Bildung + Erwerbstätigkeit (Gemeinden)"
    :url "https://www.destatis.de/static/DE/zensus/gitterdaten/Regionaltabelle_Bildung_Erwerbstaetigkeit.xlsx"
    :path "data/raw/regionalstatistik/Regionaltabelle_Bildung_Erwerbstaetigkeit.xlsx"}
   {:source :zensus-2022 :dataset "Regionaltabelle Demografie (Gemeinden)"
    :url "https://www.destatis.de/static/DE/zensus/gitterdaten/Regionaltabelle_Demografie.xlsx"
    :path "data/raw/regionalstatistik/Regionaltabelle_Demografie.xlsx"}
   {:source :zensus-2022 :dataset "Regionaltabelle Bevölkerung (Gemeinden)"
    :url "https://www.destatis.de/static/DE/zensus/gitterdaten/Regionaltabelle_Bevoelkerung.xlsx"
    :path "data/raw/regionalstatistik/Regionaltabelle_Bevoelkerung.xlsx"}
   {:source :regionalstatistik :dataset "12411-04-02-4 Bevölkerung nach Geschlecht und Altersjahren, Kreis 08111"
    :url "https://www.regionalstatistik.de/genesis/online?operation=download&code=12411-04-02-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2022"
    :path "data/raw/regionalstatistik/12411-04-02-4.csv"}
   {:source :regionalstatistik :dataset "13111-01-03-4 SvB am Arbeitsort, Kreis 08111"
    :url "https://www.regionalstatistik.de/genesis/online?operation=download&code=13111-01-03-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2020"
    :path "data/raw/regionalstatistik/13111-01-03-4.csv"}
   {:source :regionalstatistik :dataset "52111-01-02-4 Niederlassungen nach Beschäftigtengrößenklassen, Kreis 08111"
    :url "https://www.regionalstatistik.de/genesis/online?operation=download&code=52111-01-02-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2020"
    :path "data/raw/regionalstatistik/52111-01-02-4.csv"}
   {:source :regionalstatistik :dataset "52111-02-01-4 Niederlassungen nach WZ-Abschnitten, Kreis 08111"
    :url "https://www.regionalstatistik.de/genesis/online?operation=download&code=52111-02-01-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2020"
    :path "data/raw/regionalstatistik/52111-02-01-4.csv"}
   {:source :regionalstatistik :dataset "52111-07-01-4 Abhängig Beschäftigte nach WZ-Abschnitten, Kreis 08111"
    :url "https://www.regionalstatistik.de/genesis/online?operation=download&code=52111-07-01-4&option=csv&sprache=de&regionalschluessel=08111&startjahr=2020"
    :path "data/raw/regionalstatistik/52111-07-01-4.csv"}
   {:source :ba-beschaeftigung :dataset "Gemeindedaten der Beschäftigungsstatistik 30.06.2024"
    :url "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202406/iiia6/beschaeftigung-sozbe-gemband/gemband-dlk-0-202406-xlsx.xlsx"
    :path "data/raw/ba/gemband-dlk-0-202406.xlsx"}
   {:source :ba-beschaeftigung :dataset "Gemeindedaten der Beschäftigungsstatistik 30.06.2022 (xlsb)"
    :url "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202206/iiia6/beschaeftigung-sozbe-gemband/gemband-dlk-0-202206-zip.zip"
    :path "data/raw/ba/gemband-dlk-0-202206.zip"}
   ;; Kreis-zu-Kreis Pendlermatrix. Sheets "Einpendler Kreise" / "Auspendler Kreise";
   ;; jede Arbeitsort-Zeile (Spalten A/B) wird von den Wohnort-Zeilen (Spalten C/D) gefolgt.
   ;; 30.06.2023 ist die neueste veröffentlichte Ausgabe (Stand 2026-09); 202406 existiert nicht.
   {:source :ba-beschaeftigung :dataset "Pendlerverflechtungen der SvB nach Kreisen 30.06.2023"
    :url "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202306/iiia6/beschaeftigung-pendler-krpend/krpend-k-0-202306-xlsx.xlsx"
    :path "data/raw/ba/ba-krpend-k-0-202306.xlsx"}])

(defn adopt-raw!
  "Write a receipt beside every raw file the Stuttgart world reads."
  []
  (let [adopt (requiring-resolve 'city.intake.core/adopt!)]
    (vec (for [r raw-sources :when (.exists (io/file (:path r)))]
           (select-keys (adopt r) [:acq/dataset :acq/sha256 :acq/bytes :acq/path])))))

;; ---- cached reads of the store ---------------------------------------------------

(def cells-path "data/derived/stuttgart_cells.jsonl")
(def areas-path "data/derived/stuttgart_areas_store.edn")
(def centroids-path "data/derived/stuttgart_cell_centroids.jsonl")
(def persons-path "data/derived/synth_stuttgart_persons.edn")

(defn cache-areas!
  "Stadtteil/Stadtbezirk rows from the Datahike store, once, to an EDN file.
   [{:eid :level :code :name :parent-eid}]"
  []
  (let [d (requiring-resolve 'datahike.api/q)
        db ((requiring-resolve 'city.store/db))
        rows (d '[:find ?e ?lvl ?code ?name
                  :where [?e :area/city :stuttgart] [?e :area/level ?lvl]
                  [(contains? #{:stadtteil :stadtbezirk} ?lvl)]
                  [?e :area/code ?code] [?e :entity/name ?name]] db)
        parents (into {} (d '[:find ?e ?p :where [?e :area/city :stuttgart] [?e :area/parent ?p]] db))
        areas (vec (for [[e lvl code name] rows]
                     {:eid e :level lvl :code code :name name :parent-eid (parents e)}))]
    (io/make-parents areas-path)
    (spit areas-path (pr-str areas))
    {:areas (count areas) :path areas-path}))

;; ---- age bands -------------------------------------------------------------------

(def grid-bands
  "The Zensus 100 m age columns, in order, with the PUMF AGEGRP they fold into
   (`city.synth.pumf/age-group`: 1 = 0–9 … 13 = 75+) and their age span."
  [[:unter5 1 0 4] [:a5bis9 1 5 9] [:a10bis14 2 10 14] [:a15bis19 3 15 19]
   [:a20bis24 4 20 24] [:a25bis29 5 25 29] [:a30bis34 6 30 34] [:a35bis39 7 35 39]
   [:a40bis44 8 40 44] [:a45bis49 9 45 49] [:a50bis54 10 50 54] [:a55bis59 11 55 59]
   [:a60bis64 11 60 64] [:a65bis69 12 65 69] [:a70bis74 12 70 74] [:a75bis79 13 75 79]
   [:a80bis84 13 80 84] [:a85bis89 13 85 89] [:a90undaelter 13 90 99]])

(def hh-bands
  "Household-size columns and the size they stand for (6+ counted as 6)."
  [[:1_Person 1] [:2_Personen 2] [:3_Personen 3] [:4_Personen 4] [:5_Personen 5] [:6_Personen_und_mehr 6]])

(defn- n* [v] (cond (number? v) (long v) (and (string? v) (re-matches #"-?\d+" v)) (Long/parseLong v) :else nil))

(defn- rescale
  "Rescale a histogram so it sums to `total`, largest remainder (exact)."
  [known ^long total]
  (let [ks (vec (keys known)) s (reduce + 0 (vals known))
        raw (mapv #(* (double total) (/ (double (known %)) s)) ks)
        base (mapv #(long (Math/floor ^double %)) raw)
        left (- total (reduce + base))
        order (->> (map-indexed (fn [i ^double r] [i (- r (Math/floor r))]) raw)
                   (sort-by (comp - second)) (map first) (take left) set)]
    (into {} (map-indexed (fn [i k] [k (+ (base i) (if (order i) 1 0))]) ks))))

(defn histogram
  "A suppressed Zensus histogram → [known-counts missing-keys residual].
   '–' means the cell is below the publication threshold, not zero. The 100 m
   grid is protected by cell-key noise applied per *cell and characteristic*,
   so the published bands can also overshoot the published total; then the
   bands are scaled down to it and nothing is left for the suppressed ones."
  [m ks total]
  (let [known (into {} (for [k ks :let [v (n* (get m k))] :when v] [k v]))
        s (reduce + 0 (vals known))
        total (long total)]
    (if (or (> s total) (and (< s total) (every? known ks) (pos? s)))
      ;; every band published but the noised sum misses the noised total
      [(rescale known total) [] 0]
      [known (vec (remove known ks)) (- total s)])))

(defn fill
  "Distribute `residual` over `missing` in proportion to `profile` (a
   {key weight} map, here the parent Stadtteil's own profile), largest
   remainder so the counts stay integers and sum exactly."
  [known missing residual profile]
  (if (or (zero? residual) (empty? missing))
    known
    (let [w (mapv #(double (max 1e-9 (get profile % 0.0))) missing)
          s (reduce + w)
          raw (mapv #(* residual (/ % s)) w)
          base (mapv #(long (Math/floor %)) raw)
          left (- residual (reduce + base))
          order (->> (map-indexed (fn [i r] [i (- (double r) (Math/floor (double r)))]) raw)
                     (sort-by (comp - second)) (map first))
          add (frequencies (take left (concat order (repeat (first order)))))]
      (merge known (into {} (map-indexed (fn [i k] [k (+ (base i) (get add i 0))]) missing))))))

(def grid-jsonl
  "The file `city.load.census/load-stuttgart-grid!` adopts. It is read here for
   the two histograms rather than the store because `:cell/household-size` in
   the store holds only `Insgesamt_Haushalte`: the loader's `pick` regex was
   written `#\"…\\\\d_Person…\"`, which matches a literal backslash, so the six
   size classes were never transacted. The regex is fixed in `city.load.census`
   but the store is not reloaded here (a 4 GB read-only connection)."
  "data/derived/stuttgart_zensus_100m.jsonl")

(defn cache-cells!
  "Zensus cells to JSONL, once: gid, lon/lat, population and the Stadtteil /
   Stadtbezirk from the store (the point-in-polygon assignment already
   transacted by `city.load.census/locate-cells!`), the two suppressed
   histograms from the adopted grid extract."
  []
  (let [d (requiring-resolve 'datahike.api/q)
        db ((requiring-resolve 'city.store/db))
        areas (edn/read-string (slurp areas-path))
        by-eid (into {} (map (juxt :eid identity)) areas)
        rows (d '[:find ?gid ?lon ?lat ?pop ?a
                  :where [?e :entity/kind :cell] [?e :cell/gid ?gid]
                  [?e :entity/lon ?lon] [?e :entity/lat ?lat]
                  [?e :cell/population ?pop] [?e :entity/area ?a]] db)
        raw (with-open [r (io/reader grid-jsonl)]
              (into {} (for [l (line-seq r) :let [m (json/read-str l :key-fn keyword)]]
                         [(:gid m) m])))
        pick (fn [m ks] (into {} (for [k ks :let [v (n* (get m k))] :when v] [k v])))
        agek (mapv first grid-bands)
        hhk (into [:Insgesamt_Haushalte] (map first hh-bands))]
    (io/make-parents cells-path)
    (with-open [w (io/writer cells-path)]
      (doseq [[gid lon lat pop a] (sort-by first rows)
              :let [st (by-eid a) sb (by-eid (:parent-eid st)) m (raw gid)]]
        (.write w (json/write-str {:gid gid :lon lon :lat lat :population pop
                                   :age (pick m agek) :hh (pick m hhk)
                                   :stadtteil (:name st) :stadtteil-code (:code st)
                                   :stadtbezirk (:name sb) :stadtbezirk-code (:code sb)}))
        (.write w "\n")))
    {:cells (count rows)
     :population (reduce + (map #(nth % 3) rows))
     :path cells-path}))

(defn cells [] (with-open [r (io/reader cells-path)] (mapv #(json/read-str % :key-fn keyword) (line-seq r))))

;; ---- the Gemeinde tables ----------------------------------------------------------

(def gemeinde
  "Zensus 2022, Gemeinde 08111000 (Stuttgart), from
   data/raw/regionalstatistik/Regionaltabelle_Bildung_Erwerbstaetigkeit.xlsx
   (sheets CSV-Erwerbsstatus, CSV-ET_Alter, CSV-Schulform). Transcribed here
   rather than parsed at run time: the workbook is 28 MB and covers all of
   Germany, and these eleven numbers are the whole of what the model uses.
   Reference date 2022-05-15; the universe is the population in private
   households (593,900 of the 610,458 Zensus residents)."
  {:population-private-households 593900
   :labour-force 338280
   :employed 315900
   :unemployed 22380
   :not-in-labour-force 255620
   ;; Erwerbstätige by the table's own age bands
   :employed-by-age {[15 19] 6970 [20 29] 65000 [30 39] 79720 [40 49] 63160
                     [50 59] 66210 [60 67] 27240 [68 99] 7600}
   ;; Personen in schulischer Ausbildung (general schools only — no Hochschule)
   :pupils 62860
   :zensus-population 610458
   :zensus-men 303207
   :zensus-women 307249})

(def tertiary-share-20-24
  "Share of residents aged 20–24 in education (ATTSCH 1) on top of the school
   population. Not in any table fetched: the Zensus Schulform table counts
   general schools only, and Hochschule enrolment is published by place of
   study, not residence. 0.45 is the German Bildungsbeteiligung of the 20–24
   cohort (tertiary + vocational school); an assumption, flagged as such."
  0.45)

(defn sex-ratio-by-band
  "P(male | 5-year band) from Regionalstatistik 12411-04-02-4 (Fortschreibung
   des Bevölkerungsstandes, Kreis 08111, 31.12.2022, single years of age)."
  [path]
  (let [lines (with-open [r (io/reader path :encoding "ISO-8859-1")] (vec (line-seq r)))
        rows (for [l lines
                   :let [f (str/split l #";")]
                   :when (and (= 6 (count f)) (= "08111" (str/trim (first f))))
                   :let [lbl (nth f 2)
                         age (cond (re-find #"^unter 1" lbl) 0
                                   (re-find #"^(\d+) bis unter" lbl) (Long/parseLong (second (re-find #"^(\d+) bis unter" lbl)))
                                   (re-find #"^(\d+) Jahre und mehr" lbl) (Long/parseLong (second (re-find #"^(\d+) Jahre und mehr" lbl)))
                                   :else nil)
                         m (n* (nth f 4)) w (n* (nth f 5))]
                   :when (and age m w)]
               [age m w])]
    (into {} (for [[k _ lo hi] grid-bands
                   :let [sel (filter (fn [[a _ _]] (<= lo a hi)) rows)
                         m (reduce + (map second sel)) w (reduce + (map #(nth % 2) sel))]]
               [k (if (pos? (+ m w)) (/ (double m) (+ m w)) 0.5)]))))

(defn employment-rates
  "P(employed | 5-year band). The Zensus publishes Erwerbstätige in bands
   15–19/20–29/…/60–67/68+; the grid publishes population in 5-year bands.
   A band that straddles a Zensus band (65–69 straddles 60–67 and 68+) is
   split pro rata by single years."
  [pop-by-band]
  (let [ebands (:employed-by-age gemeinde)
        ;; population of each Zensus band, splitting 5-year bands by overlap
        overlap (fn [[lo hi] [blo bhi]] (max 0 (inc (- (min hi bhi) (max lo blo)))))
        bandpop (into {} (for [[zb _] ebands]
                           [zb (reduce + (for [[k _ lo hi] grid-bands
                                               :let [o (overlap zb [lo hi])]
                                               :when (pos? o)]
                                           (* (get pop-by-band k 0) (/ (double o) (inc (- hi lo))))))]))
        rate (into {} (for [[zb e] ebands] [zb (if (pos? (bandpop zb)) (/ (double e) (bandpop zb)) 0.0)]))]
    (into {} (for [[k _ lo hi] grid-bands]
               [k (let [span (inc (- hi lo))
                        r (reduce + (for [[zb v] rate :let [o (overlap zb [lo hi])] :when (pos? o)]
                                      (* v (/ (double o) span))))]
                    (min 1.0 r))]))))

;; ---- synthesis --------------------------------------------------------------------

(defn- profiles
  "Per Stadtteil, the age and household-size profile of the *published* counts
   — what a suppressed cell's residual is spread over."
  [cells]
  (reduce (fn [acc c]
            (let [st (:stadtteil c)]
              (-> acc
                  (update-in [:age st] #(merge-with + (or % {}) (into {} (for [[k _ _ _] grid-bands :let [v (n* (get (:age c) k))] :when v] [k v]))))
                  (update-in [:hh st] #(merge-with + (or % {}) (into {} (for [[k _] hh-bands :let [v (n* (get (:hh c) k))] :when v] [k v])))))))
          {:age {} :hh {}} cells))

(defn- shuffled [^java.util.Random rng coll]
  (let [l (java.util.ArrayList. ^java.util.Collection (vec coll))]
    (java.util.Collections/shuffle l rng) (vec l)))

(def band->agegrp (into {} (for [[k g _ _] grid-bands] [k g])))

(defn household-slots
  "Household sizes of one cell, reconciled with its population. The Zensus
   publishes '6 Personen und mehr' as one class, so counting it as 6 leaves a
   shortfall: the shortfall goes first into enlarging those households, and
   only what is left over creates extra one-person households. A surplus
   (suppression noise the other way) removes the smallest households."
  [sizes ^long target]
  (let [base (vec (sort > (mapcat (fn [[k s]] (repeat (get sizes k 0) s)) hh-bands)))
        tot (reduce + 0 base)]
    (cond
      (= tot target) base
      (< tot target) (let [big (count (filter #(>= % 6) base))
                        short (- target tot)
                        extra (min short (* 4 (max 0 big)))   ;; up to 10 persons per 6+ household
                        per (if (pos? big) (quot extra big) 0)
                        rem (if (pos? big) (- extra (* per big)) 0)
                        base' (vec (map-indexed (fn [i s] (if (>= s 6) (+ s per (if (< i rem) 1 0)) s)) base))]
                    (into base' (repeat (- short extra) 1)))
      :else (loop [v base t tot]
              (if (or (<= t target) (empty? v)) (into v (repeat (- target t) 1))
                  (let [s (peek v)] (recur (clojure.core/pop v) (- t s))))))))

(defn cell-persons
  "One cell → [{:AGEGRP … :hh … :size …} …]. Ages come from the filled 5-year
   histogram, households from the filled size histogram; persons are placed
   into households adult-first so no household is children only."
  [c age-profile hh-profile ^java.util.Random rng]
  (let [pop (long (or (:population c) 0))
        [ak am ar] (histogram (:age c) (mapv first grid-bands) pop)
        ages (fill ak am ar (get age-profile (:stadtteil c) {}))
        ;; 427 populated cells publish no household total; the Stadtteil's own
        ;; mean household size turns their population into a household count
        prof (get hh-profile (:stadtteil c) {})
        mean-size (let [n (reduce + 0 (vals prof))
                        p (reduce + 0 (map (fn [[k s]] (* s (get prof k 0))) hh-bands))]
                    (if (pos? n) (/ (double p) n) 2.0))
        hh-total (or (n* (get (:hh c) :Insgesamt_Haushalte))
                     (max (if (pos? pop) 1 0) (Math/round (/ (double pop) mean-size))))
        [hk hm hr] (histogram (:hh c) (mapv first hh-bands) hh-total)
        sizes (fill hk hm hr prof)
        slots (household-slots sizes pop)
        n-hh (count slots)
        people (shuffled rng (mapcat (fn [[k n]] (repeat n k)) ages))
        adult? (fn [k] (>= (long (band->agegrp k)) 4))
        adults (filterv adult? people) kids (filterv (complement adult?) people)
        na (count adults) nk (count kids)
        out (transient [])
        ai (volatile! 0) ki (volatile! 0)
        room (int-array n-hh)
        emit! (fn [h b size] (conj! out {:AGEGRP (band->agegrp b) :band b :hh h :size size}))]
    ;; pass 1: one adult per household (a child only if the adults run out)
    (dotimes [h n-hh]
      (cond (< @ai na) (do (emit! h (adults @ai) (slots h)) (vswap! ai inc) (aset room h (int (dec (long (slots h))))))
            (< @ki nk) (do (emit! h (kids @ki) (slots h)) (vswap! ki inc) (aset room h (int (dec (long (slots h))))))
            :else (aset room h (int 0))))
    ;; pass 2: children into the remaining slots, largest households first
    (dotimes [h n-hh]
      (while (and (< @ki nk) (pos? (aget room h)))
        (emit! h (kids @ki) (slots h)) (vswap! ki inc) (aset room h (dec (aget room h)))))
    ;; pass 3: the rest of the adults fill what is left
    (dotimes [h n-hh]
      (while (and (< @ai na) (pos? (aget room h)))
        (emit! h (adults @ai) (slots h)) (vswap! ai inc) (aset room h (dec (aget room h)))))
    ;; pass 4: rounding leftovers become their own one-person households
    (loop [h n-hh]
      (when (or (< @ai na) (< @ki nk))
        (if (< @ai na) (do (emit! h (adults @ai) 1) (vswap! ai inc))
            (do (emit! h (kids @ki) 1) (vswap! ki inc)))
        (recur (inc h))))
    (persistent! out)))

(defn school?
  "ATTSCH 1: a pupil (Zensus Schulform count spread over ages 5–19 by the grid
   bands) or a 20–24-year-old in tertiary/vocational education."
  [band ^java.util.Random rng p-school]
  (cond (#{:a5bis9 :a10bis14 :a15bis19} band) (< (.nextDouble rng) (double p-school))
        (= band :a20bis24) (< (.nextDouble rng) (double tertiary-share-20-24))
        :else false))

(defn synthesize!
  "Write data/derived/synth_stuttgart_persons.edn and the cell centroid map.
   Returns the counts the validation report is built from."
  [& {:keys [seed out] :or {seed 7 out persons-path}}]
  (let [cs (cells)
        {age-prof :age hh-prof :hh} (profiles cs)
        pop-by-band (apply merge-with + (vals age-prof))
        emp-rate (employment-rates pop-by-band)
        sexp (sex-ratio-by-band "data/raw/regionalstatistik/12411-04-02-4.csv")
        ;; pupils: the Zensus count spread over the 5–19 bands
        school-pop (reduce + (map #(get pop-by-band % 0) [:a5bis9 :a10bis14 :a15bis19]))
        p-school (min 1.0 (/ (double (:pupils gemeinde)) (max 1.0 school-pop)))
        ;; unemployment: the Gemeinde count over everyone 15–74 who is not employed
        pop15-74 (reduce + (for [[k _ lo _] grid-bands :when (<= 15 lo 70)] (get pop-by-band k 0)))
        emp15-74 (reduce + (for [[k _ lo _] grid-bands :when (<= 15 lo 70)] (* (get pop-by-band k 0) (get emp-rate k 0.0))))
        p-unemp (min 1.0 (/ (double (:unemployed gemeinde)) (max 1.0 (- pop15-74 emp15-74))))
        ^java.util.Random rng (java.util.Random. seed)
        counts (volatile! {:persons 0 :households 0 :employed 0 :unemployed 0 :students 0 :men 0 :women 0
                           :by-agegrp {} :by-stadtbezirk {} :by-stadtteil {} :by-size {}})]
    (io/make-parents out)
    (with-open [w (io/writer out)
                cw (io/writer centroids-path)]
      (doseq [c cs]
        (.write cw (str (json/write-str {:da (:gid c) :lon (:lon c) :lat (:lat c)
                                         :stadtteil (:stadtteil c) :stadtbezirk (:stadtbezirk c)}) "\n"))
        (let [ps (cell-persons c age-prof hh-prof rng)]
          (vswap! counts update :households + (inc (long (reduce max -1 (map :hh ps)))))
          (doseq [p ps]
            (let [b (:band p) g (long (:AGEGRP p))
                  male? (< (.nextDouble rng) (double (get sexp b 0.5)))
                  employed? (and (>= g 3) (< (.nextDouble rng) (double (get emp-rate b 0.0))))
                  unemployed? (and (not employed?) (<= 3 g 12) (< (.nextDouble rng) (double p-unemp)))
                  att (if (school? b rng p-school) 1 2)
                  lfact (cond employed? 1 unemployed? 9 :else 11)
                  row {:AGEGRP g :GENDER (if male? 2 1) :LFACT lfact
                       :NAICS 0 :NOC21 0 :MODE 0 :ATTSCH att
                       :da (:gid c) :la (:stadtteil c) :hh (:hh p) :size (:size p)}]
              (.write w (pr-str row)) (.write w "\n")
              (vswap! counts
                      (fn [m]
                        (-> m (update :persons inc)
                            (update :employed + (if (= 1 lfact) 1 0))
                            (update :unemployed + (if (= 9 lfact) 1 0))
                            (update :students + (if (= 1 att) 1 0))
                            (update :men + (if male? 1 0))
                            (update :women + (if male? 0 1))
                            (update-in [:by-agegrp g] (fnil inc 0))
                            (update-in [:by-size (:size p)] (fnil inc 0))
                            (update-in [:by-stadtbezirk (:stadtbezirk c)] (fnil inc 0))
                            (update-in [:by-stadtteil (:stadtteil c)] (fnil inc 0))))))))))
    (assoc @counts :p-school p-school :p-unemployed p-unemp
           :employment-rates (into (sorted-map) (map (fn [[k v]] [k (/ (Math/round (* 1000.0 v)) 1000.0)])) emp-rate)
           :sex-ratio (into (sorted-map) (map (fn [[k v]] [k (/ (Math/round (* 1000.0 v)) 1000.0)])) sexp)
           :cells (count cs) :out out)))

;; ---- validation against the resident register -------------------------------------

(def register-path "data/raw/stuttgart/einwohner_altersgruppen_stadtbezirke.csv")

(def register-bands
  "The register's 10 age groups → the six coarse bands on which the register
   and the PUMF AGEGRP scale agree exactly: both cut at 0/15/30/45/65/75.
   AGEGRP 11 is 55–64, so the register's 45–60 and 60–65 have to be pooled;
   no finer age comparison than this one is meaningful."
  {"0 bis unter 3 Jahre" :a0-14 "3 bis unter 6 Jahre" :a0-14 "6 bis unter 15 Jahre" :a0-14
   "15 bis unter 18 Jahre" :a15-29 "18 bis unter 30 Jahre" :a15-29
   "30 bis unter 45 Jahre" :a30-44
   "45 bis unter 60 Jahre" :a45-64 "60 bis unter 65 Jahre" :a45-64
   "65 bis unter 75 Jahre" :a65-74
   "75 Jahre oder älter" :a75+})

(defn register
  "Stuttgart's resident register (opendata.stuttgart.de, ISO-8859-1) at the
   latest Stichtag → {:total n :by-bezirk {} :by-band {}}."
  [& {:keys [stichtag] :or {stichtag "31.12.2022"}}]
  (let [rows (with-open [r (io/reader register-path :encoding "ISO-8859-1")]
               (->> (line-seq r) rest
                    (map #(str/split % #";"))
                    (filter #(= 4 (count %)))
                    (filter #(= stichtag (first %)))
                    vec))]
    {:stichtag stichtag
     :total (reduce + (map #(Long/parseLong (nth % 3)) rows))
     :by-bezirk (reduce (fn [m [_ b _ n]] (update m b (fnil + 0) (Long/parseLong n))) {} rows)
     :by-band (reduce (fn [m [_ _ a n]] (update m (register-bands a) (fnil + 0) (Long/parseLong n))) {} rows)}))

(def agegrp->band
  {1 :a0-14 2 :a0-14 3 :a15-29 4 :a15-29 5 :a15-29 6 :a30-44 7 :a30-44 8 :a30-44
   9 :a45-64 10 :a45-64 11 :a45-64 12 :a65-74 13 :a75+})

(defn validate
  "Synthetic totals vs the register, per Stadtbezirk and per coarse age band.
   AGEGRP 11 is 55–64 and 12 is 65–74, so the synthetic 45–59/60–74 split is
   approximate at the 60–64 boundary; that is stated with the numbers."
  [counts & {:keys [stichtag] :or {stichtag "31.12.2022"}}]
  (let [reg (register :stichtag stichtag)
        pct (fn [a b] (if (pos? b) (/ (Math/round (* 1000.0 (/ (- (double a) b) b))) 10.0) nil))
        bez (vec (sort-by #(- (Math/abs (double (or (:err-pct %) 0))))
                          (for [[b n] (:by-bezirk reg)
                                :let [s (get (:by-stadtbezirk counts) b 0)]]
                            {:stadtbezirk b :register n :synthetic s :err (- s n) :err-pct (pct s n)})))
        syn-band (reduce (fn [m [g n]] (update m (agegrp->band g) (fnil + 0) n)) {} (:by-agegrp counts))
        bands (vec (for [k [:a0-14 :a15-29 :a30-44 :a45-64 :a65-74 :a75+]
                         :let [r (get (:by-band reg) k 0) s (get syn-band k 0)]]
                     {:band k :register r :synthetic s :err (- s r) :err-pct (pct s r)}))]
    {:stichtag stichtag
     :total {:register (:total reg) :synthetic (:persons counts)
             :err (- (:persons counts) (:total reg)) :err-pct (pct (:persons counts) (:total reg))}
     :stadtbezirke bez
     :age-bands bands
     :worst-bezirk-pct (apply max (map #(Math/abs (double (or (:err-pct %) 0))) bez))
     :mean-abs-bezirk-pct (/ (Math/round (* 10.0 (/ (reduce + (map #(Math/abs (double (or (:err-pct %) 0))) bez)) (count bez)))) 10.0)}))

(defn centroids
  "cell gid → [lon lat], the map `city.sim.cityworld/persons-columns` takes."
  []
  (with-open [r (io/reader centroids-path)]
    (into {} (for [l (line-seq r) :let [m (json/read-str l :key-fn keyword)]]
               [(:da m) [(:lon m) (:lat m)]]))))
