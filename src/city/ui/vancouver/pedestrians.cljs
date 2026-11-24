(ns city.ui.vancouver.pedestrians
  "Observed intersection counts and links into the corresponding synthetic weekdays."
  (:require [goog.object :as obj]))

(defn- el [id] (js/document.getElementById id))
(defn- text! [id value] (set! (.-textContent (el id)) value))
(defn- total [xs] (reduce + xs))
(defn- number-label [n] (.toLocaleString n))
(defn- hour-label [minute] (str (.padStart (str (quot minute 60)) 2 "0") ":00"))

(defn- visit-url [example model site scheduled? report]
  (let [[da i minute] example
        params (js/URLSearchParams.)
        day-run (.get (js/URLSearchParams. js/location.search) "dayRun")]
    (doseq [[k v] [["da" da] ["person" (inc i)] ["minute" minute] ["crossing" site] ["crossingRun" (obj/get report "version")]]]
      (.set params k (str v)))
    (when day-run
      (.set params "dayRun" day-run))
    (case model
      "tracts" (do (.set params "workplaces" "census") (.set params "commute" "tracts"))
      "city" (.set params "walks" "diary")
      nil)
    (when scheduled?
      (.set params "transitWalks" (obj/get (obj/get report "transit") "riders"))
      (when-let [name (aget example 7)] (.set params "service" name)))
    (str "cityday.html?" params)))

(defn- count-cell! [row count example model site hour scheduled? report]
  (let [cell (.insertCell row)]
    (if example
      (let [link (js/document.createElement "a")]
        (set! (.-href link) (visit-url example model site scheduled? report))
        (set! (.-textContent link) (number-label count))
        (.setAttribute link "aria-label" (str count " passings at " (hour-label hour) ". Follow a resident in the "
                                              (case model "tracts" "census-workplace" "short" "city and inferred walks" "city-only")
                                              " replay."))
        (.append cell link))
      (set! (.-textContent cell) (number-label count)))))

(defn- draw! [report show-site focus?]
  (let [idx (js/Number (.-value (el "pedestrian-site")))
        site (aget (obj/get report "sites") idx)
        include? (.-checked (el "pedestrian-short"))
        scheduled? (and (obj/get report "transit") (.-checked (el "pedestrian-transit")))
        hours (obj/get site "hours") observed (obj/get site "observed")
        census (obj/get site "tracts") inferred (obj/get site "inferred")
        diary (mapv + (obj/get site "city") (if include? inferred (repeat 0)))
        city (if scheduled?
               (mapv (fn [base to from old] (- (+ base to from) old)) diary
                     (obj/get site "access") (obj/get site "egress") (obj/get site "replaced"))
               diary)
        examples (obj/get site "examples")
        body (el "pedestrian-hours")]
    (.replaceChildren body)
    (dotimes [j (alength hours)]
      (let [row (.insertRow body) hour (aget hours j)
            short-ex (when include? (aget (obj/get examples "inferred") j))
            example (if scheduled?
                      (or (aget (obj/get examples "access") j) (aget (obj/get examples "egress") j)
                          short-ex (aget (obj/get examples "retained") j))
                      (or short-ex (aget (obj/get examples "city") j)))]
        (set! (.-textContent (.insertCell row)) (hour-label hour))
        (set! (.-textContent (.insertCell row)) (number-label (aget observed j)))
        (count-cell! row (city j) example (if include? "short" "city") idx hour scheduled? report)
        (count-cell! row (aget census j) (aget (obj/get examples "tracts") j) "tracts" idx hour false report)))
    (text! "pedestrian-total" (str (number-label (total observed)) " observed crossings · "
                                   (number-label (total city)) " city-only passings · "
                                   (number-label (total census)) " census-workplace passings during the surveyed hours."))
    (set! (.-hidden (el "pedestrian-transit-label")) (nil? (obj/get report "transit")))
    (when-let [service (obj/get report "transit")]
      (text! "pedestrian-rider-coverage"
             (str (number-label (obj/get service "matched")) " of "
                  (number-label (obj/get service "total")) " diary trips involving transit fit a direct ride on "
                  (obj/get service "date") ". Walking occupied the most diary time on "
                  (number-label (obj/get (obj/get (obj/get report "coverage") "replaced") "walks"))
                  " of the matched trips. The comparison replaces those whole-trip walking paths.")))
    (let [info (el "pedestrian-rider-walks")]
      (set! (.-hidden info) (not scheduled?))
      (when scheduled?
        (.replaceChildren info)
        (doseq [[k label] [["access" "to a stop"] ["egress" "from a stop"]]]
          (let [n (total (obj/get site k)) ex (first (filter some? (obj/get examples k)))
                text (str (number-label n) " " label)]
            (if ex
              (let [link (js/document.createElement "a")]
                (set! (.-textContent link) text)
                (set! (.-href link) (visit-url ex (if include? "short" "city") idx true report))
                (.append info link))
              (.append info text))
            (.append info " · ")))
        (.append info (str (total (obj/get site "replaced")) " original walking passings replaced by scheduled rides."))))
    (let [[work school other] (apply mapv + (js->clj (obj/get site "purposes")))]
      (text! "pedestrian-purpose" (str "Of the census-workplace passings, " work " have a paid-work stop on the walk, "
                                       school " a school stop, and " other " other endpoints. "
                                       (total (obj/get site "at80")) " fit a walking speed of 80 m/min or less. "
                                       "Using a 44 m radius gives " (total (obj/get site "wider")) " through-passings.")))
    (let [cohort (obj/get (obj/get site "lunch") "tracts")]
      (text! "pedestrian-lunch" (str (number-label (obj/get cohort "workers"))
                                     " residents are doing paid work within 400 m at 11:30 in the census-workplace run. "
                                     (obj/get cohort "walks") " leave that job on foot before 13:00, including "
                                     (obj/get cohort "errands") " going straight to a store or restaurant.")))
    (let [link (el "pedestrian-source")]
      (set! (.-textContent link) (str "City count sheet · " (obj/get site "date")))
      (set! (.-href link) (obj/get site "source")))
    (show-site (obj/get site "point") (obj/get report "radius") focus?)))

