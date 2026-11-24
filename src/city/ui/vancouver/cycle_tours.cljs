(ns city.ui.vancouver.cycle-tours
  "Switch eligible whole outings together in the resident replay and nearby street view."
  (:require [city.vancouver.trip-accounting :as accounting]))

(defn- el [id] (js/document.getElementById id))
(defn- text! [id x] (set! (.-textContent (el id)) x))
(defn- number-label [n] (.toLocaleString (or n 0) "en-CA"))
(defn- percent [n total] (if (pos? total) (str (.toFixed (* 100 (/ n total)) 2) "%") "—"))

(defn- minute-count! [projection zone minute]
  (let [offset (- minute 240) i (.indexOf (aget projection "zones") zone)
        count-at (fn [mode]
                   (let [row (aget (aget projection mode) offset)]
                     (if (= zone "all") (reduce + row) (aget row i))))
        h (mod (quot minute 60) 24) m (mod minute 60)]
    (text! "tour-now" (str "At " (.padStart (str h) 2 "0") ":" (.padStart (str m) 2 "0")
                          ", " (number-label (count-at "access")) " drivers from this home area would be cycling with survey-based access, or "
                          (number-label (count-at "ride")) " with universal access."))))

(defn- index-tours [rows speed day places home-areas]
  (let [residents (js/Map.) hours (js/Array.from #js {:length 28} #(array))
        areas (aget day "areas") downtown (.indexOf areas "Downtown") nz (alength areas)
        flows (js/Int32Array. (* 24 nz 2))]
    (doseq [[d i _ _ _ legs] rows]
      (let [key (+ (* d 65536) i)
            trips (or (.get residents key) (array))]
        (.set residents key trips)
        (doseq [[s n a b] legs]
          (.push trips #js [s (+ s n)])
          (when-let [dir (accounting/crossing (aget (aget places a) 2) (aget (aget places b) 2) downtown)]
            (let [hour (mod (quot (if (zero? dir) (+ s n) s) 60) 24)
                  k (+ dir (* 2 (+ (aget home-areas d) (* hour nz))))]
              (aset flows k (inc (aget flows k)))))
          (doseq [h (range (quot s 60) (inc (quot (dec (+ s n)) 60)))]
            (.push (aget hours h) #js [d i s n a b speed])))))
    {:residents residents :hours hours :flow (fn [h area dir] (aget flows (+ dir (* 2 (+ area (* h nz))))))}))

(defn init [root version expected day fetch-json follow refresh places home-areas]
  (let [panel (el "cycle-outings") zone (el "tour-zone") purpose (el "tour-purpose")
        toggle (el "tour-mode") params (.-searchParams (js/URL. js/location.href))
        report (atom nil) rows (atom nil) indices (atom nil) busy (atom false)
        mode (atom "diary") flags (atom nil) example (atom 0) projection (atom nil) last-clock (atom nil)
        sync-url! (fn []
                    (let [u (js/URL. js/location.href) p (.-searchParams u)]
                      (.set p "cycleTours" @mode)
                      (.set p "tourZone" (.-value zone)) (.set p "tourPurpose" (.-value purpose))
                      (.replaceState js/history nil "" u)))
        draw! (fn []
                (let [z (.-value zone) kind (.-value purpose)
                      r (some #(when (= z (aget % "code")) %) (aget @report "zones"))
                      {:strs [feasible candidates legs trips bikes survey residents accessTours accessLegs accessRate accessPopulation]} (js->clj r)
                      eligible (filterv (fn [row] (and (or (= z "all") (= z (aget row 3)))
                                                        (or (= kind "all") (= kind (aget row 4)))
                                                        (or (not= @mode "access") (aget row 6)))) @rows)
                      sample (when (seq eligible) (eligible (mod @example (count eligible))))
                      host (el "tour-legs")]
                  (text! "tour-volume" (str (number-label feasible) " of " (number-label candidates)
                                            " driver outings fit on a bicycle. " (number-label residents)
                                            " residents could switch " (number-label legs) " trips. With survey-based bicycle access, " (number-label accessTours) " outings qualify."))
                  (text! "tour-access-evidence" (str (number-label (accessPopulation "access")) " of "
                                                     (number-label (accessPopulation "adults")) " modelled residents aged 20+ have access here. "
                                                     (if (= z "unmapped") "Unmapped homes use the citywide"
                                                         "The 2023 survey reports an adult")
                                                     " bicycle access rate of " accessRate "%."))
                  (text! "tour-shares" (str "Cycling accounts for " (percent bikes trips) " of recorded trips here"
                                            " in the original weekday, " (percent (+ bikes accessLegs) trips)
                                            " with survey-based access and " (percent (+ bikes (or legs 0)) trips)
                                            " with universal access." (when survey (str " The City survey reports " survey "%."))
                                            (when (aget expected "workplaces") " These shares use the original commute modes.")))
                  (.replaceChildren host)
                  (set! (.-disabled (el "tour-next")) (< (count eligible) 2))
                  (if sample
                    (let [[d i tpl _ label steps] sample
                          da (aget (aget day "das") d) template (aget (aget day "templates") tpl)]
                      (text! "tour-example" (str (number-label (count eligible)) " matching outings · " label
                                                " · " da "-P" (inc i)))
                      (doseq [[s n] steps]
                        (let [part (.find (aget template "parts") #(= s (aget % 0)))
                              dest (aget (aget template "slots") (aget part 4))
                              time (str (.padStart (str (mod (quot s 60) 24)) 2 "0") ":" (.padStart (str (mod s 60)) 2 "0"))
                              btn (js/document.createElement "button")]
                          (set! (.-textContent btn) (str time " → " dest))
                          (set! (.-onclick btn) #(follow da i (+ s (/ n 2))))
                          (.appendChild host btn))))
                    (text! "tour-example" "No eligible outings in this group."))))
        load! (fn []
                (when (and (.-open panel) (nil? @report) (compare-and-set! busy false true))
                  (let [base (str root version "/")]
                    (-> (js/Promise.all #js [(fetch-json (str base "report.json")) (fetch-json (str base "tours.json"))
                                             (-> (js/fetch (str base "access.bin"))
                                                 (.then (fn [response]
                                                          (when-not (.-ok response) (throw (js/Error. "Bicycle access assignments are unavailable.")))
                                                          (.arrayBuffer response))))])
                        (.then (fn [[r tours bytes]]
                                 (when-not (and (= (.-byteLength bytes) (aget day "population"))
                                                (= (aget r "tours") (alength tours))
                                                (every? (fn [k] (= (aget expected k) (aget (aget r "versions") k)))
                                                        ["atlas" "day" "streets" "cycling"]))
                                   (throw (js/Error. "Outing assignments and the selected weekday differ.")))
                                 (reset! flags (js/Uint8Array. bytes))
                                 (reset! indices {"ride" (index-tours tours (aget r "speed") day places home-areas)
                                                  "access" (index-tours (.filter tours #(aget % 6)) (aget r "speed") day places home-areas)}) (reset! rows tours) (reset! report r)
                                 (doseq [area (aget r "zones")]
                                   (.add zone (js/Option. (aget area "name") (aget area "code"))))
                                 (doseq [[select k] [[zone "tourZone"] [purpose "tourPurpose"]]]
                                   (when (some #(= (.-value %) (.get params k)) (array-seq (.-options select)))
                                     (set! (.-value select) (.get params k))))
                                 (reset! mode (or (#{"access" "ride"} (.get params "cycleTours")) "diary"))
                                 (set! (.-value toggle) @mode)
                                 (set! (.-hidden (el "tour-controls")) false)
                                 (draw!) (refresh)
                                 (-> (fetch-json (str root "../raster/" version "-cycle-tours.json"))
                                     (.then (fn [clock]
                                              (when-not (and (= version (aget clock "tours"))
                                                             (= (js->clj (aget clock "versions")) (js->clj (aget r "versions"))))
                                                (throw (js/Error. "Minute counts belong to a different outing release.")))
                                              (reset! projection clock)
                                              (text! "tour-compute" (str "Raster reproduced the same counts for every minute using "
                                                                         (number-label (aget clock "agents")) " individual drivers and "
                                                                         (number-label (aget clock "groups")) " weighted schedules on "
                                                                         (.toUpperCase (aget clock "backend")) "."))
                                              (refresh)))
                                     (.catch #(text! "tour-now" (.-message %))))))
                        (.catch #(text! "tour-volume" (.-message %)))
                        (.finally #(reset! busy false))))))]
    (set! (.-hidden panel) false)
    (set! (.-ontoggle panel) load!)
    (set! (.-onchange toggle) (fn [] (reset! mode (.-value toggle)) (reset! example 0) (sync-url!) (draw!) (refresh)))
    (doseq [select [zone purpose]]
      (set! (.-onchange select) (fn [] (reset! example 0) (sync-url!) (draw!) (refresh))))
    (set! (.-onclick (el "tour-next")) (fn [] (swap! example inc) (draw!)))
    (when (.has params "cycleTours")
      (set! (.-open (el "cycle-check")) true) (set! (.-open panel) true) (load!))
    #js {:mode (fn [] @mode)
         :flow (fn [h area dir] (if-let [f (:flow (get @indices @mode))] (f h area dir) 0))
         :atMinute (fn [t]
                     (when (and @projection (.-open panel))
                       (let [minute (js/Math.floor t) k [minute (.-value zone)]]
                         (when (not= k @last-clock)
                           (reset! last-clock k) (minute-count! @projection (.-value zone) minute)))))
         :access (fn [d i] (when @flags (aget @flags (+ (aget (aget @report "offsets") d) i))))
         :added (fn [] (case @mode
                         "access" (aget (aget (aget @report "zones") 0) "accessLegs")
                         "ride" (aget (aget (aget @report "zones") 0) "legs")
                         0))
         :rows (fn [h] (when-let [index (get @indices @mode)] (aget (:hours index) h)))
         :riding (fn [d i t]
                   (when-let [index (get @indices @mode)]
                     (when-let [legs (.get (:residents index) (+ (* d 65536) i))]
                       (.some legs (fn [[s end]] (and (<= s t) (< t end)))))))}))
