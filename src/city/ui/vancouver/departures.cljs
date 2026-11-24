(ns city.ui.vancouver.departures
  "Read a release-bound comparison of census and replayed commute times.")

(defn- el [id] (js/document.getElementById id))
(defn- text! [id value] (set! (.-textContent (el id)) value))
(defn- fmt [n] (.toLocaleString n))
(defn- share [n total]
  (if (pos? total) (str (.toFixed (* 100 (/ n total)) 1) "%") "—"))

(defn- time-label [minute]
  (str (.padStart (str (mod (quot minute 60) 24)) 2 "0") ":" (.padStart (str (mod minute 60)) 2 "0")))

(def bands ["05:00–05:59" "06:00–06:59" "07:00–07:59" "08:00–08:59" "09:00–11:59" "12:00–04:59"])
(defn- draw! [report original follow]
  (let [area (.-value (el "departure-area"))
        {:strs [census coverage direct model peak covered total directObservation]} (get-in report ["areas" area])
        direct? (.-checked (el "departure-direct"))
        counts (if direct? direct model)
        baseline (when original (get-in original ["areas" area (if direct? "direct" "model")]))
        matching (get-in report ["matching" area])
        cohort (reduce + (vals coverage))
        body (el "departure-hours")]
    (.replaceChildren body)
    (doseq [[i label] (map-indexed vector bands)]
      (let [row (.insertRow body)]
        (doseq [value (concat [label (if census (share (get census (inc i)) (first census)) "—")]
                              (when baseline [(share (baseline i) (reduce + baseline))])
                              [(share (counts i) (reduce + counts)) (fmt (counts i))])]
          (set! (.-textContent (.insertCell row)) value))))
    (set! (.-hidden (el "departure-original")) (nil? baseline))
    (set! (.-hidden (el "departure-matched")) (nil? matching))
    (when matching
      (text! "departure-model" (str "Replacement days use the same donor age group, stop sequence, addresses and main mode on each trip. "
                                    (if (report "fixedLengths") "Every trip keeps its original duration." "Trips may take longer than in the original diary.")
                                    " Municipal shop openings use the revised weekday. Scheduled transit riders use the original weekday."))
      (text! "departure-match-count"
             (str "In this home area, " (fmt (matching "matched")) " workers received a complete diary matching their household donor’s usual departure band. "
                  (fmt (matching "already")) " already matched and " (fmt (matching "unsupported")) " had no compatible diary in that band."
                  (when (report "balanced")
                    (str " A further " (fmt (matching "retained")) " kept their original diary because a change would not improve both neighbourhood time bands."))))
      (let [[da i old-minute minute] (matching "example")]
        (set! (.-hidden (el "departure-changed")) (nil? da))
        (when da (text! "departure-changed" (str "Follow a worker departing at " (time-label minute) " (original " (time-label old-minute) ")")))
        (set! (.-onclick (el "departure-changed")) #(follow da i minute))))
    (text! "departure-coverage"
           (str (fmt (reduce + model)) " of " (fmt cohort) " employed residents with a reported usual commute mode left home on a traceable trip to their first paid job stop. "
                (fmt (get coverage "via" 0)) " stopped elsewhere on the way. "
                (fmt (get coverage "noJobStop" 0)) " had no paid job stop away from home and "
                (fmt (get coverage "untraced" 0)) " had no complete route from home to their first job stop."))
    (text! "departure-reference"
           (if census
             (str (fmt (first census)) " usual commuters in the "
                  (if directObservation "published municipal total." "combined census areas.")
                  (when-not directObservation (str " Both columns cover " covered " of " total " dissemination areas.")))
             "No published census comparison for this area."))
    (set! (.-hidden (el "departure-follow")) (nil? peak))
    (if-let [{:strs [minute count largest templates example]} peak]
      (let [time (time-label minute)]
        (text! "departure-peak" (str "Across direct and multi-stop trips, " (fmt count) " residents leave at exactly " time
                                     ". They share " templates " diary templates. The most common accounts for " (fmt largest) " residents."))
        (set! (.-onclick (el "departure-follow")) #(follow (first example) (second example) minute)))
      (text! "departure-peak" ""))))

(defn init [base atlas day fetch-json follow clock-run]
  (let [panel (el "departures") select (el "departure-area")
        requested (.get (js/URLSearchParams. js/location.search) "departures")
        report (atom nil) original (atom nil) pending? (atom false)
        draw #(draw! @report @original follow)
        fail (fn [e] (reset! pending? false) (text! "departure-reference" (.-message e)))
        load! (fn []
                (when (and (.-open panel) (nil? @report) (compare-and-set! pending? false true))
                  (-> (fetch-json (str base atlas "_" day ".json"))
                      (.then #(fetch-json (str base (aget % "version") "/report.json")))
                      (.then (fn [baseline]
                               (if clock-run
                                 (do (reset! original (js->clj baseline))
                                     (when-not (and (= (aget baseline "day") day) (= (aget baseline "atlas") atlas))
                                       (throw (js/Error. "Original departure report uses a different weekday.")))
                                     (fetch-json (str (aget clock-run "path") "report.json")))
                                 baseline)))
                      (.then (fn [data]
                               (let [r (js->clj data) overall (r "overall")]
                                 (when-not (and (= (r "atlas") atlas) (= (r "day") day))
                                   (throw (js/Error. "Departure counts refer to a different weekday.")))
                                 (reset! report r)
                                 (doseq [name (cons overall (sort (remove #{overall} (keys (r "areas")))))]
                                   (.add select (js/Option. name name)))
                                 (when (contains? (r "areas") requested) (set! (.-value select) requested))
                                 (set! (.-hidden (el "departure-controls")) false)
                                 (draw))))
                      (.catch fail))))]
    (let [scenario (el "departure-clock")]
      (set! (.-value scenario) (if clock-run "household" "original"))
      (set! (.-onchange scenario)
            (fn []
              (let [url (js/URL. js/location.href) p (.-searchParams url)]
                (if (= "household" (.-value scenario)) (.set p "clock" "household") (.delete p "clock"))
                (doseq [k ["commute" "workplaces" "crossing" "crossingRun" "transitWalks" "riderRun" "service" "policy" "zones" "marketRun"]] (.delete p k))
                (.set p "departures" (.-value select))
                (.assign js/location url)))))
    (set! (.-onchange select) draw)
    (set! (.-onchange (el "departure-direct")) draw)
    (set! (.-ontoggle panel) load!)
    (set! (.-hidden panel) false)
    (when (or requested clock-run) (set! (.-open panel) true) (load!))))

(defn load-clock [base atlas day requested fetch-json & [family alias]]
  (let [root (str base (or family "household-clock") "/")]
    (-> (if (= requested (or alias "household"))
          (fetch-json (str root atlas "_" day ".json"))
          (if (re-matches #"[0-9a-f]{20}" requested)
            (js/Promise.resolve #js {:version requested})
            (js/Promise.reject (js/Error. "Unknown weekday clock release."))))
        (.then (fn [ptr]
                 (let [v (aget ptr "version") path (str root v "/")]
                   (-> (fetch-json (str path "clock.json"))
                       (.then (fn [data]
                                (when-not (and (= atlas (aget data "atlas")) (= day (aget data "day")))
                                  (throw (js/Error. "This clock uses a different population or weekday.")))
                                (let [changes (aget data "changes")
                                      templates (aget data "templates")
                                      append-templates! (fn [target key]
                                                          (doseq [entry templates]
                                                            (.push (aget target "templates") (aget entry key))))
                                      apply-roster (fn [da roster]
                                                     (doseq [[i old tpl] (aget changes da)]
                                                       (let [p (aget (aget roster "people") i)]
                                                         (when-not (= (aget p 7) old)
                                                           (throw (js/Error. "Weekday clock and roster disagree.")))
                                                         (aset p 7 tpl))))
                                      apply-day (fn [weekday]
                                                  (append-templates! weekday "day")
                                                  (let [sample (js/Map.)]
                                                    (doseq [row (aget weekday "sample")]
                                                      (.set sample (str (aget (aget weekday "das") (aget row 0)) "/" (aget row 1)) row))
                                                    (doseq [da (js/Object.keys changes) [i _ tpl] (aget changes da)]
                                                      (when-let [row (.get sample (str da "/" i))] (aset row 2 tpl)))
                                                    (aset weekday "occupancy" (aget data "occupancy"))))
                                      apply-atlas (fn [population]
                                                    (append-templates! population "diary")
                                                    (doseq [[_ area] (js/Object.entries (aget population "areas"))
                                                            da (aget area "das")
                                                            [_ old tpl] (aget changes da)
                                                            scope [(aget population "city") area (aget (aget population "das") da)]]
                                                      (let [days (aget scope "days")]
                                                        (aset days old (dec (aget days old)))
                                                        (aset days tpl (inc (or (aget days tpl) 0))))))]
                                  #js {:version v :path path :kind (aget data "kind") :transit (aget data "transit")
                                       :streets (aget data "streets")
                                       :workplaceRun (aget data "workplaceRun")
                                       :workTransitRelease (aget data "workTransitRelease")
                                       :applyDiaries #(append-templates! % "diary")
                                       :applyRoster apply-roster :applyDay apply-day :applyAtlas apply-atlas}))))))))))
