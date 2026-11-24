(ns city.ui.vancouver.cycle-counts
  "Compare the active weekday's cyclist passages with held-out City count sheets."
  (:require [clojure.string :as str]))

(defn- el [id] (.getElementById js/document id))
(defn- text! [id msg] (set! (.-textContent (el id)) msg))
(defn- hour-label [h]
  (let [hour (mod h 24)]
    (str (when (< hour 10) "0") hour ":00")))

(defn- draw! [report work tour follow explore penalty]
  (let [index (.-selectedIndex (el "cycle-site"))
        site (get-in report ["sites" index])
        rule (if tour (if (= work "city") tour (str work "+" tour)) work)
        run (get-in report ["runs" rule])
        results (get-in run ["sites" index])
        comparison (get report "comparison")
        base-index (first (keep-indexed (fn [i row] (when (= row site) i)) (get comparison "sites")))
        base (get-in comparison ["runs" rule "sites" base-index "counts"])
        detour (get run "detours")
        hills (get run "hills")
        {:strs [routed legs unlocated colocated rejected]} (get run "coverage")
        {:strs [hours observed dailyAverage date weather point locationSource]} site
        {:strs [counts examples]} results
        daily? (some? dailyAverage)
        total (reduce + counts)
        body (el "cycle-hours")]
    (when-not results (throw (js/Error. "Missing bicycle counts for this workplace assignment.")))
    (text! "cycle-status" (str (.toLocaleString (or dailyAverage (reduce + observed)))
                               (if daily? " City daily average · " " observed · ")
                               (.toLocaleString total) " simulated " (if (= 1 total) "passage" "passages")
                               (if daily? " per weekday" " during the counted hours")
                               (when (and daily? base) (str " · " (.toLocaleString (reduce + base)) " with the comparison route rule")) "."))
    (set! (.-hidden (el "cycle-observed-hour")) daily?)
    (set! (.-hidden (el "cycle-directions-table")) daily?)
    (text! "cycle-evidence-title" (if daily? "Diary evidence" "Direction and diary evidence"))
    (text! "cycle-observation-note" (if daily?
                                      "The City reports a summer daily average. Its counters include residents and visitors and can include other devices using the bikeway. The hourly table shows simulated residents during one 04:00–04:00 weekday."
                                      "The City count includes all bicycle movements recorded during the survey windows."))
    (let [paired? (and tour (not= work "city"))
          host (el "cycle-paired-rows")]
      (set! (.-hidden (el "cycle-paired")) (not paired?))
      (.replaceChildren host)
      (when paired?
        (doseq [[name run-key] [["Original weekday" "city"]
                                ["Workplace and commute assignment" work]
                                ["Bicycle outings" tour]
                                ["Workplaces, commutes and bicycle outings" rule]]]
          (let [row (.insertRow host)
                passages (get-in report ["runs" run-key "sites" index "counts"])]
            (set! (.-textContent (.insertCell row)) name)
            (set! (.-textContent (.insertCell row)) (.toLocaleString (reduce + passages)))))))
    (let [reachable (get results "reachable")]
      (set! (.-hidden (el "cycle-bound")) (nil? reachable))
      (when (some? reachable)
        (text! "cycle-bound" (str "At most " (.toLocaleString reachable)
                                  " resident bicycle trips could pass this junction during the survey hours, given their endpoints, diary times and speed ceiling."))))
    (set! (.-hidden (el "cycle-base-heading")) (nil? base))
    (text! "cycle-base-heading" (if hills "Prefer bikeways" "Shortest"))
    (text! "cycle-run-heading" (cond hills "Bikeways and gentler hills" detour "Prefer bikeways" :else "Simulated"))
    (set! (.-hidden (el "cycle-detours")) (or (nil? detour) (some? hills)))
    (set! (.-hidden (el "cycle-hills")) (nil? hills))
    (when hills
      (let [{:strs [changed baselineUphillMetres riddenUphillMetres baselineMetres riddenMetres]} hills]
        (text! "cycle-hill-effect"
               (str (.toLocaleString changed) " of " (.toLocaleString routed) " trips take a different route. "
                    "Mean uphill distance at grades of 2% or more goes from "
                    (js/Math.round (/ baselineUphillMetres (max 1 routed))) " to "
                    (js/Math.round (/ riddenUphillMetres (max 1 routed))) " m per trip. "
                    "Mean route length goes from " (js/Math.round (/ baselineMetres (max 1 routed))) " to "
                    (js/Math.round (/ riddenMetres (max 1 routed))) " m."))))
    (when (and detour (nil? hills))
      (let [{:strs [longer shortestMetres riddenMetres shortestBikewayMetres riddenBikewayMetres]} detour
            share (fn [a b] (.toFixed (* 100 (/ a (max 1 b))) 1))]
        (text! "cycle-detours"
               (str (.toLocaleString longer) " trips take a detour over one metre. Mean extra distance across all "
                    (.toLocaleString routed) " routed trips is " (js/Math.round (/ (- riddenMetres shortestMetres) (max 1 routed)))
                    " m. Distance on matched bikeways rises from " (share shortestBikewayMetres shortestMetres)
                    "% to " (share riddenBikewayMetres riddenMetres)
                    "%. This scenario assigns each off-bikeway metre the cost of " penalty
                    " bikeway metres. Riders use the shortest route if the detour exceeds their diary time."))))
    (set! (.-href (el "cycle-source")) (or (get site "source") (get report "source")))
    (let [link (el "cycle-source-location")]
      (set! (.-hidden link) (not locationSource))
      (when locationSource (set! (.-href link) locationSource)))
    (text! "cycle-date" (str date (when weather (str " · " weather))))
    (text! "cycle-coverage" (str (.toLocaleString routed) " of " (.toLocaleString legs)
                                 " bicycle legs have a distinct, reachable destination within the diary time. "
                                 (.toLocaleString unlocated) " lack a located endpoint, " (.toLocaleString colocated)
                                 " share a location and " (.toLocaleString rejected) " have no fitting route."))
    (set! (.-onclick (el "cycle-visit-site")) #(explore (clj->js point)))
    (let [host (el "cycle-directions") n (get results "diaries")]
      (.replaceChildren host)
      (doseq [[direction observed] (when-not daily? (get site "approaches"))]
        (let [row (.insertRow host)]
          (doseq [value [direction observed (get-in results ["approaches" direction])]]
            (set! (.-textContent (.insertCell row)) (str value)))))
      (text! "cycle-diaries" (if (pos? n)
                               (str "The riders counted here use " n " source " (if (= n 1) "diary" "diaries")
                                    ". The most frequent contributes " (get results "largestDiary") " passages.")
                               (if daily? "No simulated rider passed during this weekday."
                                 "No simulated rider passed during these survey hours."))))
    (.replaceChildren body)
    (doseq [[hour obs n example baseline] (map vector hours (or observed (repeat nil)) counts examples (or base (repeat nil)))]
      (let [row (.insertRow body)]
        (set! (.-textContent (.insertCell row)) (hour-label hour))
        (when-not daily? (set! (.-textContent (.insertCell row)) (str obs)))
        (when base (set! (.-textContent (.insertCell row)) (str baseline)))
        (let [cell (.insertCell row)]
          (if-let [[da i minute] example]
            (let [button (.createElement js/document "button")]
              (set! (.-textContent button) (str n))
              (.setAttribute button "aria-label" (str "Follow a cyclist passing during the " (hour-label hour) " hour"))
              (set! (.-onclick button) #(follow da i minute))
              (.append cell button))
            (set! (.-textContent cell) (str n))))))))

(defn- workplace-parent [versions]
  (or (get versions "tract-workplaces") (get versions "worksites") (get versions "outbound")))

(defn- checked-report [report comparison wanted tour-id]
  (let [v (report "versions") profile (wanted "bikeways") work (wanted "workplaces")
        baseline (get comparison "versions")]
    (when-not (and (every? #(= (wanted %) (v %)) ["atlas" "day" "streets" "cycling" "clock" "bikeways"])
                   (= tour-id (v "tours"))
                   (or (nil? work) (= work (workplace-parent v)))
                   (or (nil? profile)
                       (and (every? #(= (v %) (get baseline %)) ["atlas" "day" "streets" "legs" "cycling" "clock" "tours"])
                            (= (wanted "parentBikeways") (get baseline "bikeways"))
                            (or (nil? work) (= work (workplace-parent baseline)))
                            (= (update-vals (report "runs") #(get % "coverage"))
                               (update-vals (comparison "runs") #(get % "coverage"))))))
      (throw (js/Error. "The bicycle count report uses a different simulation release.")))
    (assoc report "comparison" comparison)))

(defn init [base parents json workplace outing follow explore]
  (let [wanted (js->clj parents) profile (wanted "bikeways")
        baseline (wanted "parentBikeways")
        parent (str/join "_" (keep wanted ["atlas" "day" "cycling" "clock" "workplaces"]))
        tour-rule #(case (outing) "ride" "cycleTours" "access" "cycleAccess" nil)
        supplement #(when (tour-rule) (wanted "tours"))
        load-report (fn [key] (-> (json (str base key ".json"))
                                  (.then (fn [p] (json (str base (aget p "version") "/counts.json"))))
                                  (.then js->clj)))
        panel (el "cycle-check") select (el "cycle-site") cache (atom {}) pending (atom #{}) shown (atom :none)
        requested (.get (js/URLSearchParams. js/location.search) "cycleCheck")
        update-url! (fn []
                      (let [url (js/URL. js/location.href)]
                        (if (.-open panel)
                          (.set (.-searchParams url) "cycleCheck" (.-value select))
                          (.delete (.-searchParams url) "cycleCheck"))
                        (.replaceState js/history nil "" url)))
        refresh! (fn refresh! []
                   (when (.-open panel)
                     (let [tour-id (supplement) key (if tour-id (str parent "_" tour-id) parent)]
                       (if-let [report (get @cache key)]
                         (do
                           (when (not= key @shown)
                             (let [pick (if (= @shown :none) requested (.-value select))]
                               (.replaceChildren select)
                               (doseq [{:strs [name key]} (report "sites")] (.add select (js/Option. name key)))
                               (when (some #(= pick (get % "key")) (report "sites")) (set! (.-value select) pick)))
                             (reset! shown key))
                           (set! (.-hidden (el "cycle-results")) false)
                           (draw! report (workplace) (tour-rule) follow explore (wanted "offBikewayCost")) (update-url!))
                         (when-not (contains? @pending key)
                           (swap! pending conj key)
                           (set! (.-hidden (el "cycle-results")) true)
                           (text! "cycle-status" "Loading bicycle counts…")
                           (-> (js/Promise.all #js [(load-report (if profile (str key "_" profile) key))
                                                    (when profile (load-report (if baseline (str key "_" baseline) key)))])
                               (.then (fn [[r comparison]]
                                        (swap! cache assoc key (checked-report r comparison wanted tour-id))
                                        (when (= tour-id (supplement)) (refresh!))))
                               (.catch (fn [e] (when (= tour-id (supplement))
                                                 (text! "cycle-status" (str "Bicycle comparison unavailable. " (.-message e))))))
                               (.finally #(swap! pending disj key))))))))]
    (set! (.-hidden panel) false)
    (set! (.-onchange select) refresh!)
    (set! (.-ontoggle panel) #(if (.-open panel) (refresh!) (update-url!)))
    (when requested (set! (.-open panel) true))
    (refresh!)
    refresh!))