(defn init [root pointer streets active-tract fetch-json show-site]
  (let [panel (el "pedestrian-check") select (el "pedestrian-site")
        params (js/URLSearchParams. js/location.search)
        requested (.get params "crossing")
        report (atom nil) pending (atom nil)
        redraw (fn [focus?] (when (and @report (.-open panel)) (draw! @report show-site focus?)))
        load! (fn []
                (let [day (obj/get pointer "version")]
                  (-> (if-let [pinned (re-matches #"[a-f0-9]{20}" (or (.get params "crossingRun") ""))]
                        (js/Promise.resolve #js {:version pinned})
                        (fetch-json (str root day "_" streets ".json")))
                      (.then (fn [ptr]
                               (let [version (obj/get ptr "version")]
                                 (-> (fetch-json (str root version "/counts.json"))
                                     (.then (fn [data] (obj/set data "version" version) data))))))
                      (.then (fn [data]
                               (when-not (and (= day (obj/get data "day")) (= streets (obj/get data "streets"))
                                              (= (obj/get pointer "atlas") (obj/get data "atlas"))
                                              (or (nil? active-tract) (= active-tract (obj/get data "tracts"))))
                                 (throw (js/Error. "Intersection counts use a different population or street network.")))
                               (reset! report data)
                               (obj/set (.-dataset select) "version" (obj/get data "version"))
                               (when-let [service (obj/get data "transit")]
                                 (obj/set (.-dataset select) "riders" (obj/get service "riders")))
                               (doseq [[i site] (map-indexed vector (obj/get data "sites"))]
                                 (.add select (js/Option. (obj/get site "name") (str i))))
                               (when (and requested (some #(= requested (.-value %)) (array-seq (.-options select))))
                                 (set! (.-value select) requested))
                               (set! (.-hidden (el "pedestrian-controls")) false)
                               (text! "pedestrian-status" "")
                               (redraw (and requested (not (.has params "da"))))))
                      (.catch (fn [e] (reset! pending nil) (text! "pedestrian-status" (.-message e)))))))]
    (set! (.-hidden panel) false)
    (let [link (el "market-pedestrian-check")]
      (set! (.-hidden link) false)
      (set! (.-onclick link) #(set! (.-open panel) true)))
    (set! (.-onchange select) #(redraw true))
    (set! (.-onchange (el "pedestrian-short")) #(redraw false))
    (set! (.-onchange (el "pedestrian-transit")) #(redraw false))
    (set! (.-ontoggle panel)
          #(if (.-open panel)
             (if @report (redraw false) (when-not @pending (reset! pending (load!))))
             (show-site nil nil false)))
    (when requested
      (set! (.-checked (el "pedestrian-transit")) (.has params "transitWalks"))
      (set! (.-checked (el "pedestrian-short")) (and (not= "census" (.get params "workplaces"))
                                                      (not= "diary" (.get params "walks"))))
      (set! (.-open panel) true))))
