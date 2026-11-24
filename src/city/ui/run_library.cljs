(ns city.ui.run-library
  "Browse published city weekdays and reopen experiments from the same browser database."
  (:require [clojure.string :as str]
            [city.opening-hours :as hours]
            [city.replay :as replay]
            [city.ui.experiments :as store]))

(defn- weekday-time [minute]
  (str (.padStart (str (mod (quot minute 60) 24)) 2 "0") ":"
       (.padStart (str (mod minute 60)) 2 "0") (when (>= minute 1440) " +1")))

(defn- opening-url [{:keys [market site hours clock workplaces rule basket activated openings jointRun]} visit]
  (let [p (js/URLSearchParams. #js {:marketRun market :shop site :hours hours})]
    (when clock (.set p "clock" clock))
    (when jointRun (.set p "jointRun" jointRun))
    (when (#{"ride" "access"} rule) (.set p "cycleTours" rule))
    (when workplaces (.set p "workplaces" "census") (.set p "commute" rule))
    (when (some? basket) (.set p "basket" (str basket)))
    (when (some? activated)
      (.set p "shopPlay" "1") (.set p "opened" (str activated))
      (.set p "minute" (str activated)))
    (when (seq openings) (.set p "openings" (js/JSON.stringify (clj->js openings))))
    (when visit
      (let [[da i slot minute] visit]
        (doseq [[k v] [["da" da] ["person" (inc i)] ["minute" minute] ["visit" slot]]]
          (.set p k (str v)))))
    (str "cityday.html?" p)))

(defn opening-link [record visit]
  (opening-url (js->clj record :keywordize-keys true) (when visit (array-seq visit))))

(defn- el [id] (js/document.getElementById id))

(defn- row! [list title href description]
  (let [li (js/document.createElement "li") a (js/document.createElement "a")
        detail (js/document.createElement "small")]
    (set! (.-href a) href)
    (set! (.-textContent a) title)
    (set! (.-textContent detail) description)
    (.append li a detail)
    (.append list li)
    li))

(defn- district-comparison! [parent href scenarios]
  (let [details (js/document.createElement "details") summary (js/document.createElement "summary")
        label (js/document.createElement "label") select (js/document.createElement "select")
        list (js/document.createElement "ul")
        districts (sort (set (mapcat #(map first (:districts %)) scenarios)))
        million (fn [n] (str (when (neg? n) "−") "€" (.toFixed (/ (js/Math.abs n) 1e6) 1) "m"))
        show! (fn []
                (.replaceChildren list)
                (doseq [[idx {:keys [label districts]}] (map-indexed vector scenarios)
                        :let [row (some #(when (= (.-value select) (first %)) %) districts)]
                        :when row]
                  (let [[_ mean low high] row]
                    (row! list label (str href "&metric=case-" idx "&district=" (js/encodeURIComponent (first row)))
                          (str "Mean annual change in resident spending " (million mean)
                               " · 90% posterior interval " (million low) " to " (million high))))))]
    (set! (.-textContent summary) "Compare district turnover")
    (set! (.-textContent label) "District ")
    (doseq [district districts] (.add select (js/Option. district district)))
    (when (some #{"Mitte"} districts) (set! (.-value select) "Mitte"))
    (set! (.-onchange select) show!)
    (.append label select) (.append details summary label list) (.append parent details)
    (show!)))

(defn- render! [{:keys [runs openings]} current]
  (let [picker (el "library-city")
        choices (sort (set (map :city (concat runs openings))))
        requested (.get (.-searchParams (js/URL. js/location.href)) "city")
        chosen (or (some #{requested} choices) (first choices))
        show! (fn []
                (let [city (.-value picker)
                      saved (sort-by :saved > (filter #(= city (:city %)) openings))
                      published (replay/order-runs (filter #(= city (:city %)) runs) current)
                      candidates (filter #(current (:release %)) published)
                      primary (or (replay/preferred-run candidates city "region") (replay/preferred-run candidates city "city"))]
                  (set! (.-href (el "back-to-map")) (str "explorer.html" (if (seq js/location.search) js/location.search (str "?city=" city))))
                  (set! (.-hidden (el "archived-section")) (empty? (remove #{primary} published)))
                  (doseq [id ["published-runs" "archived-runs" "local-openings"]] (.replaceChildren (el id)))
                  (set! (.-hidden (el "local-experiments")) (empty? saved))
                  (doseq [{:keys [label population inbound release coverage scenarios matchedCensusAreas jointRun incomingTransit outboundRoad outboundTransit]} published]
                    (let [page (if (= city "stuttgart") "lab.html" "cityday.html")
                          query (replay/weekday-query {:city city :coverage coverage :release release})
                          href (str page "?" (js/URLSearchParams. (clj->js query)))
                          map-url (str "explorer.html?city=" city "&release=" release)
                          main? (= release (:release primary))
                          li (row! (el (if main? "published-runs" "archived-runs")) label (if (current release) map-url href)
                                   (str (.toLocaleString population "en-CA") " residents"
                                        (when (and inbound (pos? inbound))
                                          (str " + " (.toLocaleString inbound "en-CA") " inbound commuters"))
                                        " · " (cond (empty? current) "Indexed release " main? "Current release " (current release) "Comparison release " :else "Archived release ")
                                        (subs release 0 10)))]
                      (when matchedCensusAreas
                        (let [link (js/document.createElement "a")]
                          (set! (.-href link) (str "population.html?boundary=1&dayRun=" release))
                          (set! (.-textContent link) (str "Census coverage · all " (.toLocaleString matchedCensusAreas "en-CA") " areas"))
                          (.append li link)))
                      (when (and jointRun incomingTransit)
                        (let [link (js/document.createElement "a")]
                          (set! (.-href link) (str href "&downtown=am&commuters=combined#downtown"))
                          (set! (.-textContent link) "Compare Downtown rush hour")
                          (.append li link)))
                      (when outboundRoad
                        (let [link (js/document.createElement "a")]
                          (set! (.-href link) (str href "&downtown=am&commuters=combined&roadGate=city&roadDirection=1"
                                                   "&roadVehicles=outboundWork#incoming-road-crossings"))
                          (set! (.-textContent link) "Follow outbound work drives")
                          (.append li link)))
                      (when outboundTransit
                        (let [link (js/document.createElement "a")]
                          (set! (.-href link) (str href "&downtown=am#outbound-transit-work"))
                          (set! (.-textContent link) "Follow outbound transit commutes")
                          (.append li link)))
                      (when (and main? (seq scenarios)) (district-comparison! li map-url scenarios))))
                  (doseq [{:keys [address hours activated openings rule basket purchase localWalk shoppingOutings jointRun visit-count resident-count diverted] :as opening} saved]
                    (row! (el "local-openings") address (opening-url opening nil)
                          (str visit-count " visits by " resident-count " residents · " diverted
                               " diverted · " (- visit-count diverted) " newly feasible · "
                               (:label (hours/schedule hours)) " · "
                               (when (some? activated) (str "opened at " (weekday-time activated) " · "))
                               (when (seq openings) (str (count openings) " storefronts · "))
                               (if jointRun
                                 (str "combined weekday · " (if shoppingOutings "added shopping walks" "diary grocery trips"))
                                 (case rule "access" "survey bicycle access" "ride" "universal bicycle access"
                                       "diary" (if shoppingOutings "added shopping walks" "original travel diary") rule))
                               (when localWalk " · local grocery walks")
                               (when (= purchase "bc2010") " · 2010 grocery shares")
                               (when (some? basket) (str " · $" basket " per visit")))))))]
    (set! (.-hidden (el "live-laboratory")) (boolean (seq current)))
    (.replaceChildren picker)
    (doseq [city choices] (.add picker (js/Option. (str/capitalize city) city)))
    (set! (.-value picker) (or chosen ""))
    (set! (.-disabled picker) (empty? choices))
    (set! (.-onchange picker)
          (fn [] (let [url (js/URL. js/location.href)]
                   (set! (.-search url) "")
                   (.set (.-searchParams url) "city" (.-value picker))
                   (js/history.replaceState nil "" url)
                   (show!))))
    (show!)))

(defn- load-manifests [catalog]
  (js/Promise.all
   (into-array
    (for [row (array-seq catalog)
          :let [id (.-release row)]]
      (do
        (when-not (and (string? id) (re-matches #"[a-f0-9]{64}" id))
          (throw (js/Error. "Invalid release in published catalogue.")))
        (-> (js/fetch (str "data/runs/" id ".json"))
            (.then (fn [r] (if (.-ok r) (.json r) (throw (js/Error. "Weekday manifest unavailable.")))))
            (.then (fn [manifest]
                     (when-not (and (= id (.-release manifest)) (= (.-city row) (.-city manifest)))
                       (throw (js/Error. "Weekday manifest and catalogue disagree.")))
                     manifest))))))))

(defn init []
  (let [msg (el "library-status")]
    (set! (.-textContent msg) "")
    (-> (js/fetch "data/runs/current.json" #js {:cache "no-cache"})
        (.then (fn [r] (if (.-ok r) (.json r) (throw (js/Error. "Published run catalogue unavailable.")))))
        (.then load-manifests)
        (.then #(js->clj % :keywordize-keys true))
        (.catch (fn [_] (set! (.-textContent msg) "Published catalogue unavailable. Showing runs indexed in this browser.") []))
        (.then (fn [runs]
                 (let [current (set (map :release runs))]
                   (-> (js/Promise.resolve nil)
                       (.then #(store/run-library runs))
                       (.then #(render! % current))
                       (.catch (fn [_]
                                 (set! (.-textContent msg) "Browser storage unavailable. Showing published weekdays.")
                                 (render! {:runs runs} current))))))))))
