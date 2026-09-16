(ns city.ui.city-panels
  "The explorer's side panels: observed records with their provenance, visits
   by hour, the economic scorecard, area rates and flows, and the scenario
   report (posterior particles, calibration, district and venue changes).

   This namespace is deliberately a pure renderer: its caller owns requests,
   clocks and selection state.  `render!` only replaces the supplied element's
   contents with a view of the payloads it has been given."
  (:require [clojure.string :as str]))

(def ^:private blue "#526d82")
(def ^:private amber "#b47a32")
(def ^:private ink "#596168")
(def ^:private pale "#d9dee1")

(defn- esc [x]
  (-> (str (or x ""))
      (str/replace "&" "&amp;")
      (str/replace "<" "&lt;")
      (str/replace ">" "&gt;")
      (str/replace "\"" "&quot;")
      (str/replace "'" "&#39;")))

(defn- value [m k]
  (when (map? m)
    (if (contains? m k) (get m k) (get m (name k)))))

(defn- present? [m k]
  (and (map? m) (or (contains? m k) (contains? m (name k)))))

(defn- finite-number? [x]
  (and (number? x) (js/Number.isFinite x)))

(defn- fmt
  ([x] (fmt x 2))
  ([x digits]
   (cond
     (nil? x) "—"
     (finite-number? x)
     (.toLocaleString x "en-GB" #js {:maximumFractionDigits digits})
     :else (esc x))))

(defn- label [x]
  (-> (cond (keyword? x) (name x) :else (str x))
      (str/replace #"[-_]" " ")
      (str/replace #"/" " / ")))

(defn- section [title source body & [hint]]
  (str "<section class='city-section'><div class='section-label'>" (esc source)
       "</div><h2>" (esc title) "</h2>" body
       (when hint (str "<p class='hint'>" (esc hint) "</p>")) "</section>"))

(defn- state-note [kind status]
  (let [s (or (value status :status) :missing)
        msg (value status :message)]
    (str "<p class='hint' role='status'>"
         (case (keyword (name s))
           :loading (str "Loading " kind "…")
           :error (str kind " could not be loaded" (when (seq (str msg)) (str ": " (esc msg))))
           :missing (str (or (when (seq (str msg)) (esc msg)) (str "No " kind " payload is available.")))
           (str (or (when (seq (str msg)) (esc msg)) (str "No " kind " data is available."))))
         "</p>")))

(defn- ready? [payloads statuses k]
  (= :ready (some-> (value statuses k) (value :status) name keyword)))

(defn- payload-block [payloads statuses k kind draw]
  (if (ready? payloads statuses k)
    (draw (value payloads k))
    (state-note kind (value statuses k))))

(defn- table [headers rows]
  (str "<div class='city-table-wrap'><table class='city-table'><thead><tr>"
       (apply str (for [h headers] (str "<th scope='col'>" (esc h) "</th>")))
       "</tr></thead><tbody>"
       (apply str
              (for [row rows]
                (str "<tr>"
                     (apply str (map-indexed
                                 (fn [i cell]
                                   (str (if (zero? i) "<th scope='row'>" "<td>")
                                        cell (if (zero? i) "</th>" "</td>"))) row))
                     "</tr>")))
       "</tbody></table></div>"))

(defn- empty-note [what]
  (str "<p class='hint'>The payload is ready and contains no " (esc what) ".</p>"))

(defn- map-rows [m]
  (sort-by (fn [[_ n]] (- (if (number? n) n 0))) (or m {})))

(defn- observed-summary [summary]
  (if-not (map? summary)
    (empty-note "observed summary")
    (let [simple (fn [k title]
                   (str "<details data-detail='observed-" (esc (name k)) "' open><summary>" (esc title) "</summary>"
                        (cond
                          (not (present? summary k)) (state-note (str/lower-case title) nil)
                          (empty? (value summary k)) (empty-note (str/lower-case title))
                          :else (table [title "Observed count"]
                                       (for [[n c] (map-rows (value summary k))]
                                         [(esc n) (fmt c 0)]))) "</details>"))]
      (str
       (simple :kinds "Entities by kind")
       (simple :storefront-categories "Storefronts (2024) by category")
       "<details data-detail='observed-licence-types'><summary>Licences (2025), top types</summary>"
       (cond
         (not (present? summary :licence-types)) (state-note "licence summary" nil)
         (empty? (value summary :licence-types)) (empty-note "licence types")
         :else (table ["Licence type" "Observed licences" "Reported employees"]
                      (for [r (value summary :licence-types)]
                        [(esc (value r :type)) (fmt (value r :count) 0)
                         (fmt (value r :employees) 0)])))
       "</details><details data-detail='observed-lots-by-zoning'><summary>Assessed lots by zoning</summary>"
       (cond
         (not (present? summary :lots-by-zoning)) (state-note "zoning summary" nil)
         (empty? (value summary :lots-by-zoning)) (empty-note "zoning rows")
         :else (table ["Zoning" "Observed lots" "Land value (CAD)" "Improvement value (CAD)"]
                      (for [r (sort-by #(or (value % :land-value) 0) > (value summary :lots-by-zoning))]
                        [(esc (value r :zoning)) (fmt (value r :lots) 0)
                         (fmt (value r :land-value) 0) (fmt (value r :improvement-value) 0)])))
       "</details>"
       (simple :place-categories "Overture places by category")))))

(defn- provenance [meta]
  (if-not (map? meta)
    (empty-note "run metadata")
    (let [cfg (value meta :config)
          identity-rows [[:city (value meta :city)] [:seed (value meta :seed)]
                         [:days (value meta :days)] [:months (value meta :months)]
                         [:published-at (value meta :published-at)]
                         [:persons (value meta :persons)] [:firms (value meta :firms)]]]
      (str "<div class='source'><p><strong>Published simulation run.</strong> The timestamp identifies publication, not the dates of the observed inputs.</p>"
           (table ["Run field" "Value"]
                  (for [[k v] identity-rows] [(esc (label k)) (fmt v)])) "</div>"
           "<details data-detail='run-config'><summary>Effective run configuration</summary>"
           (if (seq cfg)
             (table ["Parameter" "Effective value"]
                    (for [[k v] (sort-by (comp str key) cfg)]
                      [(esc (label k)) (esc (if (coll? v) (pr-str v) v))]))
             (empty-note "effective configuration fields"))
           "</details>"
           (when-let [world (value meta :world)]
             (str "<details data-detail='run-world'><summary>Published world counts and basis</summary>"
                  (table ["Field" "Value"]
                         (for [[k v] (sort-by (comp str key) world)]
                           [(esc (label k)) (esc (if (coll? v) (pr-str v) v))]))
                  "</details>"))))))

(defn- features [fc] (or (value fc :features) []))

(defn- visits-hours [fc]
  (reduce
   (fn [acc feature]
     (let [hours (value (value feature :properties) :hours)]
       (if (sequential? hours)
         (mapv + acc (mapv #(if (finite-number? %) (max 0 %) 0) (take 24 (concat hours (repeat 0)))))
         acc)))
   (vec (repeat 24 0)) (features fc)))

(defn- visit-chart [fc hour]
  (let [fs (features fc)]
    (if (empty? fs)
      (empty-note "storefront visit features")
      (let [ys (visits-hours fc) mx (max 1 (apply max ys))
            w 640 h 218 left 42 top 15 plot-w 580 plot-h 165 bw (/ plot-w 24)
            selected (if (finite-number? hour) (max 0 (min 23 hour)) 0)
            x (+ left (* bw (+ selected 0.5)))]
        (str "<svg class='city-chart' viewBox='0 0 " w " " h "' role='img' aria-label='Simulated storefront visits by hour with selected hour marker'>"
             "<title>Simulated storefront visits by hour</title>"
             "<line x1='" left "' y1='" (+ top plot-h) "' x2='" (+ left plot-w) "' y2='" (+ top plot-h) "' stroke='" pale "'/><text x='4' y='20' fill='" ink "' font-size='11'>visits</text>"
             (apply str (map-indexed
                         (fn [i y]
                           (let [bh (* plot-h (/ y mx)) bx (+ left (* i bw) 1)]
                             (str "<rect x='" bx "' y='" (- (+ top plot-h) bh) "' width='" (max 1 (- bw 2)) "' height='" bh "' fill='" blue "' opacity='.78'><title>" i ":00 — " (esc (fmt y)) " simulated visits</title></rect>"))) ys))
             "<line x1='" x "' y1='" top "' x2='" x "' y2='" (+ top plot-h) "' stroke='" amber "' stroke-width='3'/><text x='" (max left (- x 18)) "' y='207' fill='" amber "' font-size='11'>selected</text>"
             (apply str (for [i [0 6 12 18 23]]
                          (str "<text x='" (+ left (* bw (+ i 0.5))) "' y='194' text-anchor='middle' fill='" ink "' font-size='11'>" i "</text>")))
             "<text x='622' y='194' text-anchor='end' fill='" ink "' font-size='11'>hour</text></svg>"
             "<p class='hint'>" (fmt (reduce + ys)) " simulated storefront visits across " (fmt (count fs) 0) " storefronts on the modelled weekday.</p>")))))

(defn- unit-label [u]
  (case (str u)
    "eur-per-year" "EUR/year"
    "eur-per-inhabitant-year" "EUR/inhabitant/year"
    (label u)))

(defn- score-value-unit [u]
  ;; report/rows-of carries annual district totals in millions, while the
  ;; per-inhabitant scorer carries literal euros.  The JSON has one generic
  ;; :observed/:predicted pair, so its registry unit is needed to recover the
  ;; display scale.
  (case (str u)
    "eur-per-year" "million EUR/year"
    "eur-per-inhabitant-year" "EUR/inhabitant/year"
    (unit-label u)))

(defn- econ-summary-table [summaries]
  (table ["Registered quantity" "Audit status" "Unit" "Districts" "Observed city total (million EUR)" "Predicted city total (simulated, million EUR)" "Ratio" "Mean |log ratio|" "Base-corrected mean |log ratio|"]
         (for [s summaries]
           [(esc (value s :quantity))
            (if-let [e (value s :error)] (str "error: " (esc e)) (esc (value s :status)))
            (esc (unit-label (value s :unit))) (fmt (value s :n) 0)
            (fmt (value s :city-observed-mio)) (fmt (value s :city-predicted-mio))
            (fmt (value s :city-ratio) 3) (fmt (value s :mean-abs-log-ratio) 3)
            (fmt (value s :mean-abs-log-ratio-base-corrected) 3)])))

(defn- ratio-chart [quantity rows]
  (let [rows (vec (filter #(and (finite-number? (value % :ratio))
                                (not (neg? (value % :ratio)))) rows))
        max-r (max 2 (apply max 1 (map #(value % :ratio) rows)))
        h (+ 42 (* 19 (count rows))) x0 145 pw 455 x1 (+ x0 (* pw (/ 1 max-r)))]
    (if (empty? rows) (empty-note "district ratios for this quantity")
        (str "<svg class='city-chart' viewBox='0 0 640 " h "' role='img' aria-label='Observed to predicted ratios by district for " (esc quantity) "'><title>Observed to predicted ratios by district for " (esc quantity) "</title><line x1='" x1 "' y1='10' x2='" x1 "' y2='" (- h 22) "' stroke='" amber "' stroke-width='2'/><text x='" x1 "' y='" (- h 5) "' text-anchor='middle' fill='" amber "' font-size='10'>1.0 exact</text>"
             (apply str (map-indexed
                         (fn [i r]
                           (let [y (+ 11 (* i 19)) ratio (value r :ratio)]
                             (str "<text x='138' y='" (+ y 10) "' text-anchor='end' fill='" ink "' font-size='10'>" (esc (value r :district)) "</text><rect x='" x0 "' y='" y "' height='12' width='" (* pw (/ ratio max-r)) "' fill='" blue "'><title>" (esc (value r :district)) ": " (fmt ratio 3) " predicted / observed</title></rect>"))) rows)) "</svg>"))))

(defn- econ-panel [econ]
  (let [summaries (vec (or (value econ :summary) [])) rows (vec (or (value econ :rows) []))
        qs (distinct (concat (map #(value % :quantity) summaries) (map #(value % :quantity) rows)))
        summary-by (into {} (map (juxt #(value % :quantity) identity) summaries))]
    (if (and (empty? summaries) (empty? rows))
      (empty-note "registered economic score results")
      (str (if (seq summaries) (econ-summary-table summaries) (empty-note "economic summary rows"))
           (apply str
                  (for [q qs :let [rs (filter #(= q (value % :quantity)) rows)
                                   s (get summary-by q)
                                   unit (score-value-unit (value s :unit))]]
                    (str "<details data-detail='econ-" (esc q) "'><summary>" (esc q) " — district evidence</summary>"
                         (ratio-chart q rs)
                         (if (seq rs)
                           (table ["District" (str "Observed (published), " unit)
                                   (str "Predicted (simulated), " unit) "Predicted / observed"]
                                  (for [r (sort-by #(str (value % :district)) rs)]
                                    [(esc (value r :district)) (fmt (value r :observed))
                                     (fmt (value r :predicted)) (fmt (value r :ratio) 3)]))
                           (empty-note "district rows"))
                         "</details>")))
           "<p class='hint'>Ratios compare model-derived predictions with published observations. A value of 1 is numerical agreement; it does not establish causal validity.</p>"))))

(defn- rate-chart
  "Visits per resident by area, the twenty highest and the five lowest, as a
   bar chart: the shape of the run at a glance, the full table underneath."
  [rows]
  (let [ranked (vec (sort-by #(- (or (value % :visits-per-resident) 0)) (filter #(finite-number? (value % :visits-per-resident)) rows)))
        shown (concat (take 20 ranked) (when (> (count ranked) 25) (take-last 5 ranked)))
        top (max 1e-9 (or (value (first ranked) :visits-per-resident) 1))
        h (+ 30 (* 15 (count shown))) x0 150 pw 460]
    (if (empty? shown) (empty-note "area rates")
        (str "<svg class='city-chart' viewBox='0 0 640 " h "' role='img' aria-label='Storefront visits per resident by area, highest twenty and lowest five'>"
             (apply str (map-indexed
                         (fn [i r]
                           (let [y (+ 8 (* i 15)) v (value r :visits-per-resident) gap? (and (= i 20) (> (count ranked) 25))]
                             (str (when gap? (str "<text x='" x0 "' y='" (+ y 4) "' fill='" ink "' font-size='9'>… " (- (count ranked) 25) " areas between …</text>"))
                                  "<text x='143' y='" (+ y 10) "' text-anchor='end' fill='" ink "' font-size='10'>" (esc (value r :area)) "</text>"
                                  "<rect x='" x0 "' y='" y "' height='11' width='" (* pw (/ v top)) "' fill='" blue "'/>"
                                  "<text x='" (+ x0 4 (* pw (/ v top))) "' y='" (+ y 9) "' fill='" ink "' font-size='9'>" (fmt v 2) "</text>")))
                         shown))
             "</svg>"))))

(defn- od-list [aggregates]
  (let [flows (take 8 (sort-by #(- (or (value % :trips) 0)) (remove #(= (value % :from) (value % :to)) (or (value aggregates :od) []))))]
    (when (seq flows)
      (str "<p class='hint'>Largest flows between areas, sampled resident trips of the weekday: "
           (str/join " · " (for [f flows] (str (esc (value f :from)) " → " (esc (value f :to)) " " (fmt (value f :trips) 0))))
           "</p>"))))

(defn- aggregates-panel [aggregates]
  (let [rows (vec (or (value aggregates :areas) []))]
    (if (empty? rows)
      (str (empty-note "area aggregate rows")
           (when-let [note (value aggregates :note)] (str "<p class='hint'>" (esc note) "</p>")))
      (str (rate-chart rows) (od-list aggregates)
           "<details data-detail='aggregates-table'><summary>all area numbers</summary>"
           (table ["Area" "Residents (simulated)" "Resident workers (simulated)" "Jobs (simulated)"
                   "In-commuters (simulated)" "Out-commuters (simulated)" "Storefronts (simulated)"
                   "Storefront visits / modelled weekday" "Visits / resident"]
                  (for [r (sort-by #(str (value % :area)) rows)]
                    [(esc (value r :area)) (fmt (value r :residents) 0)
                     (fmt (value r :resident-workers) 0) (fmt (value r :jobs) 0)
                     (fmt (value r :in-commuters) 0) (fmt (value r :out-commuters) 0)
                     (fmt (value r :storefronts) 0) (fmt (value r :storefront-visits) 0)
                     (fmt (value r :visits-per-resident) 3)]))
           "</details>"
           "<p class='hint'>All rows describe the same published run. Visit and commuter figures describe one simulated weekday; they are model outputs, not observed counts. OD sampling stride: " (fmt (value aggregates :stride) 0) ".</p>"))))

;; ---- the posterior and the policy scenario ----------------------------------------------

(def ^:private green "#3f9a6b")
(def ^:private coral "#c2533d")

(defn- meur [x] (if (finite-number? x) (str (if (pos? x) "+" "") (.toFixed (/ x 1e6) 1) " M€") "—"))

(defn- class-names [sc] (map name (or (value sc :classes) ["short" "medium" "long"])))

(defn- particle-strips
  "The posterior particles as ticks on each parameter's prior range, one row
   per demand class: what the district turnovers pinned down and what they
   left as wide as the prior. Opacity is the particle's weight."
  [sc]
  (let [particles (or (value sc :particles) []) priors (value sc :priors)
        ranges {:beta (or (value priors :beta) [1 3.5])
                :d0-m (mapv #(js/Math.exp %) (or (value priors :log-d0) [5.3 7.6]))
                :alpha (or (value priors :alpha) [0 2])}
        cols [[:beta "β · distance decay"] [:d0-m "d₀ · metres"] [:alpha "α · size exponent"]]
        cw 195 rh 42 left 62 top 22 w 640 h (+ top (* rh 3) 6)
        wmax (apply max 1e-9 (map #(or (value % :weight) 0) particles))]
    (str "<svg class='city-chart' viewBox='0 0 " w " " h "' role='img' aria-label='Posterior particles per demand class and kernel parameter'>"
         (apply str (map-indexed (fn [ci [_ lbl]] (str "<text x='" (+ left (* ci cw) 4) "' y='13' fill='" ink "' font-size='10'>" (esc lbl) "</text>")) cols))
         (apply str
                (for [[ri c] (map-indexed vector (class-names sc)) [ci [k _]] (map-indexed vector cols)
                      :let [y (+ top (* ri rh)) x0 (+ left (* ci cw) 4) x1 (+ left (* ci cw) (- cw 12))
                            [lo hi] (get ranges k)
                            sx (fn [v] (+ x0 (* (- x1 x0) (max 0 (min 1 (/ (- v lo) (max 1e-9 (- hi lo))))))))]]
                  (str (when (zero? ci) (str "<text x='" (- left 8) "' y='" (+ y 24) "' text-anchor='end' fill='" ink "' font-size='10'>" (esc c) "</text>"))
                       "<line x1='" x0 "' y1='" (+ y 30) "' x2='" x1 "' y2='" (+ y 30) "' stroke='" pale "'/>"
                       "<text x='" x0 "' y='" (+ y 39) "' fill='" ink "' font-size='8'>" (fmt lo 1) "</text>"
                       "<text x='" x1 "' y='" (+ y 39) "' text-anchor='end' fill='" ink "' font-size='8'>" (fmt hi 0) "</text>"
                       (apply str (for [p particles
                                        :let [v (value (value (value p :theta) (keyword c)) k)]
                                        :when (finite-number? v)]
                                    (str "<line x1='" (sx v) "' y1='" (+ y 10) "' x2='" (sx v) "' y2='" (+ y 28) "' stroke='" blue
                                         "' stroke-opacity='" (max 0.3 (/ (or (value p :weight) 0) wmax)) "' stroke-width='1.5'/>"))))))
         "</svg>")))

(defn- calibration-chart
  "Posterior predictive over observed turnover, per district, for one class:
   the 5–95% band and the mean, against the line where the model reproduces
   the measurement."
  [sc c]
  (let [rows (sort-by #(str (value % :district))
                      (filter #(= c (name (value % :class))) (or (value sc :calibration) [])))
        ratio (fn [r k] (/ (or (value (value r :predicted) k) 0) (max 1e-9 (value r :observed))))
        max-r (min 6 (max 2 (apply max 1 (map #(ratio % :q95) rows))))
        h (+ 34 (* 17 (count rows))) x0 145 pw 470
        sx (fn [v] (+ x0 (* pw (/ (min v max-r) max-r))))]
    (if (empty? rows) (empty-note (str c "-class calibration rows"))
        (str "<svg class='city-chart' viewBox='0 0 640 " h "' role='img' aria-label='Posterior predictive against observed turnover, " (esc c) " class'>"
             "<line x1='" (sx 1) "' y1='4' x2='" (sx 1) "' y2='" (- h 20) "' stroke='" ink "' stroke-dasharray='3 3'/>"
             (apply str (map-indexed
                         (fn [i r]
                           (let [y (+ 12 (* i 17))]
                             (str "<text x='138' y='" (+ y 4) "' text-anchor='end' fill='" ink "' font-size='10'>" (esc (value r :district)) "</text>"
                                  "<line x1='" (sx (ratio r :q05)) "' y1='" y "' x2='" (sx (ratio r :q95)) "' y2='" y "' stroke='" blue "' stroke-width='6' stroke-opacity='0.35'/>"
                                  "<circle cx='" (sx (ratio r :mean)) "' cy='" y "' r='3' fill='" blue "'/>")))
                         rows))
             "<text x='" x0 "' y='" (- h 5) "' fill='" ink "' font-size='9'>0</text>"
             "<text x='" (sx 1) "' y='" (- h 5) "' text-anchor='middle' fill='" ink "' font-size='9'>predicted = observed</text>"
             "<text x='" (+ x0 pw) "' y='" (- h 5) "' text-anchor='end' fill='" ink "' font-size='9'>" (fmt max-r 1) "×</text></svg>"))))

(defn- district-delta-chart
  "Scenario minus baseline per district: bar at the posterior mean, whisker
   over the 5–95% band, in millions of euros of resident money per year."
  [sc]
  (let [rows (sort-by #(or (value (value % :delta-total) :mean) 0) (or (value sc :districts) []))
        m (fn [r k] (/ (or (value (value r :delta-total) k) 0) 1e6))
        lim (max 0.5 (apply max (map #(max (js/Math.abs (m % :q05)) (js/Math.abs (m % :q95))) rows)))
        h (+ 34 (* 17 (count rows))) x0 145 pw 470
        sx (fn [v] (+ x0 (* pw (/ (+ v lim) (* 2 lim)))))]
    (if (empty? rows) (empty-note "district deltas")
        (str "<svg class='city-chart' viewBox='0 0 640 " h "' role='img' aria-label='Scenario effect on district turnover with credible bands'>"
             "<line x1='" (sx 0) "' y1='4' x2='" (sx 0) "' y2='" (- h 20) "' stroke='" ink "'/>"
             (apply str (map-indexed
                         (fn [i r]
                           (let [y (+ 6 (* i 17)) mean (m r :mean)
                                 d (value r :district) d (if (= d "outside") "outside the 23" d)]
                             (str "<text x='138' y='" (+ y 10) "' text-anchor='end' fill='" ink "' font-size='10'>" (esc d) "</text>"
                                  "<rect x='" (min (sx 0) (sx mean)) "' y='" y "' height='12' width='" (js/Math.abs (- (sx mean) (sx 0))) "' fill='" (if (neg? mean) coral green) "'/>"
                                  "<line x1='" (sx (m r :q05)) "' y1='" (+ y 6) "' x2='" (sx (m r :q95)) "' y2='" (+ y 6) "' stroke='" ink "' stroke-width='1.2'/>")))
                         rows))
             "<text x='" x0 "' y='" (- h 5) "' fill='" ink "' font-size='9'>−" (fmt lim 1) " M€</text>"
             "<text x='" (sx 0) "' y='" (- h 5) "' text-anchor='middle' fill='" ink "' font-size='9'>0</text>"
             "<text x='" (+ x0 pw) "' y='" (- h 5) "' text-anchor='end' fill='" ink "' font-size='9'>+" (fmt lim 1) " M€</text></svg>"))))

(defn- venue-table [sc]
  (let [rows (take 14 (sort-by #(- (js/Math.abs (or (value (value % :delta-total) :mean) 0))) (or (value sc :venues) [])))]
    (if (empty? rows) (empty-note "venue deltas")
        (table ["Venue" "Role" "Δ resident revenue / year (mean)" "90% band"]
               (for [v rows :let [dt (value v :delta-total)]]
                 [(esc (or (value v :name) (value v :label))) (esc (label (value v :role))) (meur (value dt :mean))
                  (str (meur (value dt :q05)) " to " (meur (value dt :q95)))])))))

(defn- scenario-panel [sc]
  (let [n (count (or (value sc :particles) []))]
    (str "<p><strong>" (esc (value sc :label)) "</strong> — " (esc (value sc :question)) "</p>"
         "<h3>The posterior the answer is drawn under</h3>"
         "<p class='hint'>" n " particles of the segmented destination model — α, β, d₀ per demand class — fitted to the published district × class turnovers. "
         "Ticks are particles on the prior's range, opacity their weight: a tight cluster is what the turnovers pinned down, a spread is what they left open.</p>"
         (particle-strips sc)
         "<h3>Rung one — does the fitted model reproduce what was measured?</h3>"
         (apply str (for [c (class-names sc)]
                      (str "<details data-detail='calibration-" (esc c) "'><summary>" (esc c) " class: posterior predictive / observed, by district</summary>"
                           (calibration-chart sc c) "</details>")))
         "<h3>Rung two — the intervention, district by district</h3>"
         "<p class='hint'>Scenario minus baseline under each particle, so the band is the posterior over the effect itself. Resident money only; commuter and visitor spend are not moved here.</p>"
         (district-delta-chart sc)
         "<h3>Venues that move most</h3>"
         (venue-table sc)
         (when-not (value sc :conserved?) "<p class='hint'>Warning: euros were not conserved in every particle of this scenario.</p>"))))

(defn render!
  "Render the complete evidence/analytics column into `element`.

   The caller supplies already-decoded ClojureScript payloads and explicit
   per-payload statuses.  This function performs no fetching and installs no
   listeners or watches."
  [element {:keys [city area payloads statuses hour month]}]
  (when element
    (let [area-name (or (value area :name) (value area :area) (value area :eid) "No area selected")
          ;; innerHTML replacement is intentional (the renderer owns this
          ;; element), but playback must not reset the reader's disclosures.
          detail-state (into {}
                             (for [d (array-seq (.querySelectorAll element "details[data-detail]"))]
                               [(.-detail (.-dataset d)) (.-open d)]))
          scenario? (ready? payloads statuses :scenario)
          scenario-section (section "Posterior and policy scenario" "INFERRED / INTERVENTION UNDER THE POSTERIOR"
                                    (payload-block payloads statuses :scenario "policy scenario" scenario-panel)
                                    "An interventional prediction, do(venues := V'), with θ held at each posterior particle: the same residents and the same money, no new random draw. The exact expectation is compared, so the difference carries no sampling noise.")
          run-sections (str
                    (section "Run provenance and effective configuration" "PUBLISHED RUN"
                             (payload-block payloads statuses :meta "run metadata" provenance))
                    (section "Observed entities" "OBSERVED / SOURCE RECORDS"
                             (payload-block payloads statuses :summary "observed entity summary" observed-summary))
                    (section "Storefront visits by hour" "SIMULATED / ONE WEEKDAY"
                             (payload-block payloads statuses :visits "storefront visits" #(visit-chart % hour))
                             "The selected hour is a display playhead; bars aggregate the complete supplied visit feature collection.")
                    (section "Registered economic scorecard" "PUBLISHED OBSERVATIONS × SIMULATED PREDICTIONS"
                             (payload-block payloads statuses :econ "economic scorecard" econ-panel))
                    (section "Area aggregates" "SIMULATED / WHOLE-CITY RUN"
                             (payload-block payloads statuses :aggregates "area aggregates" aggregates-panel)))
          ;; with a scenario selected the column tells that story first and
          ;; folds the run's own evidence beneath it; without one, the run
          ;; evidence leads and the scenario section only says none is selected
          html (str "<div class='city-panels'><header class='city-section'><div class='section-label'>CITY EVIDENCE</div><h1>"
                    (esc (str (str/capitalize (name (or city :city))) " · " area-name))
                    "</h1><p class='hint'>Observed records and published simulation outputs are labelled separately throughout.</p></header>"
                    (if scenario?
                      (str scenario-section
                           "<details data-detail='run-evidence' class='city-section'><summary>the run beneath the scenario: provenance, visits, firms, scorecard, aggregates</summary>"
                           run-sections "</details>")
                      (str run-sections scenario-section))
                    "</div>")]
      (set! (.-innerHTML element) html)
      (doseq [d (array-seq (.querySelectorAll element "details[data-detail]"))
              :let [id (.-detail (.-dataset d))]
              :when (contains? detail-state id)]
        (set! (.-open d) (get detail-state id))))))
