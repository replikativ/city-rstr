(ns city.ui.trip-demand
  "Explore the published weekday by home zone, primary mode and destination."
  (:require [city.ui.experiments :as store]))

(defn- el [id] (js/document.getElementById id))
(defn- text! [id s] (set! (.-textContent (el id)) s))
(defn- count-label [n] (.toLocaleString (/ n 5) "en-CA" #js {:maximumFractionDigits 1}))
(defn- share [n total] (if (pos? total) (str (.toFixed (/ (* 100 n) total) 1) "%") "—"))
(defn- total [cells] (reduce + 0 (map #(nth % 3) cells)))

(def ^:private destination-purposes
  ["Paid work" "Shopping" "Dining" "Recreation" "Social" "Return home" "Other or unclear"])

(defn- rate-label [n]
  (.toLocaleString n "en-CA" #js {:minimumFractionDigits 1 :maximumFractionDigits 1}))

(defn- gap-label [n]
  (if (< (js/Math.abs n) 0.05)
    (rate-label 0)
    (str (if (pos? n) "+" "−") (rate-label (js/Math.abs n)))))

(defn- display-purpose-rates! [survey cells people zone mode]
  (let [panel (el "demand-purpose-mode")
        {:strs [adults purposes]} survey
        all? (= mode "all")
        comparable? (and (= zone "all") (pos? people) (seq purposes)
                         (or all? (contains? (get-in purposes ["Paid work" "modeTrips"]) mode)))]
    (set! (.-hidden panel) (not comparable?))
    (when comparable?
      (let [body (el "demand-purpose-mode-rows")
            classified (remove #(= "Other / unspecified" (second %)) cells)]
        (.replaceChildren body)
        (doseq [purpose destination-purposes
                :let [{:strs [trips modeTrips]} (purposes purpose)]
                :when trips]
          (let [items (filter #(= purpose (nth % 2)) classified)
                model-purpose (/ (* 1000 (total items)) people)
                model (/ (* 1000 (total (if all? items (filter #(= mode (second %)) items)))) people)
                survey-mode (if all? trips (modeTrips mode))
                observed (/ (* 1000 survey-mode) adults)
                at-survey-mix (* model-purpose (/ survey-mode trips))
                row (.insertRow body)
                gap (str (gap-label (- observed model)) " total")]
            (set! (.-textContent (.insertCell row)) purpose)
            (set! (.-textContent (.insertCell row)) (str (rate-label model) " / " (rate-label observed)))
            (let [cell (.insertCell row)]
              (set! (.-textContent cell) gap)
              (when-not all?
                (let [note (js/document.createElement "small")]
                  (set! (.-textContent note)
                        (str (gap-label (- observed at-survey-mix)) " from trip volume · "
                             (gap-label (- at-survey-mix model)) " from mode share"))
                  (.appendChild cell note))))))
        (text! "demand-purpose-mode-note"
               (str "Positive gaps mean the model records fewer trips than the survey. "
                    (when-not all?
                      "The volume effect uses the survey mode share at both trip volumes. The mode-share effect uses the model trip volume. ")
                    "Rates use the five travel modes defined by the survey."))))))

(defn- display! [data cells follow]
  (let [{:strs [zones adults cityShares purposeShares purposeModeSurvey]} data
        zone (el "demand-zone") mode (el "demand-mode")
        url (js/URL. js/location.href) params (.-searchParams url)
        draw (fn []
               (let [z (.-value zone) m (.-value mode)
                     group (if (= z "all") cells (filterv #(= z (first %)) cells))
                     subset (if (= m "all") group (filterv #(= m (second %)) group))
                     trips (total group) n (total subset)
                     diaries (count (into #{} (mapcat #(nth % 5)) subset))
                     people (if (= z "all") (reduce + (vals adults)) (get adults z 0))
                     shares (if (= z "all") cityShares (some #(when (= z (% "code")) (% "shares")) zones))
                     obs (get shares m) body (el "demand-purposes")]
                 (text! "demand-volume"
                        (str (count-label trips) " recorded trips by " (count-label people) " adult-equivalent residents"
                             (when (pos? people) (str " · " (.toFixed (/ trips people) 2) " trips per resident")) "."))
                 (text! "demand-share"
                        (str (if (= m "all") "All primary travel modes."
                                 (str m " accounts for " (count-label n) " trips (" (share n trips) ")."
                                      (when obs (str " The City survey reports " obs "%."))))
                             " These trips come from " diaries " distinct diary templates."))
                 (set! (.-hidden (el "demand-survey-head")) (not (and (= z "all") (= m "all"))))
                 (.replaceChildren body)
                 (doseq [purpose destination-purposes]
                   (let [items (filter #(= purpose (nth % 2)) subset)
                         amount (total items) example (some #(nth % 4) items) row (.insertRow body)
                         support (count (into #{} (mapcat #(nth % 5)) items))]
                     (doseq [s [purpose (count-label amount) (share amount n)]]
                       (set! (.-textContent (.insertCell row)) s))
                     (when (and (pos? amount) (not= m "all"))
                       (let [note (js/document.createElement "small")]
                         (set! (.-textContent note) (str support (if (= support 1) " diary" " diaries")))
                         (.appendChild (aget (.-cells row) 1) note)))
                     (when (and (= z "all") (= m "all"))
                       (set! (.-textContent (.insertCell row)) (if-let [v (purposeShares purpose)] (str v "%") "—")))
                     (let [cell (.insertCell row)]
                       (when example
                         (let [btn (js/document.createElement "button")]
                           (set! (.-textContent btn) "Follow")
                           (.setAttribute btn "aria-label" (str "Follow a " purpose " trip"))
                           (set! (.-onclick btn) #(apply follow example))
                           (.appendChild cell btn))))))
                 (display-purpose-rates! purposeModeSurvey group people z m)))
        changed (fn []
                  (let [u (js/URL. js/location.href) p (.-searchParams u)]
                    (.set p "demand" (.-value zone)) (.set p "tripMode" (.-value mode))
                    (.replaceState js/history nil "" u))
                  (draw))]
    (.add zone (js/Option. "Whole city" "all"))
    (doseq [{:strs [name code]} zones] (.add zone (js/Option. name code)))
    (when (pos? (get adults "unmapped" 0)) (.add zone (js/Option. "Unmapped homes" "unmapped")))
    (.add mode (js/Option. "All modes" "all"))
    (doseq [m ["Cycling" "Walking" "Transit" "Auto driver" "Auto passenger" "Other / unspecified"]]
      (.add mode (js/Option. m m)))
    (doseq [[select key] [[zone "demand"] [mode "tripMode"]]]
      (when (some #(= (.-value %) (.get params key)) (array-seq (.-options select)))
        (set! (.-value select) (.get params key)))
      (set! (.-onchange select) changed))
    (set! (.-hidden (el "demand-controls")) false)
    (when (= "1" (.get params "demandRates"))
      (set! (.-open (el "demand-purpose-mode")) true))
    (draw)))

(defn init [root atlas day fetch-json follow]
  (-> (fetch-json (str root atlas "_" day ".json"))
      (.then (fn [ptr]
               (let [version (aget ptr "version")]
                 (-> (fetch-json (str root version "/demand.json"))
                     (.then (fn [report]
                              (when-not (and (= "vancouver" (aget report "city")) (= atlas (aget report "atlas"))
                                             (= day (aget report "day")))
                                (throw (js/Error. "Trip counts belong to a different release.")))
                              (-> (js/Promise.resolve nil)
                                  (.then #(store/trip-cells version report))
                                  (.catch (fn [_]
                                            (text! "demand-storage" "Browser storage is unavailable. Showing the published trip counts.")
                                            (aget report "cells")))
                                  (.then #(display! (js->clj report) (js->clj %) follow)))))))))
      (.catch #(text! "demand-volume" (.-message %)))))

(defn- per-thousand [n population]
  (if (and (some? n) (pos? population))
    (.toLocaleString (/ (* 1000 n) population) "en-CA" #js {:maximumFractionDigits 1})
    "—"))

(defn- clock-time [minute]
  (str (.padStart (str (mod (quot minute 60) 24)) 2 "0") ":"
       (.padStart (str (mod minute 60)) 2 "0")))

(defn- display-timing! [{:strs [periods purposes modelAdults surveyAdults source]} follow jump]
  (let [select (el "timing-period")
        body (el "timing-rows")
        peak-button (el "timing-peak")
        follow-button (el "timing-follow")
        by-key (into {} (map (juxt #(get % "key") identity)) periods)
        draw (fn []
               (let [{:strs [recorded combined surveyTrips surveyShares fittedShopping example shoppingPeak]}
                     (by-key (.-value select))
                     survey (mapv #(* surveyTrips (/ % 100)) surveyShares)]
                 (.replaceChildren body)
                 (doseq [[label n m s] (concat (map vector purposes recorded combined survey)
                                              [["All trips" (reduce + recorded) (reduce + combined) surveyTrips]])]
                   (let [row (.insertRow body)
                         heading (js/document.createElement "th")]
                     (.setAttribute heading "scope" "row")
                     (set! (.-textContent heading) label)
                     (.appendChild row heading)
                     (doseq [[count population] [[n modelAdults] [m modelAdults] [s surveyAdults]]]
                       (set! (.-textContent (.insertCell row)) (per-thousand count population)))))
                 (text! "timing-shopping"
                        (str (.toLocaleString fittedShopping "en-CA") " fitted walks to shops in this period."
                             (when shoppingPeak
                               (let [[minute departures] shoppingPeak]
                                 (str " The busiest modeled shopping minute is " (clock-time minute)
                                      " with " (.toLocaleString departures "en-CA") " departures.")))))
                 (set! (.-hidden peak-button) (nil? shoppingPeak))
                 (set! (.-hidden follow-button) (nil? example))
                 (when shoppingPeak
                   (set! (.-textContent peak-button) (str "Go to " (clock-time (first shoppingPeak))))
                   (set! (.-onclick peak-button) #(jump (first shoppingPeak))))
                 (when example (set! (.-onclick follow-button) #(apply follow example)))))]
    (doseq [{:strs [key label start end]} periods]
      (.add select (js/Option. (str label " · " (clock-time start) "–" (clock-time end)) key)))
    (let [requested (.get (js/URLSearchParams. js/location.search) "tripTiming")]
      (set! (.-value select) (if (contains? by-key requested) requested "pre-pm")))
    (set! (.-onchange select)
          (fn []
            (let [url (js/URL. js/location.href)]
              (.set (.-searchParams url) "tripTiming" (.-value select))
              (.replaceState js/history nil "" url))
            (draw)))
    (set! (.-href (el "timing-source")) (str source "#page=47"))
    (set! (.-href (el "timing-population-source")) (str source "#page=23"))
    (set! (.-hidden (el "timing-status")) true)
    (set! (.-hidden (el "timing-controls")) false)
    (draw)))

(defn init-timing [url joint fetch-json follow jump]
  (-> (fetch-json url)
      (.then
       (fn [value]
         (let [data (js->clj value)
               expected (js->clj (aget joint "versions"))]
           (when-not (and (= 1 (data "schema")) (= (aget joint "id") (data "joint"))
                          (= (aget joint "outings") (data "outings")) (= expected (data "versions")))
             (throw (js/Error. "The timing comparison uses a different combined weekday.")))
           (display-timing! data follow jump))))))

(defn- follow-cell! [row label example follow]
  (let [cell (.insertCell row)]
    (when example
      (let [btn (js/document.createElement "button")]
        (set! (.-textContent btn) "Follow")
        (.setAttribute btn "aria-label" label)
        (set! (.-onclick btn) #(apply follow example))
        (.appendChild cell btn)))))

(defn- display-commute-zones! [{:strs [homeZones workplaces unmappedResidents unmappedWorkplaces usedInFit]}
                               source params follow]
  (let [by-workplace (into {} (map (juxt #(get % "key") identity)) workplaces)
        panel (el "north-commute-zones")
        select (el "north-commute-workplace")
        body (el "north-commute-zone-rows")
        requested (.get params "northWorkplace")
        boundary-count (reduce + (map #(get % "nearBoundary") homeZones))
        fallback-count (reduce + (map #(get % "fallback") homeZones))
        draw (fn []
               (let [{:strs [model observed]} (by-workplace (.-value select))]
                 (.replaceChildren body)
                 (doseq [[home [n example] survey] (map vector homeZones model observed)]
                   (let [{:strs [label residents modelResidents]} home
                         row (.insertRow body)
                         bound? (string? survey)
                         limit (if bound? (js/Number (subs survey 1)) survey)]
                     (set! (.-textContent (.insertCell row)) label)
                     (let [cell (.insertCell row)]
                       (set! (.-textContent cell) (per-thousand n modelResidents))
                       (set! (.-title cell) (str (.toLocaleString n "en-CA") " modeled commuters")))
                     (let [cell (.insertCell row)]
                       (set! (.-textContent cell) (str (when bound? "<") (per-thousand limit residents)))
                       (set! (.-title cell) (str (if bound? survey (.toLocaleString survey "en-CA")) " survey commuters")))
                     (follow-cell! row (str "Follow a commuter from " label) example follow)))))]
    (doseq [{:strs [key]} workplaces]
      (.add select (js/Option. key key)))
    (set! (.-value select) (or (when (contains? by-workplace requested) requested)
                              (when (contains? by-workplace "Burnaby") "Burnaby")
                              "Downtown or West End"))
    (set! (.-onchange select)
          (fn []
            (let [url (js/URL. js/location.href)
                  p (.-searchParams url)
                  link (el "north-commute-zone-link")]
              (.set p "northWorkplace" (.-value select))
              (.replaceState js/history nil "" url)
              (when-let [href (.getAttribute link "href")]
                (let [other (js/URL. href)]
                  (.set (.-searchParams other) "northWorkplace" (.-value select))
                  (set! (.-href link) other))))
            (draw)))
    (text! "north-commute-zone-coverage"
           (str (.toLocaleString boundary-count "en-CA") " residents live near a mapped zone boundary."
                (when (pos? fallback-count)
                  (str " " (.toLocaleString fallback-count "en-CA") " are located by home census area."))
                (when (pos? unmappedResidents)
                  (str " " (.toLocaleString unmappedResidents "en-CA") " residents have an unclassified home."))
                (when (pos? unmappedWorkplaces)
                  (str " " (.toLocaleString unmappedWorkplaces "en-CA") " commuters have an unclassified workplace."))))
    (text! "north-commute-zone-fit"
           (if usedInFit
             "This replay fits the survey’s workplace shares within each home zone. It keeps the existing number of modeled commuters, modes and diary times."
             "This replay holds the 2025 commute estimates out of the workplace fit."))
    (set! (.-href (el "north-commute-zone-source")) (str source "#page=67"))
    (set! (.-hidden panel) false)
    (when requested (set! (.-open panel) true))
    (draw)))

(defn- display-north! [report follow]
  (let [{:strs [model observations source gapWalks widerDestinations heldOut2025]} report
        area (el "north-demand-area")
        view (el "north-demand-view")
        area-names (cons "North Shore" (sort (remove #{"North Shore"} (keys model))))
        draw (fn []
               (let [name (.-value area)
                     dimension (.-value view)
                     {:strs [residents trips travelers coverage] :as selected} (model name)
                     survey (observations name)
                     observed (survey dimension)
                     survey-2025 (get-in heldOut2025 ["observations" name])
                     observed-2025 (get survey-2025 dimension)
                     show-2025 (boolean (seq observed-2025))
                     cells (selected dimension)
                     entries (into (set (keys cells)) (concat (keys observed) (keys observed-2025)))
                     entries (if (= dimension "hours") (sort-by js/Number entries) (sort entries))
                     body (el "north-demand-rows")
                     count-label #(.toLocaleString % "en-CA")
                     rate #(.toFixed (/ (:trips %) (:people %)) 2)
                     missing (get coverage "Unrecorded change of place" 0)
                     inferred (get gapWalks name)]
                 (text! "north-demand-rate"
                        (str (rate {:trips trips :people residents}) " recorded trips per resident · "
                             (rate {:trips (survey "trips") :people (survey "residents")}) " in 2023"
                             (when survey-2025
                               (str " · " (rate {:trips (survey-2025 "trips") :people (survey-2025 "residents")}) " in 2025"))
                             "."))
                 (set! (.-hidden (el "north-demand-2025-column")) (not show-2025))
                 (text! "north-demand-population"
                        (str (count-label residents) " private-household residents aged 15+ in the model, "
                             (count-label travelers) " with recorded travel."))
                 (text! "north-demand-gaps"
                        (if (some? inferred)
                          (str (count-label inferred) " of " (count-label missing)
                               " assigned place changes without recorded travel fit a walk of at most ten minutes. "
                               "Adding those walks would bring the model to "
                               (rate {:trips (+ trips inferred) :people residents}) " trips per resident.")
                          (str (count-label missing) " changes between assigned places have no recorded travel.")))
                 (text! "north-demand-note"
                        (case dimension
                          "hours" "The 2023 survey gives numerical totals for two peak departure hours across the North Shore."
                          "outbound" (if widerDestinations
                                       "Counts use assigned origins on the North Shore and destinations south of Burrard Inlet. Burnaby and New Westminster currently cover paid work."
                                       "Counts use assigned origins on the North Shore and destinations south of Burrard Inlet. The replay's destinations extend through Vancouver and UBC.")
                          "purposes" "The model uses diary activities at each destination. Escorting passengers and unclear activities share the Other category. Surveys also count recreational loops."
                          "The North Shore survey groups taxis, ride-hailing and motorcycles under Other."))
                 (.replaceChildren body)
                 (doseq [key entries]
                   (let [[n example] (cells key)
                         row (.insertRow body)
                         label (if (= dimension "hours") (str (.padStart key 2 "0") ":00") key)]
                     (set! (.-textContent (.insertCell row)) label)
                     (doseq [[count population] (cond-> [[n residents] [(observed key) (survey "residents")]]
                                                  show-2025 (conj [(observed-2025 key) (survey-2025 "residents")]))]
                       (let [cell (.insertCell row)]
                         (set! (.-textContent cell) (per-thousand count population))
                         (when (some? count)
                           (set! (.-title cell) (str (count-label count) " trips")))))
                     (follow-cell! row (str "Follow a trip for " label) example follow)))))
        url (js/URL. js/location.href)
        params (.-searchParams url)
        changed (fn []
                  (let [u (js/URL. js/location.href) p (.-searchParams u)]
                    (.set p "northDemand" (.-value area))
                    (.set p "northBreakdown" (.-value view))
                    (.replaceState js/history nil "" u))
                  (draw))]
    (doseq [name area-names] (.add area (js/Option. name name)))
    (doseq [[select key] [[area "northDemand"] [view "northBreakdown"]]]
      (let [value (.get params key)]
        (when (some #(= value (.-value %)) (array-seq (.-options select)))
          (set! (.-value select) value)))
      (set! (.-onchange select) changed))
    (set! (.-href (el "north-demand-source")) source)
    (when heldOut2025
      (set! (.-href (el "north-demand-2025-source")) (heldOut2025 "source"))
      (set! (.-hidden (el "north-demand-2025-reference")) false)
      (set! (.-hidden (el "north-demand-2025-note")) false)
      (when-let [zones (heldOut2025 "commuteZones")]
        (display-commute-zones! zones (heldOut2025 "source") params follow)))
    (set! (.-hidden (el "north-demand-results")) false)
    (draw)))

(defn init-north [root version atlas day fetch-json follow]
  (-> (fetch-json (str root version "/report.json"))
      (.then (fn [report]
               (when-not (and (= atlas (aget report "atlas")) (= day (aget report "day")))
                 (throw (js/Error. "North Shore trip counts belong to a different weekday.")))
               (display-north! (js->clj report) follow)))
      (.catch #(text! "north-demand-rate" (.-message %)))))
