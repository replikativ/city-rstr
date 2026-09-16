(ns city.synth.stuttgart-firms
  "A synthetic firm register for Stuttgart.

   Germany publishes no establishment-level register: the Unternehmensregister
   is counts only. So the *locations* come from Overture Places and the
   *sizes* come from marginals:

   - Regionalstatistik 52111-01-02-4 — Niederlassungen of Kreis 08111 by the
     four size classes 0–9 / 10–49 / 50–249 / 250+.
   - 52111-02-01-4 and 52111-07-01-4 — Niederlassungen and abhängig
     Beschäftigte by WZ-2008 section, same Kreis, same year.
   - opendata.stuttgart.de `unternehmen_svb_stadtbezirke.csv` — firms and
     SvB per Stadtbezirk × section, 2020: the only spatially resolved source.

   Each place is mapped to a WZ section by its Overture category, drawn a size
   from the section's own size distribution (the city-wide class distribution
   exponentially tilted to the section's mean size), and then the whole
   Stadtbezirk × section cell is scaled to the CKAN employee total."
  (:require [city.synth.anchors :as anc]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]))

(def places-path "data/derived/stuttgart_places.jsonl")
(def overture-path "data/raw/overture-places/stuttgart_bbox.jsonl")
(def klgl-path "data/derived/stuttgart_areas.jsonl")
(def out-path "data/derived/firms/stuttgart-2025.json")
(def summary-path "data/derived/firms/stuttgart-2025-stadtteile.json")
(def ckan-path "data/raw/stuttgart/unternehmen_svb_stadtbezirke.csv")

;; ---- WZ 2008 sections --------------------------------------------------------------

(def wz-names
  {"BDE" "Bergbau, Energie- und Wasserversorgung"
   "C" "Verarbeitendes Gewerbe"
   "F" "Baugewerbe"
   "G" "Handel; Instandhaltung und Reparatur von Kraftfahrzeugen"
   "H" "Verkehr und Lagerei"
   "I" "Gastgewerbe"
   "J" "Information und Kommunikation"
   "K" "Erbringung von Finanz- und Versicherungsdienstleistungen"
   "L" "Grundstücks- und Wohnungswesen"
   "M" "Erbringung von freiberuflichen, wissenschaftlichen und technischen Dienstleistungen"
   "N" "Erbringung von sonstigen wirtschaftlichen Dienstleistungen"
   "O" "Öffentliche Verwaltung, Verteidigung, Sozialversicherung"
   "P" "Erziehung und Unterricht"
   "Q" "Gesundheits- und Sozialwesen"
   "R" "Kunst, Unterhaltung und Erholung"
   "S" "Erbringung von sonstigen Dienstleistungen"})

(def not-an-establishment
  "Overture categories that are infrastructure, not a workplace. They stay in
   the firm file (they are real destinations) but get zero employees, so
   `assign-workplaces-grid!` never sends anyone to work in a car park."
  #"(?x) ^(atms?|parking|ev_charging_station|landmark_and_historical_building|
        park|public_bathroom|bus_stop|tram_stop|taxi_stand|bicycle_parking|
        monument|fountain|picnic_area|playground|cemetery|bench|
        recycling|waste_disposal|toilet.*|viewpoint|rest_area|
        lake|river|forest|mountain|beach|island|nature_preserve|
        hiking_trail|garden|pond|waterfall|valley|hill|meadow)$")

