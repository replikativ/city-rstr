(ns city.ui.vancouver.shopping-evidence
  "Score opening schedules and compare shopping arrivals with independent surveys."
  (:require [city.opening-hours :as hours]))

(defn- el [id] (js/document.getElementById id))
(defn- txt! [id s] (set! (.-textContent (el id)) s))
(defn- number-label [n] (.toLocaleString n "en-CA" #js {:maximumFractionDigits 1}))
(defn- pct [value] (str (.toFixed (* 100 value) 1) "%"))
(defn- clock [t]
  (let [m (mod t 1440) pad #(.padStart (str %) 2 "0")]
    (str (pad (quot m 60)) ":" (pad (mod m 60)))))
(defn- row! [body values]
  (let [r (.insertRow body)]
    (doseq [v values] (set! (.-textContent (.insertCell r)) (str v)))))

(defn- mode-check! [{:strs [arrivals surveys]} mode walks? walked]
  (let [{:strs [fifths inferredWalkFifths switchedFifths]} arrivals
        counts (update fifths "Walking" + (if walks? inferredWalkFifths 0))
        moved (get switchedFifths mode 0)
        scenario (-> counts (update "Auto driver" - moved (* 5 walked))
                     (update "Walking" + (* 5 walked)) (update "Cycling" + moved))
        n (reduce + (vals counts)) table (el "shopping-modes")]
    (txt! "shopping-volume" (str (number-label (/ n 5)) " adult-equivalent weekday trips arriving at shopping across the city"
                                 (when walks? (str ", including " (number-label (/ inferredWalkFifths 5)) " inferred walks")) "."))
    (.replaceChildren table)
    (doseq [m ["Auto driver" "Auto passenger" "Transit" "Walking" "Cycling" "Other / unspecified"]]
      (row! table (concat [m (pct (/ (get counts m 0) n)) (pct (/ (get scenario m 0) n))]
                          (for [survey surveys]
                            (if-some [v (get-in survey ["shares" m])] (str v "%") "—")))))))

(defn- clock-check! [samples key]
  (let [mode (.-value (el "shopping-clock-mode")) hours (hours/schedule key)
        body (el "shopping-clocks")]
    (.replaceChildren body)
    (doseq [[pool label] [["bcFit" "Urban BC · fit"] ["bcHoldout" "Urban BC · held out"]
                          ["otherUrban" "Other urban provinces"]]
            :let [{:strs [donors occasions clock effective]} (get-in samples [pool "modes" mode])
                  fit (when (and hours (>= donors 15) (seq clock))
                        (reduce + 0 (for [[start dwell w] clock :when (hours/admits? hours start dwell)] w)))]]
      (row! body [label donors occasions effective (if (some? fit) (pct fit) "—")]))
    (txt! "shopping-support"
          (case mode
            "bike" "Only one BC fitting diary and one diary elsewhere have a qualifying bicycle stop. Their times cannot establish a peak shopping hour."
            "car-driver" "These diaries describe original driver schedules. The cycling scenario keeps a switched driver’s stop time."
            "The observed stops include purchases of any goods at a store. Respondent weights determine the shares."))))

(defn- groceries! [survey key]
  (set! (.-hidden (el "grocery-clock-panel")) (nil? survey))
  (when survey
    (let [mode (.-value (el "shopping-clock-mode")) hours (hours/schedule key)
          table (el "grocery-clocks")]
      (.replaceChildren table)
      (doseq [[p label] [["bc" "Urban BC"] ["otherUrban" "Other urban provinces"]]
              :let [group (aget (aget (aget survey "pools") p) mode)
                    clock (aget group "clock")]]
        (row! table [label (aget group "stops") (aget group "groceryStops") (if-some [v (aget group "share")] (pct v) "—")
                     (if (and hours (pos? (alength clock)))
                       (pct (reduce + 0 (for [[s d w] clock :when (hours/admits? hours s d)] w))) "—")])))))

(defn init [load-report state apply-hours]
  (let [data (atom nil) selected (atom nil) cached (atom nil)
        render (fn []
                 (when (.-open (el "market-evidence"))
                   (let [s (state) rows (aget s "rows") site (aget s "site") key (aget s "hours")
                         mode (aget s "mode") offer? (and site (some? rows) (pos? (alength rows)))]
                     (set! (.-hidden (el "shopping-shift")) (not offer?))
                     (when offer?
                       (let [basis [site mode]]
                         (when (not= basis (:basis @cached))
                           (let [{:keys [start count ties]} (hours/best-shift (js->clj rows) 480)
                                 opens (clock start) closes (clock (+ start 480))]
                             (reset! cached {:basis basis :opens opens :closes closes})
                             (txt! "shopping-shift-result"
                                   (str opens "–" closes " admits " count " of " (alength rows)
                                        " possible visits here. " ties (if (= ties 1) " start time attains" " start times attain") " this maximum."))))))
                     (when @data
                       (mode-check! @data mode (aget s "inferred") (aget s "walked"))
                       (groceries! (aget s "survey") key)
                       (clock-check! (@data "samples") key)))))]
    (set! (.-onchange (el "shopping-clock-mode")) render)
    (set! (.-onclick (el "shopping-shift-apply"))
          (fn [] (when-let [{:keys [opens closes]} @cached] (apply-hours opens closes))))
    (set! (.-ontoggle (el "market-evidence"))
          (fn []
            (when (.-open (el "market-evidence"))
              (render)
              (when (compare-and-set! selected nil :loading)
                (-> (load-report)
                    (.then (fn [r]
                             (reset! data (js->clj r))
                             (set! (.-hidden (el "shopping-surveys")) false)
                             (txt! "shopping-evidence-status" "")
                             (render)))
                    (.catch (fn [_] (reset! selected nil)
                              (txt! "shopping-evidence-status" "Survey comparison unavailable for this weekday."))))))))
    render))

(defn init-access [report selected-site walkers follow]
  (let [panel (el "local-access") area (el "local-area") radius (el "local-radius")
        areas (aget report "homeArea") boundary (aget report "boundary")
        render (fn []
                 (when (.-open panel)
                   (let [a (.-value area) k (js/Number (.-value radius))
                         within? (fn [home] (or (= a "") (= (js/Number a) home)))
                         included? (fn [d] (and (or (nil? boundary) (aget (aget boundary "municipal") d))
                                                 (within? (aget areas d))))
                         obs (aget (aget report "observed") (* 1000 (if (zero? k) 1 3)))
                         sim (aget (aget report "counts") k)
                         matched (filter #(and (included? %) (some? (aget obs %))) (range (alength areas)))
                         present? (fn [d] (some pos? (aget obs d)))
                         held (count (filter present? matched))
                         missed (count (filter #(and (present? %) (zero? (aget sim %))) matched))
                         extra (count (filter #(and (not (present? %)) (pos? (aget sim %))) matched))
                         choice (when-let [id (selected-site)] (aget (aget report "sites") id))
                         added (when choice (filter included? (aget (aget choice "newDA") k)))
                         live (filter #(within? (aget % 0)) (walkers))
                         sample (or (first (filter #(aget % 1) live)) (first live))
                         button (el "local-follow")]
                     (set! (.-hidden button) (nil? sample))
                     (set! (.-onclick button) (when sample #(follow (aget sample 3) (aget sample 4) (aget sample 5))))
                     (txt! "local-counts"
                           (str (number-label (count matched)) " census areas have observations here. Can-FED finds grocery access in "
                                (number-label held) " and the model in " (number-label (+ held extra (- missed)))
                                ". The model misses " missed " areas with observed access and finds access in " extra " others."))
                     (txt! "local-access-change"
                           (if choice (str "This opening gives " (count added) " census reference points their first modelled grocer within "
                                           (if (zero? k) 1 3) " km. Can-FED already records access at "
                                           (count (filter #(and (some? (aget obs %)) (present? %)) added)) " of these points.") "Choose a storefront to compare access after opening."))
                     (txt! "local-drivers"
                           (str (number-label (count live)) " grocery outings switch from driving to walking in the selected replay population."
                                (when choice (str " Of these, " (count (filter #(aget % 1) live)) " visit the proposed shop and "
                                                  (count (filter #(and (aget % 1) (not (aget % 2))) live))
                                                  " gain their first feasible walking option.")))))))]
    (if boundary
      (let [missing (js/Object.values (aget boundary "missing"))
            adjacent (js/Object.values (aget boundary "adjacent"))]
        (txt! "local-boundary"
              (if (and (zero? (alength missing)) (zero? (alength adjacent)))
                (str "The weekday and food access comparison cover the same " (number-label (aget boundary "municipalAreas")) " municipal census areas.")
                (str "The access comparison uses the official city boundary. The replay includes "
                   (alength adjacent) " additional areas (" (number-label (reduce + 0 adjacent))
                   " residents) and omits " (alength missing) " city areas (" (number-label (reduce + 0 missing)) " residents)."))))
      (txt! "local-boundary" "This archived comparison uses the replay footprint."))
    (doseq [[i name] (map-indexed vector (aget report "areas"))]
      (.add area (js/Option. name (str i))))
    (set! (.-hidden panel) false)
    (set! (.-ontoggle panel) render)
    (set! (.-onchange area) render)
    (set! (.-onchange radius) render)
    render))
