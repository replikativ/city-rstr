(ns city.ui.vancouver.workplaces
  "Municipal workplace geography on the resident replay and its census mode check."
  (:require [city.opening-hours :as hours]
            [city.vancouver.trip-accounting :as accounting]
            [clojure.string :as str]
            [goog.object :as obj]))

(defn- el ^js [id] (js/document.getElementById id))
(defn- count-label [n] (.toLocaleString n))
(defn- text! [id content] (set! (.-textContent (el id)) content))

(defn- trip-state [by-area local changes paid places direct mode-keys labels preserve-modes? rule d i tpl current]
  (when current
      (let [[start _ recorded a b] current
            slots (nth paid tpl)
            worker (.get (aget by-area d) i)
            selected-rule (rule)
            site-changes (changes selected-rule)
            matched (when site-changes (.get (aget site-changes d) i))
            overrides (when (and matched (or (.has matched a) (.has matched b))) matched)
            place (when worker (places (aget worker 1)))
            assigned (when (contains? (get direct tpl) start)
                       (case selected-rule
                         ("local" "sites") (.get (aget local d) i)
                         "tracts" (when-not preserve-modes? (.get (aget local d) i))
                         "usual" (when worker (aget worker 2))
                         nil))
            apply? (and (number? assigned) (<= 0 ^number assigned))
            method (if (#{"local" "sites" "tracts"} selected-rule) "neighbourhood-fitted mode" "usual commute mode")
            site-method (if (= selected-rule "tracts") "census tract workplace scenario" "matched workplace")
            mode (if apply? (mode-keys assigned) recorded)]
        (cond
          (and worker (or (contains? slots a) (contains? slots b)))
          #js {:mode mode :external true :assignedMode (when apply? mode)
               :description
               (if (= "stop" mode)
                 (str "Usual workplace · " place)
                 (str (if apply? (str (labels assigned) " · " method) (str/replace mode "-" " ")) " · "
                      (cond (and (slots a) (slots b)) "between workplace stops in "
                            (slots a) "from "
                            :else "to ")
                      place " · route unresolved"))}
          apply? #js {:replaceMode mode :overrides overrides :method (str method (when overrides (str " · " site-method)))}
          overrides #js {:overrides overrides :method site-method}))))

(defn- mode-count [counts category column]
  (cond
    (and (= category "Walking or bicycle") (not= column "observed"))
    (+ (get counts "Walking" 0) (get counts "Bicycle" 0))
    (and (= category "Other") (not= column "observed"))
    (reduce + (map #(get counts % 0) ["Other" "Ride-hail" "Taxi"]))
    :else (get counts category 0)))

(defn- mode-check! [check paired]
  (let [totals (update-vals check #(reduce + (vals %)))
        table (el "outbound-modes")]
    (.replaceChildren table)
    (doseq [category ["Car driver" "Car passenger" "Public transit" "Walking or bicycle" "Other"]]
      (let [row (.insertRow table)]
        (set! (.-textContent (.insertCell row)) category)
        (doseq [column (cond-> ["observed" "usual" "diary"] (contains? check "local") (conj "local"))]
          (let [v (mode-count (check column) category column)
                n (totals column)]
            (set! (.-textContent (.insertCell row)) (if (pos? n) (str (.toFixed (* 100 (/ v n)) 1) "%") "—"))))))
    (text! "outbound-mode-basis"
           (str (count-label (totals "observed")) " census workers, "
                (if paired
                  (str (count-label (totals "diary")) " simulated workers with a direct trip from home to work"
                       (when-let [n (get paired "templateCount")] (str " drawn from " (count-label n) " source diaries"))
                       ". " (count-label (get paired "changed" 0)) " have different modes for their first such trip. "
                       "Cycling accounts for " (count-label (get-in check ["diary" "Bicycle"] 0)) " diary trips and "
                       (count-label (get-in check ["usual" "Bicycle"] 0)) " trips using the usual mode. "
                       "The census groups walking and cycling together.")
                  (str (count-label (totals "usual")) " assigned workers and "
                       (count-label (totals "diary")) " diaries with a direct home-to-work trip."))))))

(defn- choices! [select names]
  (doseq [[i name] (map-indexed vector names)] (.add select (js/Option. name i))))

(defn- local-check! [report fit sites follow]
  (let [select (el "local-mode-area") button (el "local-mode-trip") table (el "local-mode-counts")
        paired (el "worksite-trip")
        bike-button (el "bike-mode-trip") bikes (obj/get fit "bikeExamples")
        example #(aget (obj/get fit "examples") (js/Number (.-value select)))
        show! (fn []
                (let [area (js/Number (.-value select))
                      group (js->clj (aget (obj/get fit "areas") area))
                      cols (mapv group ["census" "before" "fitted"])
                      totals (mapv #(reduce + %) cols)]
                  (text! "local-mode-cohort" (str (count-label (totals 1)) " model commuters · "
                                                  (count-label (totals 0)) " published mode counts across "
                                                  (group "covered") " of " (group "das") " census areas."))
                  (.replaceChildren table)
                  (doseq [[m label] (map-indexed vector (js->clj (obj/get fit "modes")))]
                    (let [row (.insertRow table)]
                      (set! (.-textContent (.insertCell row)) label)
                      (doseq [[counts total] (map vector cols totals)]
                        (set! (.-textContent (.insertCell row))
                              (if (pos? total) (str (.toFixed (* 100 (/ (counts m) total)) 1) "%") "—")))))
                  (if-let [checks (obj/get fit "budgetCheck")]
                    (let [counts (js->clj (aget checks area))]
                      (text! "local-mode-distance"
                             (str "Direct trips to or from a city job that do not fit the diary time. "
                                  (str/join " · " (for [[label basis] [["Walking" "street network"] ["Bicycle" (if (obj/get fit "cycling") "cycling network" "straight line")]]
                                                        :let [[n final] (get-in counts ["fitted" label] [0 0])
                                                              before (get-in counts ["marginal" label 1] 0)]]
                                                    (str label " (" basis ") " (count-label before) " before, "
                                                         (count-label final) " after, of " (count-label n) " legs"))))))
                    (when-let [checks (obj/get fit "distanceCheck")]
                      (let [counts (js->clj (aget checks area))]
                        (text! "local-mode-distance"
                               (str "Direct trips to city jobs exceeding the diary time at the model speed, even in a straight line. "
                                    (str/join " · " (for [mode ["Walking" "Bicycle"]
                                                          :let [[n over] (get-in counts ["fitted" mode] [0 0])]]
                                                      (str mode " " (count-label over) " of " (count-label n)))))))))
                  (when sites
                    (let [rows (js->clj (aget (obj/get sites "summary") area))]
                      (text! "worksite-budget"
                             (str (count-label (rows "failed")) " walking legs miss the diary time at their original workplaces. "
                                  (count-label (rows "matchedFailed")) " still miss it after exchanging compatible workplaces. "
                                  (count-label (rows "nearestFailed")) " cannot reach even the nearest job site in the assigned neighbourhood."
                                  (when (contains? rows "cityFailed")
                                    (str " Across the whole city, " (count-label (rows "cityFailed")) " cannot reach any site."))))
                      (set! (.-disabled paired) (nil? (aget (obj/get sites "examples") area)))))
                  (when bikes (set! (.-disabled bike-button) (nil? (aget bikes area))))
                  (set! (.-disabled button) (nil? (example)))))]
    (when sites
      (set! (.-hidden (el "worksite-comparison")) false)
      (set! (.-onclick paired)
            #(when-let [[d i start] (aget (obj/get sites "examples") (js/Number (.-value select)))]
               (let [selector (el "commute-rule")]
                 (set! (.-value selector) "sites")
                 (.dispatchEvent selector (js/Event. "change")))
               (follow (aget (obj/get sites "das") d) i start true))))
    (when bikes
      (set! (.-textContent button) "Follow a walking commute")
      (set! (.-hidden bike-button) false)
      (set! (.-onclick bike-button)
            #(when-let [[da i start] (aget bikes (js/Number (.-value select)))] (follow da i start true))))
    (choices! select (js->clj (obj/get report "areas")))
    (set! (.-value select) (str (.indexOf (obj/get report "areas") "Downtown")))
    (set! (.-onchange select) show!)
    (set! (.-onclick button) #(when-let [[da i start] (example)] (follow da i start true)))
    (set! (.-hidden (el "local-mode-panel")) false)
    (show!)))

(defn- controls! [report sites places areas rule fixed-rule show-zones follow refresh]
  (let [select (el "outbound-place") button (el "outbound-follow") area (el "outbound-area")
        compare (el "commute-trip")
        example #(aget (obj/get report "examples") (js/Number (.-value select)))
        trip #(when-let [trips (obj/get report "tripExamples")] (aget trips (js/Number (.-value select))))
        describe! (fn []
                    (let [j (js/Number (.-value select))]
                      (text! "outbound-cohort"
                             (str (count-label (aget (obj/get report "stock") j)) " residents have their usual workplace here. "
                                  (count-label (aget (obj/get report "attend") j)) " spend time at a paid-work stop on this modelled weekday."
                                  (when (str/starts-with? (places j) "Metro Vancouver A (")
                                    " This census area includes UBC and places beyond the campus.")))
                      (set! (.-hidden compare) (nil? (trip)))
                      (set! (.-disabled button) (nil? (example)))))]
    (set! (.-hidden (el "outbound-panel")) false)
    (choices! select places)
    (choices! area areas)
    (set! (.-value area) (str (.indexOf areas "Downtown")))
    (set! (.-onchange area) refresh)
    (set! (.-onchange select) describe!)
    (set! (.-onclick button) #(when-let [[da i start] (example)] (follow da i start)))
    (set! (.-onclick compare) #(when-let [[da i start] (trip)] (follow da i start)))
    (describe!)
    (if-let [observed (obj/get report "observedByAge")]
      (let [age (el "commute-age") selector (el "commute-rule")
            paired (js->clj (obj/get report "pairedByAge"))
            fitted (obj/get report "neighbourhoodFit")
            display! (fn []
                       (let [group (.-value age) pairs (paired group)]
                         (mode-check! (cond-> {"observed" (js->clj (obj/get observed group))
                                               "usual" (get pairs "usual" {}) "diary" (get pairs "diary" {})}
                                        fitted (assoc "local" (js->clj (obj/get (obj/get fitted "pairedByAge") group))))
                                      (or pairs {}))))]
        (when fitted
          (.add selector (js/Option. "Neighbourhood and workplace fit · city residents" "local"))
          (set! (.-hidden (el "fit-column")) false)
          (when sites (.add selector (js/Option. "Fitted modes + matched walking workplaces" "sites")))
          (when-let [tract (when sites (obj/get sites "tract"))]
            (.add selector (js/Option. (if (obj/get tract "preserveDiaryModes")
                                        "Census tract workplaces + diary modes"
                                        "Census tract workplaces + fitted modes") "tracts")))
          (local-check! report fitted sites follow))
        (doseq [label ["All ages" "15–24" "25–34" "35–44" "45–54" "55–64" "65+"]]
          (.add age (js/Option. label label)))
        (set! (.-hidden (el "commute-rule-label")) false)
        (set! (.-hidden (el "commute-age-label")) false)
        (set! (.-value selector) @rule)
        (set! (.-disabled selector) (boolean fixed-rule))
        (set! (.-onchange selector)
              (fn []
                (let [url (js/URL. js/location.href)]
                  (reset! rule (or fixed-rule (.-value selector)))
                  (set! (.-value selector) @rule)
                  (if (= @rule "diary") (.delete (.-searchParams url) "commute") (.set (.-searchParams url) "commute" @rule))
                  (.replaceState js/history nil "" url)
                  (show-zones follow)
                  (refresh))))
        (when (= @rule "usual") (set! (.-open (el "outbound-panel")) true))
        (when (#{"local" "sites" "tracts"} @rule) (set! (.-open (el "local-mode-panel")) true))
        (set! (.-onchange age) display!)
        (display!)
        (show-zones follow))
      (mode-check! (js->clj (obj/get report "modeCheck")) nil))))

(defn- occupancy! [report tract rule offset counts shop timing voting]
  (let [area (js/Number (.-value (el "outbound-area"))) before (aget counts area)
        moved (aget (obj/get report "relocated") offset area)
        delta (if (= @rule "tracts") (aget (obj/get tract "occupancyDelta") offset area) 0)
        retail (if shop ((obj/get shop "occupancyAt") offset area) 0)
        waiting (if timing (aget timing area) 0)
        voting-change (if voting (aget voting area) 0)]
    (text! "outbound-occupancy"
           (str (count-label before) " residents at places here with city-only addresses · "
                (count-label (+ (- before moved) delta retail waiting voting-change)) " with census workplace destinations · " (count-label moved) " assigned outside the city."
                (when (= @rule "tracts") (str " The tract scenario changes this neighbourhood by " (count-label delta) " residents."))
                (when shop (str " Grocery visits change it by " (count-label retail) "."))))))

(defn- workplace-volume-limit [data]
  (let [matrix (data "matched")]
    (for [[i zone] (map-indexed vector (data "zones"))
          :let [home-trips (reduce + (take 10 (matrix i)))
                zone-jobs (reduce + (map #(get % i) matrix))
                observed (zone "observed")]
          :when (and (pos? home-trips) (< (* 100 zone-jobs) (* home-trips observed)))]
      (str (zone "name") " has " (count-label (js/Math.round zone-jobs))
           " work trips with a job in the zone across all city residents. Even if residents of this zone made every one of those trips, "
           "only " (.toFixed (/ (* 100 zone-jobs) home-trips) 1)
           "% of its residents’ work trips could stay local at this trip volume. The survey reports " observed "%."))))

(defn- zone-check! [report]
  (let [panel (el "survey-zones") choice (el "zone-purpose") trim (el "zone-interior")
        requested (.get (js/URLSearchParams. js/location.search) "zones")
        data (js->clj report)
        purposes (if (data "otherPurposes") #{"work" "other" "nonhome"} #{"work"})
        limits (apply str (interpose " " (workplace-volume-limit data)))
        draw! (fn []
                (let [purpose (.-value choice) work? (= purpose "work") interior? (.-checked trim)
                      matrix (data (if interior? "interior" "matched"))
                      tbody (el "zone-counts")]
                  (.replaceChildren tbody)
                  (doseq [[i zone] (map-indexed vector (data "zones"))]
                    (let [row (.insertRow tbody) od (matrix i)
                          counts (get-in data ["otherPurposes" purpose i])
                          [n local] (cond work? [(reduce + (take 10 od)) (od i)]
                                          interior? [(counts 2) (counts 3)]
                                          :else [(counts 0) (counts 1)])
                          pct (if (pos? n) (str (.toFixed (* 100 (/ local n)) 1) "%") "—")]
                      (doseq [label [(zone "name") (str (zone (if work? "observed" purpose)) "%") pct
                                     (count-label (js/Math.round n))]]
                        (set! (.-textContent (.insertCell row)) label))))
                  (let [rows (take 9 (data "matched"))
                        counts (take 9 (get-in data ["otherPurposes" purpose]))
                        known (if work? (reduce + (mapcat #(take 10 %) rows)) (reduce + (map first counts)))
                        missing (if work? (reduce + (map peek rows)) (reduce + (map peek counts)))]
                    (text! "zone-coverage"
                           (str "Across the nine home zones, " (count-label (js/Math.round known))
                                " trips have classified endpoints and " (count-label (js/Math.round missing))
                                " have an unresolved endpoint, before the boundary filter.")))
                  (let [note (el "zone-work-volume")]
                    (set! (.-textContent note) limits)
                    (set! (.-hidden note) (or (not work?) interior? (empty? limits))))
                  (when (.-open panel)
                    (let [url (js/URL. js/location.href)]
                      (.set (.-searchParams url) "zones" purpose)
                      (.replaceState js/history nil "" url)))))]
    (set! (.-hidden panel) false)
    (doseq [option (array-seq (.-options choice))]
      (set! (.-disabled option) (not (purposes (.-value option)))))
    (when (purposes requested)
      (set! (.-value choice) requested)
      (set! (.-open panel) true))
    (set! (.-onchange choice) draw!)
    (set! (.-onchange trim) draw!)
    (draw!)))

(defn- optional-release [base family parent]
  (let [root (str base family "/")]
    (-> (js/fetch (str root parent ".json"))
        (.then (fn [r]
                 (cond (.-ok r) (-> (.json r) (.then #(str root (obj/get % "version") "/")))
                       (= (.-status r) 404) nil
                       :else (throw (js/Error. (str "Unable to load " family)))))))))

(defn- workplace-release [base family parent pins]
  (if pins
    (js/Promise.resolve (when-let [version (obj/get pins family)] (str base family "/" version "/")))
    (optional-release base family parent)))

(defn- zone-releases [base version fetch-json pins]
  (-> (js/Promise.all #js [(optional-release base "survey-zones" version)
                           (workplace-release base "tract-workplaces" version pins)])
      (.then (fn [[survey tract]]
               (js/Promise.all #js [(when survey (fetch-json (str survey "zones.json")))
                                    (when tract (fetch-json (str tract "worksites.json")))
                                    (when tract (fetch-json (str tract "zones.json"))) tract])))))

(defn- load-sites [base outbound fetch-json pins]
  (-> (workplace-release base "worksites" outbound pins)
      (.then
       (fn [dir]
         (when dir
           (let [version (last (remove empty? (str/split dir #"/")))]
             (-> (js/Promise.all #js [(fetch-json (str dir "worksites.json"))
                                      (zone-releases base version fetch-json pins)])
                 (.then (fn [[sites [baseline scenario validation tract-dir]]]
                          (doseq [record [baseline scenario validation] :when record]
                            (when-not (and (= version (obj/get record "worksites"))
                                           (= outbound (obj/get record "outbound"))
                                           (= (obj/get sites "atlas") (obj/get record "atlas"))
                                           (= (obj/get sites "day") (obj/get record "day")))
                              (throw (js/Error. "Workplace scenario and resident releases differ."))))
                          (obj/set sites "marketParent" (if tract-dir (last (remove empty? (str/split tract-dir #"/"))) version))
                          (obj/set sites "baselineZones" baseline)
                          (obj/set sites "tract" scenario)
                          (obj/set sites "tractZones" validation)
                          sites)))))))))

(defn- site-index [assignments report]
  (when report
    (let [index (.map assignments (fn [_] (js/Map.)))]
      (doseq [[d i slot _ dest] (obj/get report "changes")]
        (let [group (aget index d)]
          (when-not (.has group i) (.set group i (js/Map.)))
          (.set (.get group i) slot dest)))
      index)))

(defn resident-trips
  "Resolve a diary part against the same workplace and mode assignments in playback and validation."
  [report assignments local-rows sites tract rule]
  (let [paid (mapv set (js->clj (obj/get report "slots")))
        direct (mapv set (js->clj (obj/get report "directStarts")))
        local (when local-rows (.map local-rows (fn [rows] (js/Map. rows))))
        changes {"sites" (site-index assignments sites) "tracts" (site-index assignments tract)}
        by-area (.map assignments (fn [rows] (js/Map. (.map rows (fn [row] #js [(aget row 0) row])))))]
    (partial trip-state by-area local changes paid (js->clj (obj/get report "destinations"))
             direct (js->clj (obj/get report "modeKeys")) (js->clj (obj/get report "modes"))
             (boolean (when tract (obj/get tract "preserveDiaryModes"))) rule)))

(defn- show-geography! [sites rule follow]
  (when sites
    (let [tract (obj/get sites "tract") active? (= @rule "tracts")
          zones (obj/get sites (if active? "tractZones" "baselineZones"))
          control (el "zone-model")
          switch! (fn [value]
                    (let [selector (el "commute-rule")]
                      (set! (.-value selector) value)
                      (.dispatchEvent selector (js/Event. "change"))))]
      (when zones (zone-check! zones))
      (when tract
        (set! (.-hidden (el "zone-model-label")) false)
        (set! (.-value control) (if active? "tracts" "sites"))
        (set! (.-onchange control) #(switch! (.-value control)))
        (text! "zone-scenario-note"
               (if active?
                 (str (count-label (obj/get tract "moved")) (if (obj/get tract "preserveDiaryModes")
                                                              " residents receive a different workplace address. "
                                                              " residents change workplace tract. ")
                      "The scenario uses 2021 usual-workplace shares among "
                      (count-label (obj/get tract "covered")) " city residents with a located paid-work day in covered tracts."
                      (when-let [unfilled (obj/get tract "unfilled")]
                        (str (if-let [routes (obj/get tract "activeRoutes")]
                               (str " All commute modes stay fixed. Workers whose active routes fit every diary window increase from "
                                    (count-label (obj/get routes "before")) " to " (count-label (obj/get routes "after"))
                                    " among " (count-label (obj/get routes "workers")) " eligible workers.")
                               " Work-linked walks and cycle rides retain their sites.") " "
                             (count-label unfilled) " target places remain unfilled after checking trip times.")))
                 "The model column uses the matched walking workplaces and census destinations outside the city."))
        (let [examples (obj/get tract "examples") example (or (aget examples 1) (first (filter some? examples)))
              button (el "zone-workplace-example")]
          (set! (.-hidden button) (nil? example))
          (when example
            (set! (.-onclick button)
                  #(let [[da i start] example]
                     (switch! "tracts")
                     (follow da i start true)))))))))

(defn load-workers [base pointer day fetch-json]
  (let [root (str base "outbound/") pins (obj/get pointer "workplaceRuns")]
    (-> (if pins (js/Promise.resolve #js {:version (obj/get pins "outbound")})
            (fetch-json (str root (obj/get pointer "atlas") "_" (obj/get pointer "version") ".json")))
        (.then (fn [release]
                 (let [dir (str root (obj/get release "version") "/")]
                   (-> (fetch-json (str dir "report.json"))
                       (.then (fn [report]
                                (js/Promise.all #js [report (obj/get release "version") (load-sites base (obj/get release "version") fetch-json pins) (fetch-json (str dir "assignments.json"))
                                                     (when (obj/get report "neighbourhoodFit")
                                                       (fetch-json (str dir "local-modes.json")))])))))))
        (.then
         (fn [[report version sites assignments local-rows]]
           (let [areas (js->clj (obj/get report "areas")) places (js->clj (obj/get report "destinations"))
                 fixed-rule (obj/get pointer "commuteRule")
                 requested (or fixed-rule (.get (js/URLSearchParams. js/location.search) "commute"))
                 tract (when sites (obj/get sites "tract"))
                 rule (atom (cond (and tract (= "tracts" requested)) "tracts"
                                  (and sites (= "sites" requested)) "sites"
                                  (and local-rows (= "local" requested)) "local"
                                  (and (seq (obj/get report "directStarts")) (= "usual" requested)) "usual" :else "diary"))]
             (when-not (and (= (obj/get pointer "atlas") (obj/get report "atlas")) (= (obj/get pointer "version") (obj/get report "day"))
                            (= (.-length assignments) (.-length (obj/get day "das"))) (= areas (js->clj (obj/get day "areas"))))
               (throw (js/Error. "Workplace geography and resident releases differ.")))
             (when sites
               (when-not (and (= version (obj/get sites "outbound")) (= (obj/get report "day") (obj/get sites "day"))
                              (= (obj/get report "atlas") (obj/get sites "atlas"))
                              (= (obj/get (obj/get report "neighbourhoodFit") "streets") (obj/get sites "streets")))
                 (throw (js/Error. "Matched workplaces and resident releases differ.")))
               (obj/set sites "das" (obj/get day "das")))
             (js-obj "report" report
                     "marketParent" (or (when sites (obj/get sites "marketParent")) version)
                     "commuteRule" #(deref rule)
                     "tractDelta" (when tract (obj/get tract "delta"))
                     "state" (resident-trips report assignments local-rows sites tract #(deref rule))
                     "show" (partial controls! report sites places areas rule fixed-rule (partial show-geography! sites rule))
                     "occupancy" (partial occupancy! report tract rule))))))))

(defn project-market [n downtown visits]
  (let [{:keys [occupancy-at walking-flow cycling-flow driving-flow]} (accounting/shop-effects n downtown visits)]
    (js-obj "occupancyAt" occupancy-at "walkingFlow" walking-flow "cyclingFlow" cycling-flow "drivingFlow" driving-flow)))

(defn opening-hours [value]
  (when-let [{:keys [key label opens closes start span] :as schedule} (hours/schedule value)]
    (js-obj "key" key "label" label "opens" opens "closes" closes
            "withinReference" (hours/admits? (hours/schedule "full") start span)
            "admits" (partial hours/admits? schedule)
            "admitsAfterActivation" (partial hours/admits-after-activation? schedule))))