(def category-rules
  "Overture category → WZ 2008 section. A prioritised keyword table: the first
   pattern that matches the category string wins, so the specific rules
   (church → S, driving_school → P) sit above the generic ones (school → P).
   Everything unmatched falls to S, 'sonstige Dienstleistungen', which is what
   the section is for.

   The mapping is the hand table doc/simulator.md documents; it is coarse by
   construction — Overture's 1,059 Stuttgart categories carry no legal-form or
   sector code, so this is a naming heuristic, not a classification."
  [;; food and lodging first: 'restaurant' appears inside many compounds
   [#"restaurant|cafe|coffee|bar$|^bar_|(^|_)pub($|_)|bistro|brewery|brasserie|diner|food_court|ice_cream|juice|tea_house|nightclub|hotel|hostel|motel|bed_and_breakfast|guest_house|caterer|catering|banquet" "I"]
   ;; education
   [#"school|university|college|kindergarten|preschool|education|tutor|academy|library|driving_school|language" "P"]
   ;; health and social
   [#"dentist|doctor|physician|physical_therapy|hospital|clinic|medical|health|pharmacy|optician|eyewear|veterinar|psycholog|therap|midwife|nursing|retirement_home|elder|childcare|child_care|day_care|assisted_living|diagnostic|laborator|orthope|dermatolog|radiolog|chiroprac|naturopathic|blood|ambulance|senior" "Q"]
   ;; professional / scientific / technical
   [#"lawyer|attorney|legal|_law($|_)|law_(firm|office)|notar|accountant|tax_|auditor|architect|engineering|engineer|consult|advertis|marketing|market_research|design|photograph|translation|patent|surveyor|research|laboratory_services|management_services|public_relations|recruit(ing|ment)_consult|professional_services|corporate_office|business_services" "M"]
   ;; information and communication
   [#"software|information_technology|it_service|computer|web_|internet|telecom|publisher|publishing|newspaper_publish|broadcast|radio_station|tv_|television|film_production|video_production|data_|hosting|app_|media_(agency|production)|news_(agency|service)" "J"]
   ;; finance and insurance
   [#"bank|credit_union|insurance|financial|investment|mortgage|currency_exchange|stock|broker|trusts|pension|atm_service" "K"]
   ;; real estate
   [#"real_estate|property_management|apartment_rental|estate_agent|letting" "L"]
   ;; transport and storage
   [#"shipping|freight|cargo|courier|logistics|warehous|storage|train_station|airport|airline|bus_(company|station|line)|taxi|removals|moving_company|seaport|parking_garage_operator|transportation" "H"]
   ;; construction
   [#"contractor|construction|plumb|electrician|roof|mason|painting|carpent|hvac|heating|insulation|scaffold|excavat|paving|drywall|glazier|flooring_install|renovat|demolition" "F"]
   ;; manufacturing
   [#"manufactur|factory|brewer(y|ies)_production|bakery_production|printing_services|printer_manufact|foundry|machin(e|ing)_shop|fabricat|winery|distiller|textile_mill|sawmill|industrial_equipment|metal_(supplier|works)|plastics|chemical|assembly" "C"]
   ;; utilities / mining
   [#"power_plant|utility|utilities|water_supply|sewage|waste_management|gas_supplier|energy_(company|supplier)|mining|quarry|solar_(installer|company)" "BDE"]
   ;; public administration
   [#"government|public_service|public_administration|embassy|consulate|courthouse|police|fire_(station|department)|military|city_hall|town_hall|post_office_government|social_security|customs|tax_office" "O"]
   ;; arts, entertainment, recreation
   [#"museum|gallery|theat(er|re)|cinema|music_venue|concert|stadium|sports_club|gym|fitness|yoga|martial_arts|dance_club|bowling|casino|amusement|zoo|aquarium|swimming_pool|golf|tennis|ski_(resort|school)|skiing|climbing|recreation|arts_and_entertainment|active_life|leisure|betting|lottery" "R"]
   ;; retail and vehicle trade (broad, so it comes after the specific ones)
   [#"store|shop|market|retail|dealer|supermarket|grocer|butcher|bakery|florist|flowers|pharmac(y|ies)|kiosk|boutique|shopping|wholesal|automotive_(repair|services)|car_(wash|repair|dealer|rental)|gas_station|tire|auto_parts|motorcycle|bicycle_(shop|store)|newsstand|antique|pawn|electronics|appliance|hardware_store|drugstore|perfumery|toy(s|_)|sporting_goods|liquor|beverage_store|garden_cent" "G"]
   ;; other business services
   [#"employment_agenc|staffing|temp_agency|travel_agen|travel_services|tour_operator|cleaning|janitor|security_service|landscap|gardener|pest_control|call_center|rental|leasing|packaging|copy_shop|office_services|business_to_business|trade_show|party_and_event|event_planning|facility" "N"]
   ;; personal and other services (the default, made explicit for the common ones)
   [#"hair|barber|beauty|nail|spa|massage|tattoo|piercing|tanning|laundry|dry_clean|tailor|shoe_repair|watch_repair|funeral|church|mosque|synagogue|temple|religious|association|union|non_profit|non-profit|community_services|charity|club$|repair" "S"]])

(defn wz-of
  "WZ section for an Overture category, or nil for infrastructure."
  [category]
  (let [c (str/lower-case (str (or category "")))]
    (cond
      (str/blank? c) "S"
      (re-find not-an-establishment c) nil
      :else (or (some (fn [[re s]] (when (re-find re c) s)) category-rules) "S"))))

;; ---- the Kreis marginals -----------------------------------------------------------

(def size-classes
  "URS size classes with the bounds a draw is log-uniform between. The top
   bound of the 250+ class is not published; 1,300 is the value at which the
   four class means reproduce the Kreis's own employee total (499,665 over
   32,158 Niederlassungen in 2024), so it is calibrated, not assumed."
  [{:class :c0-9 :lo 0.8 :hi 9.5} {:class :c10-49 :lo 10 :hi 49}
   {:class :c50-249 :lo 50 :hi 249} {:class :c250+ :lo 250 :hi 1300}])

(defn- logu-mean [{:keys [lo hi]}] (/ (- (double hi) lo) (Math/log (/ (double hi) lo))))

(defn- csv-rows
  "A Regionalstatistik flat CSV → the data lines split on ';' (latin-1)."
  [path]
  (with-open [r (io/reader path :encoding "ISO-8859-1")]
    (->> (line-seq r) (map #(str/split % #";" -1)) (filterv #(re-matches #"\d{4}" (str (first %)))))))

(defn- n* [s] (let [s (str/trim (str s))] (when (re-matches #"-?\d+" s) (Long/parseLong s))))

(def urs-section-order
  "Column order of 52111-02-01-4 / -07-01-4 after the three key columns."
  ["Insgesamt" "B" "C" "D" "E" "F" "G" "H" "I" "J" "K" "L" "M" "N" "P" "Q" "R" "S"])

(defn urs
  "Kreis 08111 Unternehmensregister marginals for `year`:
   {:classes {:c0-9 n …} :firms {section n} :employees {section n}}.
   B, D and E are pooled into BDE to match the CKAN table's own grouping."
  [& {:keys [year dir] :or {year 2024 dir "data/raw/regionalstatistik"}}]
  (let [row (fn [code] (first (filter #(= (str year) (str/trim (first %))) (csv-rows (str dir "/" code ".csv")))))
        sz (row "52111-01-02-4")
        fr (row "52111-02-01-4")
        em (row "52111-07-01-4")
        by-section (fn [r] (into {} (for [[i s] (map-indexed vector urs-section-order)
                                          :when (not= s "Insgesamt")
                                          :let [v (n* (nth r (+ 3 i) nil))] :when v]
                                      [s v])))
        pool (fn [m] (-> (apply dissoc m ["B" "D" "E"])
                         (assoc "BDE" (reduce + 0 (keep m ["B" "D" "E"])))))]
    {:year year
     :classes (zipmap (map :class size-classes) (map #(n* (nth sz (+ 4 %) nil)) (range 4)))
     :firms (pool (by-section fr))
     :employees (pool (by-section em))}))

(defn tilted-class-probs
  "The city-wide class distribution, exponentially tilted so its mean employee
   count equals the section's own (MaxEnt under one moment constraint):
   p(c) ∝ p0(c)·exp(θ·μ_c), θ found by bisection. Sections whose mean lies
   outside what the classes can produce clamp at the extremes."
  [p0 mu target]
  (let [f (fn [th] (let [w (mapv #(* %1 (Math/exp (* th %2))) p0 mu)
                         s (reduce + w)]
                     (/ (reduce + (map * w mu)) s)))]
    (cond
      (<= target (apply min mu)) (mapv #(if (= % (apply min mu)) 1.0 0.0) mu)
      (>= target (apply max mu)) (mapv #(if (= % (apply max mu)) 1.0 0.0) mu)
      :else (let [th (loop [lo -1.0 hi 1.0 i 0]
                       (let [m (/ (+ lo hi) 2.0)]
                         (cond (= i 80) m
                               (< (f m) target) (recur m hi (inc i))
                               :else (recur lo m (inc i)))))
                  w (mapv #(* %1 (Math/exp (* th %2))) p0 mu)
                  s (reduce + w)]
              (mapv #(/ % s) w)))))

(defn section-distributions
  "{section [p(class) …]} for every WZ section, plus the class means."
  [{:keys [classes firms employees]}]
  (let [mu (mapv logu-mean size-classes)
        tot (reduce + (vals classes))
        p0 (mapv #(/ (double (get classes (:class %) 0)) tot) size-classes)
        overall (/ (double (reduce + (vals employees))) (reduce + (vals firms)))]
    {:mu mu :p0 p0 :overall-mean overall
     :by-section (into {} (for [[s n] firms
                                :let [e (get employees s)
                                      m (if (and e (pos? n)) (/ (double e) n) overall)]]
                            [s (tilted-class-probs p0 mu m)]))}))

;; ---- the CKAN Stadtbezirk × section table ------------------------------------------

(defn ckan
  "opendata.stuttgart.de firms and SvB per Stadtbezirk × WZ section (2020).
   → {[bezirk section] {:firms n :employees n}} plus the two margins."
  []
  (let [rows (with-open [r (io/reader ckan-path :encoding "ISO-8859-1")]
               (->> (line-seq r) rest (map #(str/split % #";" -1)) (filterv #(= 5 (count %)))))
        sect (fn [label] (let [[_ letters] (re-find #"^([A-Z](?:, [A-Z])*)\s" label)]
                           (when letters (let [ls (str/split letters #", ")]
                                           (if (< 1 (count ls)) (str/join "" ls) (first ls))))))
        cells (reduce (fn [m [_ bez label f e]]
                        (let [s (sect label)]
                          (if (and s (n* f))
                            (update m [bez s] (fn [c] (merge-with + (or c {:firms 0 :employees 0})
                                                                  {:firms (n* f) :employees (or (n* e) 0)})))
                            m)))
                      {} rows)]
    {:cells cells
     :employees-total (reduce + (map (comp :employees val) cells))
     :firms-total (reduce + (map (comp :firms val) cells))}))

;; ---- the draw ----------------------------------------------------------------------

(defn cache-places!
  "Overture places located into Stuttgart's Stadtteile, cached to JSONL.

   This repeats `city.load.stuttgart/load-overture!`'s point-in-polygon
   assignment locally instead of reading `:entity/area` back out of the store:
   the store's *place* → area refs are broken (an earlier `load-overture!` ran
   with a `stadtteile` that returned the area **name**, so a string went into a
   ref attribute and created phantom entities — `repair-area-links!` exists for
   exactly this and has not been run over all of them). The cells are fine and
   are still read from the store; only the places are re-located here, from the
   same two adopted files the loader uses."
  []
  (let [locate (requiring-resolve 'city.geo.core/locate)
        with-bbox (requiring-resolve 'city.geo.core/with-bbox)
        recs (with-open [r (io/reader klgl-path)] (mapv #(json/read-str % :key-fn keyword) (line-seq r)))
        bezirk (into {} (for [a recs :when (= "stadtbezirk" (:level a))] [(:nr a) (:name a)]))
        teile (vec (for [a recs :when (= "stadtteil" (:level a))]
                     (with-bbox {:name [(:name a) (bezirk (:parent_nr a))] :geometry (:geometry a)})))
        n (volatile! 0)]
    (io/make-parents places-path)
    (with-open [r (io/reader overture-path) w (io/writer places-path)]
      (doseq [l (line-seq r)
              :let [{:keys [id name category websites lon lat]} (json/read-str l :key-fn keyword)
                    a (when (and lon lat) (locate teile [lon lat]))]
              :when a]
        (vswap! n inc)
        (.write w (json/write-str {:eid (Math/abs (long (hash id))) :ext-id (str "overture:" id)
                                   :name name :lon lon :lat lat :category category
                                   :website (first websites)
                                   :stadtteil (first a) :stadtbezirk (second a)}))
        (.write w "\n")))
    {:places @n :path places-path}))

(defn places [] (with-open [r (io/reader places-path)] (mapv #(json/read-str % :key-fn keyword) (line-seq r))))

(defn- draw-size ^long [^java.util.Random rng probs]
  (let [u (.nextDouble rng)
        i (loop [i 0 acc 0.0]
            (if (or (= i (dec (count probs))) (< u (+ acc (nth probs i)))) i (recur (inc i) (+ acc (nth probs i)))))
        {:keys [lo hi]} (nth size-classes i)
        x (* lo (Math/pow (/ (double hi) lo) (.nextDouble rng)))]
    (max 0 (Math/round x))))

(defn build!
  "Draw a size for every Overture place, scale each Stadtbezirk × section cell
   to the CKAN employee total, and write the firm file plus a per-Stadtteil
   summary. Cells the CKAN table does not cover (section O, and any cell with
   no CKAN row) keep their drawn sizes; that is reported, not hidden."
  [& {:keys [seed year] :or {seed 11 year 2024}}]
  (let [ps (places)
        marg (urs :year year)
        {:keys [by-section p0]} (section-distributions marg)
        overall (:overall-mean (section-distributions marg))
        rng (java.util.Random. seed)
        drawn (mapv (fn [p]
                      (let [s (wz-of (:category p))
                            ;; section O is outside the Unternehmensregister; it draws
                            ;; from the city-wide class distribution instead
                            probs (get by-section s p0)]
                        (assoc p :wz s
                               :drawn (if s (draw-size rng probs) 0))))
                    ps)
        ;; the target table: the Kreis's own section employment (URS, all
        ;; employers) distributed over Stadtbezirke by the CKAN table's shares.
        ;; CKAN alone would be wrong as a level — it covers 311,797 of the
        ;; 435,469 SvB the BA counts at workplaces in Stuttgart, and its
        ;; coverage is worst exactly where Overture is best (Gastgewerbe:
        ;; 6,456 against the URS's 25,578) — but it is the only source that
        ;; says *where in the city* a section's jobs are.
        {:keys [cells]} (ckan)
        ck-by-section (reduce (fn [m [[_ sec] v]] (update m sec (fnil + 0) (:employees v))) {} cells)
        targets (into {} (for [[[bez sec] v] cells
                               :let [tot (get ck-by-section sec 0)
                                     urs-e (get (:employees marg) sec)]
                               :when (and urs-e (pos? tot))]
                           [[bez sec] (* (double urs-e) (/ (double (:employees v)) tot))]))
        by-cell (group-by (fn [p] [(:stadtbezirk p) (:wz p)]) (filter :wz drawn))
        ;; a (Bezirk, section) pair the CKAN table does not list is a pair it
        ;; asserts has no employment: those places fall to the one-person
        ;; floor rather than keeping an unconstrained draw. Section O has no
        ;; target at all (it is outside both registers) and keeps its draw.
        scaled (into {} (for [[k ps] by-cell
                              :let [tgt (get targets k)
                                    sum (reduce + (map :drawn ps))]]
                          [k (cond (and tgt (pos? sum)) (/ tgt sum)
                                   (= "O" (second k)) 1.0
                                   :else 0.0)]))
        uncovered (count (for [[k _] by-cell :when (and (nil? (get targets k)) (not= "O" (second k)))] k))
        firms (vec (for [p drawn
                         :let [f (get scaled [(:stadtbezirk p) (:wz p)] 1.0)
                               ;; an establishment employs at least the person running it;
                               ;; infrastructure (:wz nil) stays at zero so nobody works there
                               e (if (:wz p) (max 1 (long (Math/round (* f (double (:drawn p)))))) 0)]]
                     {:eids [(:eid p)] :name (:name p) :lon (:lon p) :lat (:lat p)
                      :licence-type (when (:wz p) (str (:wz p) " " (get wz-names (:wz p))))
                      :employees e :storefront-category nil :place-category (:category p)
                      ;; there is no observed storefront inventory, so retail (G)
                      ;; and hospitality (I) stand in for one: those are the
                      ;; categories whose visits the storefront aggregate is about
                      :kinds (if (#{"G" "I"} (:wz p)) ["place" "storefront"] ["place"])
                      :website (when-not (str/blank? (:website p)) (:website p))
                      :area (:stadtteil p) :stadtbezirk (:stadtbezirk p) :wz (:wz p)}))
        ;; Measured employers last. The raking above is only as good as its
        ;; carriers, and Overture has no object for the Untertürkheim works, so
        ;; that cell's jobs land on whatever *is* there — three wineries, in the
        ;; case that prompted this. `city.synth.anchors` puts the published
        ;; headcounts on the sites they belong to, subtracts them from the cell
        ;; targets, and re-rakes the remainder, so the register's city total is
        ;; preserved while its top end stops being fiction.
        anchored (let [m (anc/match firms)]
                   (when (seq (:matches m))
                     (let [a (anc/apply-anchors firms (:matches m))]
                       {:firms (-> (anc/rerake (:firms a) (:residual-targets a))
                                   ;; and hold the result to the city's published
                                   ;; count of large establishments per section
                                   (anc/cap-size-classes))
                        :placed (:placed a) :outside (:outside a)
                        :matched (count (:matches m))})))
        firms (or (:firms anchored) firms)]
    (io/make-parents out-path)
    (spit out-path (json/write-str {:firms firms :count (count firms)}))
    (let [by-st (reduce (fn [m f] (-> m (update-in [(:area f) :firms] (fnil inc 0))
                                      (update-in [(:area f) :employees] (fnil + 0) (:employees f))))
                        {} firms)]
      (spit summary-path (json/write-str {:year year
                                          :stadtteile (vec (sort-by #(- (:employees %))
                                                                    (for [[k v] by-st] (assoc v :stadtteil k))))})))
    {:places (count ps) :firms (count firms)
     :zero-employee (count (filter #(zero? (:employees %)) firms))
     :infrastructure (count (remove :wz drawn))
     :employees (reduce + (map :employees firms))
     :ckan-employees (:employees-total (ckan))
     :urs-employees (reduce + (vals (:employees marg)))
     :cell-targets (count targets)
     :cells-without-target uncovered
     :overall-mean-size (/ (Math/round (* 10.0 overall)) 10.0)
     :by-section (into (sorted-map) (frequencies (keep :wz drawn)))
     :employees-by-section (into (sorted-map) (reduce (fn [m f] (update m (:wz f) (fnil + 0) (:employees f))) {} firms))
     :out out-path :summary summary-path}))

;; ---- commuting ---------------------------------------------------------------------

(def commute-path "data/derived/stuttgart_commute_shares.edn")

(defn commute-shares!
  "The three numbers `city.sim.cityworld/build` needs, from the Bundesagentur
   für Arbeit Gemeindedaten (Beschäftigungsstatistik, 30.06.2024), Gemeinde
   08111000: SvB am Wohnort 267,688, am Arbeitsort 442,289, Wohnort = Arbeitsort
   165,914, Einpendler 276,247, Auspendler 101,756.

   BA counts only sozialversicherungspflichtig Beschäftigte — no self-employed,
   no Beamte, no marginal-only jobs. The Zensus 2022 counts 315,900
   Erwerbstätige living in Stuttgart, so SvB cover 84.7 % of employed
   residents; the job count is lifted by the same factor on the assumption
   that the uncovered employment commutes like the covered kind."
  [& {:keys [ba]
      :or {ba {:svb-wohnort 267688 :svb-arbeitsort 442289 :both 165914
               :einpendler 276247 :auspendler 101756 :stichtag "2024-06-30"}}}]
  (let [{:keys [svb-wohnort svb-arbeitsort both]} ba
        employed-residents 315900                 ;; Zensus 2022 Erwerbstätige am Wohnort
        k (/ (double employed-residents) svb-wohnort)
        shares {:source :ba-gemeindedaten
                :ba ba
                :zensus-employed-residents employed-residents
                :svb-coverage (/ (Math/round (* 1000.0 (/ 1.0 k))) 1000.0)
                :residents-with-workplace employed-residents
                :share-work-in-city (/ (Math/round (* 10000.0 (/ (double both) svb-wohnort))) 10000.0)
                :jobs-in-city (long (Math/round (* k (double svb-arbeitsort))))
                :share-jobs-held-by-residents (/ (Math/round (* 10000.0 (/ (double both) svb-arbeitsort))) 10000.0)
                :note (str "BA Gemeindedaten " (:stichtag ba) "; jobs-in-city = SvB am Arbeitsort × "
                           "(Zensus Erwerbstätige am Wohnort / SvB am Wohnort). Germany has no "
                           "'no fixed workplace' census category, so every employed resident has "
                           "a workplace and the no-fixed-workplace role is empty.")}]
    (io/make-parents commute-path)
    (spit commute-path (pr-str shares))
    shares))

(defn shares [] (read-string (slurp commute-path)))
