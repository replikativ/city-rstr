(ns city.ui.overview
  (:require ["maplibre-gl" :as ml]
            ["@deck.gl/mapbox" :refer [MapboxOverlay]]
            ["@deck.gl/layers" :refer [ScatterplotLayer]]
            ["./agent_positions.js" :refer [loadPositions]]
            [city.replay :as replay]
            [city.ui.catalog :as catalog]
            [city.ui.map-view :as view]))

(defn- ^js el [id] (js/document.getElementById id))
(defn- put! [id value] (set! (.-textContent (el id)) value))
(defn- json [url]
  (-> (js/fetch url) (.then (fn [^js r] (if (.-ok r) (.json r) (throw (js/Error. (str "Unavailable: " url))))))))
(defn- option! [id title value] (.add (el id) (js/Option. title value)))
(defn- quantity [n] (.toLocaleString n js/undefined #js {:maximumFractionDigits 0}))
(defn- time-label [minute]
  (str (.padStart (str (quot minute 60)) 2 "0") ":" (.padStart (str (mod minute 60)) 2 "0")))

(defn- segment-index [times t]
  (loop [lo 0 hi (dec (alength times))]
    (if (= 1 (- hi lo)) lo
      (let [mid (quot (+ lo hi) 2)]
        (if (<= (aget times mid) t) (recur mid hi) (recur lo mid))))))

(defn- position [^js leg t]
  (let [ts (.-times leg) path (.-path leg) end (dec (alength ts))]
    (when (and (pos? end) (<= (aget ts 0) t) (< t (aget ts end)))
      (let [lo (segment-index ts t) hi (inc lo)
            a (aget path lo) b (aget path hi) f (/ (- t (aget ts lo)) (- (aget ts hi) (aget ts lo)))]
        #js [(+ (aget a 0) (* f (- (aget b 0) (aget a 0))))
             (+ (aget a 1) (* f (- (aget b 1) (aget a 1))))]))))

(defn- segment-kmh [^js leg t]
  (let [ts (.-times leg) i (segment-index ts t)
        a (aget (.-path leg) i) b (aget (.-path leg) (inc i))
        lat (/ (* (+ (aget a 1) (aget b 1)) js/Math.PI) 360)
        metres (* 111195 (js/Math.hypot (* (- (aget b 0) (aget a 0)) (js/Math.cos lat))
                                         (- (aget b 1) (aget a 1))))]
    (/ (* 0.06 metres) (- (aget ts (inc i)) (aget ts i)))))

(defn- trail [^js leg t end-point]
  (let [times (.-times leg) path (.-path leg)
        start (max (aget times 0) (- t 6)) points #js []]
    (when (< start t)
      (.push points (position leg start))
      (dotimes [i (alength times)]
        (when (< start (aget times i) t) (.push points (aget path i))))
      (.push points end-point)
      points)))

(defn- area-km2 [^js geometry]
  (let [rad (/ js/Math.PI 180)
        ring-area (fn [ring]
                    (js/Math.abs
                     (* 0.5 6371.0088 6371.0088
                        (reduce + (map (fn [[a b]]
                                         (* (- (aget b 0) (aget a 0)) rad
                                            (+ (js/Math.sin (* rad (aget a 1))) (js/Math.sin (* rad (aget b 1))))))
                                       (partition 2 1 (array-seq ring)))))))
        polygons (if (= "Polygon" (.-type geometry)) [(.-coordinates geometry)] (array-seq (.-coordinates geometry)))]
    (reduce + (for [polygon polygons :let [[outer & holes] (array-seq polygon)]]
                (- (ring-area outer) (reduce + (map ring-area holes)))))))

(defn- sampled-slot [agent size total]
  (when (and (number? agent) (pos? size))
    (let [slot (js/Math.floor (/ (* (+ agent 0.5) size) total))]
      (when (and (< slot size) (= agent (js/Math.floor (/ (* (+ slot 0.5) total) size)))) slot))))

(defn- bounds [^js geo]
  (let [b (ml/LngLatBounds.)]
    (letfn [(visit [coords]
              (if (number? (aget coords 0)) (.extend b coords)
                  (doseq [child (array-seq coords)] (visit child))))]
      (doseq [f (array-seq (.-features geo))] (visit (.. f -geometry -coordinates))))
    b))

(def empty-geo #js {:type "FeatureCollection" :features #js []})

(defn- context! [^js m]
  (-> (json "lab/context-dark.json")
      (.then (fn [style]
               (let [sources (aget style "sources")
                     local (aget sources "regional-context")
                     layers (array-seq (aget style "layers"))
                     fallback #{"water" "landcover_wood" "landuse_residential" "waterway"
                                "highway_major_inner" "highway_minor" "highway_motorway_inner"
                                "place_city" "place_town" "place_suburb"}]
                 ;; Source tile templates resolve relative to the document on mounted previews.
                 (aset local "tiles" #js [(str (.-href (js/URL. "lab/stuttgart-context/" (.-baseURI js/document)))
                                                "{z}/{x}/{y}.pbf")])
                 (.addSource m "regional-context" local)
                 (doseq [l layers :when (fallback (aget l "id"))]
                   (.addLayer m (js/Object.assign #js {} l #js {:id (str "regional-" (aget l "id"))
                                                                 :source "regional-context"}) "origin-fill"))
                 (.addSource m "openmaptiles" (aget sources "openmaptiles"))
                 (doseq [l layers :when (= "openmaptiles" (aget l "source"))]
                   (.addLayer m l "origin-fill")))))
      (.catch #(js/console.warn "Basemap context unavailable" %))))

(defn- return-camera [query]
  (when-let [value (.get query "camera")]
    (let [[lon lat zoom :as parts] (mapv js/Number (.split value ","))]
      (when (and (= 3 (count parts)) (<= -180 lon 180) (<= -85 lat 85) (<= 0 zoom 22))
        #js {:center #js [lon lat] :zoom zoom}))))

(defn init []
  (let [url (js/URL. (.-href js/location)) q (.-searchParams url)
        camera (return-camera q)
        initial (js/Number (or (.get q "minute") 480))
        state (atom {:minute (if (and (js/Number.isInteger initial) (<= 0 initial 1439)) initial 480)})
        ^js m (view/create-map ml/Map ml/NavigationControl
                           #js {:container "overview-map" :zoom (if camera (.-zoom camera) 10)
                                :center (or (some-> camera .-center) (clj->js (get-in catalog/cities [(keyword (.-value (el "run"))) :center])))
                                :transformRequest (fn [url kind]
                                                    #js {:url (if (and (= kind "Glyphs") (.endsWith url "/0-255.pbf"))
                                                                (.-href (js/URL. "lab/stuttgart-context/latin.pbf" (.-baseURI js/document))) url)}) :attributionControl #js {:compact true :customAttribution "© BKG 2026 dl-de/by-2-0 · © OpenStreetMap contributors · Statistics Canada · City of Vancouver · Landeshauptstadt Stuttgart"} :style #js {:version 8 :glyphs "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf" :sources #js {}
                                 :layers #js [#js {:id "land" :type "background" :paint #js {:background-color "#141414"}}]}})
        ^js overlay (MapboxOverlay. #js {:interleaved true :layers #js []})
        selected (fn [] (.-value (el "run")))]
    (letfn [(scenario []
              (get (:cases @state) (.-value (el "metric"))))
            (venues! [c]
              (let [rows (some-> c (aget "venues"))
                    change (some-> c (aget "changeLabel"))
                    hourly (some-> c (aget "hourlyVisits"))
                    currency (some-> c (aget "basketCurrency"))
                    basket (when currency (js/Number (.-value (el "basket"))))
                    site (some-> c (aget "openingSite"))
                    roles (some-> c (aget "roles"))
                    _ (when (and rows (not (identical? rows (:venue-rows @state)))
                                 (not (some #(= (:venue @state) (aget % 0)) (array-seq rows))))
                        (let [ids (when roles (array-seq (js/Object.keys roles)))
                              preferred (or site (some #(when (= "opened" (aget roles %)) %) ids)
                                            (some #(when (= "closed" (aget roles %)) %) ids))]
                          (swap! state assoc :venue preferred)))
                    minute (:minute @state)
                    hour (quot minute 60)
                    events (some-> c (aget "visitEvents"))
                    completed (when events (take-while #(<= (aget % 0) minute) (array-seq events)))
                    losses (when events (frequencies (keep #(aget % 1) completed)))
                    gained (count completed)
                    delta-at (fn [id] (if (= id site) gained (- (get losses id 0))))
                    venue (:venue @state)]
                (set! (.-hidden (el "venue-control")) (nil? rows))
                (set! (.-hidden (el "basket-control")) (nil? currency))
                (let [changed? (not (identical? rows (:venue-rows @state)))]
                  (when changed?
                    (let [entries (sort-by #(aget % 1) (when rows (array-seq rows)))]
                      (swap! state assoc :venue-rows rows :venue-index (into {} (map (juxt #(aget % 0) identity) entries)))
                      (.replaceChildren (el "venue"))
                      (option! "venue" "Select a shop" "")
                      (doseq [r entries] (option! "venue" (str (aget r 1) " · " (aget r 0)) (aget r 0)))))
                  (when (or changed? (not= [basket gained] (:sales-frame @state)))
                    (let [features (for [[id r] (:venue-index @state)
                                         :let [v (if events (delta-at id) (aget r (if change 4 3)))]]
                                     #js {:type "Feature" :geometry #js {:type "Point" :coordinates (aget r 2)}
                                          :properties #js {:id id :value (* (or basket 1) (or v 0))
                                                           :role (when hourly (aget (aget c "roles") id))}})]
                      (.setData (.getSource m "venues") #js {:type "FeatureCollection" :features (to-array features)})
                      (swap! state assoc :sales-frame [basket gained]))))
                (when-not (= [hourly (when hourly hour)] (:hourly-frame @state))
                  (swap! state assoc :hourly-frame [hourly (when hourly hour)])
                  (.setLayoutProperty m "revenue-rings" "visibility" (if hourly "visible" "none"))
                  (.setLayoutProperty m "shops" "visibility" (if hourly "none" "visible"))
                  (.setPaintProperty m "revenue-rings" "circle-radius"
                                     #js ["min" 60 #js ["+" 2 #js ["*" (if currency 0.65 0.006) #js ["sqrt" #js ["abs" #js ["get" "value"]]]]]])
                  (let [index (:venue-index @state)
                        points (when hourly
                                 (for [id (array-seq (js/Object.keys hourly))
                                       :let [delta (aget (aget hourly id) hour) r (get index id)]
                                       :when (and r (>= (js/Math.abs delta) (if currency 1 5)))]
                                   #js {:type "Feature" :geometry #js {:type "Point" :coordinates (aget r 2)}
                                        :properties #js {:id id :value delta}}))]
                    (.setData (.getSource m "hourly-shops") #js {:type "FeatureCollection" :features (to-array points)})))
                (.setFilter m "selected-shop" #js ["==" #js ["get" "id"] (or venue "")])
                (set! (.-value (el "venue")) (or venue ""))
                (let [r (get (:venue-index @state) venue)
                      label (fn [v] (if (some? v) (str (quantity v) " " (aget c "venueUnit")) "unavailable"))]
                  (put! "retail-basis" (when c
                                       (if (= "vancouver" (.-city (:run @state)))
                                         (when currency "All resident diaries screened. Eligible walking grocery visits count once. Incoming workers and other modes are outside this estimate.")
                                         "Milaneo spending changes use population demand and fitted shop-choice probabilities. Hourly visit changes use a sampled weekday. The map limit affects only markers.")))
                  (put! "shop-sales"
                        (when site
                          (let [total (aget (get (:venue-index @state) site) 4)
                                arrivals (aget (aget hourly site) hour)]
                            (str "East Hastings · " (when events
                                                      (str "CAD " (quantity (* gained basket)) " by " (time-label minute)
                                                           " · CAD " (quantity (* basket (reduce + 0 (vals losses)))) " diverted so far · "))
                                 "CAD " (quantity (* total basket)) " in weekday walking sales · "
                                 arrivals " arrivals from " (time-label (* hour 60)) " to " (time-label (* (mod (inc hour) 24) 60))))))
                  (set! (.-hidden (el "shop-comparison")) (not (and change r)))
                  (when (and change r)
                    (let [money (fn [v] (if (nil? v) "Unavailable"
                                          (if currency (str currency " " (quantity (* basket v)) " / weekday")
                                              (label v))))]
                      (put! "shop-baseline" (money (aget r 3)))
                      (put! "shop-change" (money (aget r 4)))
                      (put! "shop-with-opening" (when (and currency (some? (aget r 3)) (some? (aget r 4)))
                                                  (money (+ (aget r 3) (aget r 4)))))
                      (put! "shop-hour" (when hourly
                                          (if-let [hours (aget hourly venue)]
                                            (str (quantity (aget hours hour)) " visits · " (time-label (* hour 60)))
                                            "Unavailable")))
                      (put! "shop-so-far" (when events
                                            (str currency " " (quantity (* basket (delta-at venue))) " · " (time-label minute))))
                      (put! "shop-interval" (when (some? (aget r 5))
                                              (str (quantity (aget r 5)) " to " (label (aget r 6)))))))
                  (put! "venue-info" (when rows
                                       (cond (and change r) (if currency "Modeled walking sales" (aget c "baselineLabel"))
                                             r (str (aget c "baselineLabel") " · " (label (aget r 3)))
                                             :else "Select a shop to inspect its modeled results."))))))
            (geometry! [geo]
              (when-not (identical? geo (:geo @state))
                (let [district (or (:initial-district @state)
                                   (some-> (.-selectedOptions (el "area")) (aget 0) .-text))]
                  (swap! state assoc :geo geo :initial-district nil)
                  (.setData (.getSource m "areas") geo)
                  (.replaceChildren (el "area"))
                  (doseq [f (array-seq (aget geo "features"))]
                    (option! "area" (.. f -properties -label) (.-id f))
                    (when (= district (.. f -properties -label))
                      (set! (.-value (el "area")) (.-id f)))))))
            (link! []
              (when-let [^js run (:run @state)]
                (let [minute (:minute @state) city (.-city run)]
                  (if-let [person (when-not (scenario) (:person @state))]
                    (.set q "traveller" person)
                    (.delete q "traveller"))
                  (.set q "people" (.-value (el "people-mode")))
                  (.set q "limit" (if (.-checked (el "all-agents")) "all" (.-value (el "agent-limit"))))
                  (if-let [v (when (some-> (scenario) (aget "venues")) (:venue @state))] (.set q "venue" v) (.delete q "venue"))
                  (if (or (:focus @state) (some-> (scenario) (aget "geometry")))
                    (.set q "district" (.-text (aget (.-selectedOptions (el "area")) 0)))
                    (.delete q "district"))
                  (if (some-> (scenario) (aget "basketCurrency"))
                    (.set q "basket" (.-value (el "basket")))
                    (.delete q "basket"))
                  (.set q "metric" (.-value (el "metric")))
                  (.set q "city" city) (.set q "release" (.-release run)) (.set q "minute" (str minute))
                  (js/history.replaceState nil "" (.-href url)))))
            (limit-of [total]
              (if (.-checked (el "all-agents")) total
                  (min total (max 0 (js/Math.floor (js/Number (.-value (el "agent-limit"))))))))
            (roster! []
              (let [{:keys [epoch frame minute scene run agents legs]} @state
                    total (+ (aget run "population") (or (aget run "inbound") 0))
                    size (limit-of total) key [epoch minute size legs]]
                (cond
                  frame
                  (when (not= key (:population-frame @state))
                    (let [xy (frame (mod (- minute (aget scene "dayStart")) 1440) size)]
                      (let [routed (volatile! 0)]
                        (doseq [leg (array-seq legs)
                                :let [slot (sampled-slot (aget leg "agent") size total)]
                                :when (some? slot)]
                          (when (position leg minute)
                            ;; The moving marker takes this roster slot for the duration of the leg.
                            (aset xy (* 2 slot) js/NaN)
                            (aset xy (inc (* 2 slot)) js/NaN)
                            (vswap! routed inc)))
                        (put! "agent-count" (str (quantity size) " of " (quantity total) " agents · "
                                                 (quantity @routed) " moving on street paths. Grey dots mark the last modeled stop and jump when the next stop begins.")))
                      (.setProps overlay #js {:layers #js [(ScatterplotLayer.
                        #js {:id "resident-positions" :beforeId "trails" :data #js {:length size :attributes #js {:getPosition #js {:value xy :size 2}}}
                             :getRadius 1.4 :radiusUnits "pixels" :getFillColor #js [180 180 180 125]})]})
                      (swap! state assoc :population-frame key)))
                  (nil? agents) (put! "agent-count" "Roster positions unavailable for this release.")
                  (not (:loading-positions @state))
                  (do (swap! state assoc :loading-positions true)
                      (put! "agent-count" "Loading the full agent roster…")
                      (-> (loadPositions (str "data/overview/" agents ".gz") total)
                          (.then (fn [f] (when (= epoch (:epoch @state))
                                          (swap! state assoc :frame f) (render!))))
                          (.catch (fn [e] (when (= epoch (:epoch @state))
                                           (swap! state assoc :loading-positions false)
                                           (put! "agent-count" (.-message e))))))))))
            (draw-people! []
              (let [{:keys [legs minute person scene]} @state
                    roster? (and (nil? (scenario)) (= "roster" (.-value (el "people-mode"))))
                    routed? (and (nil? (scenario)) (not roster?))
                    limit (limit-of js/Number.MAX_SAFE_INTEGER)
                    points #js [] paths #js [] found (volatile! nil) available (volatile! 0)
                    total (+ (aget (:run @state) "population") (or (aget (:run @state) "inbound") 0))
                    t (+ minute (get @state :fraction 0))]
                (if roster? (roster!)
                    (when (:population-frame @state)
                      (.setProps overlay #js {:layers #js []}) (swap! state dissoc :population-frame)))
                (when (or routed? roster?)
                  (let [previous (:visible-ids @state)
                        retained? (fn [leg] (and previous (.has previous (.-id leg))))
                        candidates (array-seq legs)
                        ranked (if (and routed? previous (< limit (alength legs)))
                                 (concat (filter retained? candidates) (remove retained? candidates))
                                 candidates)
                        ordered (if person
                                  (concat (filter #(= person (.-id %)) candidates)
                                          (remove #(= person (.-id %)) ranked))
                                  ranked)
                        visible (js/Set.)]
                  (doseq [leg ordered]
                    (when-let [p (position leg t)]
                      (vswap! available inc)
                      (when (if roster? (some? (sampled-slot (aget leg "agent") (min limit total) total)) (< (alength points) limit))
                        (.add visible (.-id leg))
                        (when (= person (.-id leg)) (vreset! found leg)
                          (when (:follow @state) (.setCenter m p)))
                        (when-let [line (when (.-checked (el "show-trails")) (trail leg t p))]
                          (.push paths #js {:type "Feature" :geometry #js {:type "LineString" :coordinates line}
                                            :properties #js {:selected (= person (.-id leg))}}))
                        (.push points #js {:type "Feature" :geometry #js {:type "Point" :coordinates p}
                                           :properties #js {:id (.-id leg) :selected (= person (.-id leg))}}))))
                  (swap! state assoc :visible-ids visible))
                  (when routed?
                   (let [idx (mod (- minute (aget scene "dayStart")) 1440)
                        travel (.indexOf (aget scene "areas") "travelling")]
                    (put! "agent-count" (str (quantity (alength points)) " of " (quantity @available)
                                             " active routed sample paths · " (quantity (aget (aget (aget scene "presence") idx) travel))
                                             " travelling in the modeled population.")))))
                (.setData (.getSource m "trails") #js {:type "FeatureCollection" :features paths})
                (.setData (.getSource m "people") #js {:type "FeatureCollection" :features points})
                (put! "person" (when (and person (nil? (scenario))) (str "Traveller " person " · " (if-let [leg @found]
                                     (str (aget leg "mode") " · " (quantity (segment-kmh leg t)) " km/h · " (aget leg "purpose")) "outside displayed leg"))))
                (doseq [id ["clear-person" "follow-person"]] (set! (.-hidden (el id)) (or (nil? person) (some? (scenario)))))
                (.setAttribute (el "follow-person") "aria-pressed" (str (boolean (:follow @state))))))
            (trace-file [h]
              (let [key (aget (aget (:trace-index @state) "hours") h)]
                (or (get-in @state [:chunks key])
                    (let [promise (json (str "data/overview/" key ".json"))]
                      (swap! state update :chunks #(assoc (select-keys % [(:last-chunk @state)]) key promise))
                      (swap! state assoc :last-chunk key)
                      promise))))
            (hour! [h]
              (let [{:keys [trace-index epoch]} @state token [epoch h]]
                (when (and trace-index (not= token (:hour @state)))
                  (swap! state assoc :hour token)
                  (-> (trace-file h)
                      (.then (fn [legs] (when (= token (:hour @state)) (swap! state assoc :legs legs) (draw-people!)
                                                 (-> (trace-file (mod (inc h) 24)) (.catch (fn [_] nil))))))
                      (.catch (fn [e] (when (= token (:hour @state)) (do (swap! state assoc :hour nil :chunks {}) (put! "status" (.-message e))))))))))
            (connections! [s hour area show?]
              (let [key [(:epoch @state) show? hour area]]
                (when (not= key (:connection-key @state))
                  (swap! state assoc :connection-key key)
                  (let [centers (:centers @state)
                        totals (when show?
                                 (reduce (fn [acc [departure arrival from to weight]]
                                           (if (and (not= from to) (centers from) (centers to))
                                             (cond
                                               (and (= area to) (= hour arrival)) (update acc [from "in"] (fnil + 0) weight)
                                               (and (= area from) (= hour departure)) (update acc [to "out"] (fnil + 0) weight)
                                               :else acc) acc)) {} (array-seq (aget s "flows"))))
                        features (for [[[other direction] weight] totals]
                                   #js {:type "Feature" :properties #js {:direction direction :weight weight}
                                        :geometry #js {:type "LineString" :coordinates #js [(centers area) (centers other)]}})]
                    (.setData (.getSource m "od") #js {:type "FeatureCollection" :features (to-array features)})
                    (put! "od-legend" (when (seq totals)
                                        "Area connections · blue arriving, coral departing. Width shows journey count."))))))
            (select-area! []
              (swap! state assoc :focus true)
              (when-let [f (some #(when (= (.-id %) (js/Number (.-value (el "area")))) %)
                                 (array-seq (some-> (:geo @state) (aget "features"))))]
                (.fitBounds m (bounds #js {:features #js [f]}) #js {:padding 75 :maxZoom 12 :duration 350}))
              (render!))
            (catchment! [zoom?]
              (let [{:keys [origins scene]} @state on? (and origins (.-checked (el "catchment")) (nil? (scenario)))]
                (doseq [layer ["origin-fill" "origin-edge"]]
                  (.setLayoutProperty m layer "visibility" (if on? "visible" "none")))
                (put! "origin-info" (when on? "Click a municipality for its commuter count to Stuttgart."))
                (when (and zoom? scene)
                  (.fitBounds m (bounds (if on? origins (aget scene "geography"))) #js {:padding 40 :duration 350}))))
            (render! []
              (when-let [^js s (:scene @state)]
                (let [minute (:minute @state) i (mod (- minute (.-dayStart s)) 1440)
                      metric (.-value (el "metric")) c (scenario)
                      values (some-> c (aget "values"))
                      row (if c (aget values (if (= 1 (alength values)) 0 i))
                              (if (#{"none" "presence" "density"} metric) (aget (.-presence s) i)
                                  (aget (aget s metric) (quot i 60))))
                      value (fn [id] (if (= metric "density") (/ (aget row id) (get (:km2 @state) id)) (aget row id)))
                      geo (or (some-> c (aget "geometry")) (.-geography s))
                      _ (geometry! geo)
                      area (js/Number (.-value (el "area")))
                      features (aget geo "features")
                      peak (reduce max 1 (map #(js/Math.abs (value (.-id %))) (array-seq features)))]
                  (.setPaintProperty m "areas" "fill-opacity" (if (= metric "none") 0 0.65))
                  (.setPaintProperty m "areas" "fill-color"
                                     (if (some-> c (aget "hourlyVisits"))
                                       #js ["interpolate" #js ["linear"] #js ["coalesce" #js ["feature-state" "level"] 0] -1 "#dc806c" 0 "#303030" 1 "#76c59d"]
                                       #js ["interpolate" #js ["linear"] #js ["coalesce" #js ["feature-state" "level"] 0] -1 "#e8a773" 0 "#303030" 0.35 "#427b8f" 1 "#a2d8ed"]))
                  (doseq [f (array-seq features)]
                    (.setFeatureState m #js {:source "areas" :id (.-id f)}
                                      #js {:level (/ (value (.-id f)) peak) :selected (= area (.-id f))}))
                  (set! (.-hidden (el "trace-control")) (boolean c))
                  (put! "count" (str (aget (or (some-> c (aget "areas")) (.-areas s)) area) " · " (quantity (value area)) " "
                                     (if c (aget c "unit")
                                         (case metric ("none" "presence") "people present" "density" "people present / km²" "arrivals" "arrivals this hour" "departures this hour"))
                                     (when-let [low (some-> c (aget "low"))]
                                       (str " · 90% interval " (quantity (aget low area)) " to "
                                            (quantity (aget (aget c "high") area))))))
                  (put! "legend" (when-not (= metric "none") (str "Area shading · " (if (some #(neg? (aget row (.-id %))) (array-seq features))
                                                             (str (quantity (- peak)) " to ") "0 to ") (quantity peak))))
                  (when (or (some-> c (aget "venues")) (:venue-rows @state)) (venues! c))
                  (connections! s (quot i 60) area (and (nil? c) (.-checked (el "show-connections"))))
                  (put! "flows" (cond
                                  (some-> c (aget "openingSite"))
                                  (str (aget c "summary") (if (aget c "visitEvents") " Rings accumulate sales change at each modeled arrival." " Rings show weekday sales change.") " Filled circles show visit change for the whole hour. Green gains · coral losses."
                                       (when-let [inventory (aget c "inventory")] (str " " inventory ".")))
                                  (some-> c (aget "hourlyVisits"))
                                  (str "Districts and outer rings show annual spending change. Filled circles show shop visits gained or lost from "
                                       (time-label (* 60 (quot minute 60))) " (changes of 5 or more). Green gains · coral losses.")
                                  :else (str (some-> c (aget "summary"))
                                       (when-let [inventory (some-> c (aget "inventory"))] (str " · " inventory)))))
                  (let [fixed? (and c (= 1 (alength values)) (nil? (aget c "hourlyVisits")))]
                    (doseq [id ["play" "minute" "speed" "motion"]]
                      (set! (.-disabled (el id)) (boolean fixed?)))
                    (when fixed?
                      (swap! state assoc :playing false)
                      (put! "play" "Play"))
                    (put! "clock" (if fixed? "Whole period" (time-label minute))))
                  (when-let [totals (when-not c (:flows @state))]
                    (let [cell (get totals [(quot i 60) area]) in (get cell 0 0) out (get cell 1 0)]
                      (put! "flows" (str "Trips across area boundaries this hour · " (.toLocaleString in) " in / "
                                         (.toLocaleString out) " out"))))
                  (set! (.-value (el "minute")) minute)
                  (when-not c (hour! (quot minute 60))) (draw-people!) (link!))))
            (load! [entry]
              (let [id (:release entry) epoch (random-uuid)]
                (set! (.-checked (el "show-connections")) false)
                (swap! state assoc :epoch epoch :visible-ids nil :hourly-frame nil :venue nil :venue-index {} :venue-rows nil :chunks {} :frame nil :population-frame nil :loading-positions false :focus false :origins nil :scene nil :fraction 0 :cases {} :geo nil :trace-index nil :hour nil :legs #js [] :person nil :follow false :run nil)
                (.setProps overlay #js {:layers #js []})
                (.setLayoutProperty m "shops" "visibility" "visible")
                (.setLayoutProperty m "revenue-rings" "visibility" "none")
                (put! "agent-count" "")
                (set! (.-hidden (el "venue-control")) true) (put! "venue-info" "") (put! "retail-basis" "")
                (set! (.-hidden (el "basket-control")) true) (put! "shop-sales" "") (set! (.-hidden (el "shop-comparison")) true)
                (put! "status" "Loading weekday…") (put! "count" "") (put! "legend" "") (put! "person" "")
                (doseq [^js opt (array-seq (.querySelectorAll (el "metric") "[data-scenario]"))] (.remove opt))
                (put! "flows" "")
                (.replaceChildren (el "area"))
                (doseq [id ["trails" "od" "origins" "venues" "hourly-shops"]] (.setData (.getSource m id) empty-geo))
                (put! "origin-info" "") (put! "od-legend" "")
                (.setData (.getSource m "roads") empty-geo) (.setData (.getSource m "areas") empty-geo) (.setData (.getSource m "people") empty-geo)
                (set! (.-disabled (el "play")) true)
                (set! (.-disabled (.querySelector js/document "[data-replay-menu]")) true)
                (-> (js/Promise.all #js [((.-cityLoadManifest js/window) (:city entry) id json)
                                         (json (str "data/overview/" id ".json"))
                                         (json (str "data/overview/" id "-traces.json"))
                                         (json (str "data/overview/" id "-cases.json"))])
                    (.then (fn [[^js run ^js ptr ^js traces ^js cases-ptr]]
                             (when-not (and (= id (.-release ptr) (.-release traces) (.-release cases-ptr))
                                            (re-matches #"[0-9a-f]{64}" (aget cases-ptr "cases")) (= 24 (alength (.-hours traces)))
                                            (re-matches #"[0-9a-f]{64}" (.-scene ptr)))
                               (throw (js/Error. "Incompatible weekday release.")))
                             (-> (js/Promise.all #js [(json (str "data/overview/" (.-scene ptr) ".json"))
                                                      (json (str "data/overview/" (aget traces "roads") ".json"))
                                                      (json (str "data/overview/" (aget cases-ptr "cases") ".json"))
                                                      (when-let [origins (aget traces "origins")] (json (str "data/overview/" origins ".json")))])
                                 (.then (fn [[^js s roads cases origins]]
                                          (when (= epoch (:epoch @state))
                                            (when-not (and (= id (.-release s)) (= 1 (.-version s))
                                                           (= (+ (.-population run) (if (aget run "regionalWorkers") (.-inbound run) 0)) (.-population s)))
                                              (throw (js/Error. "Weekday totals and release disagree.")))
                                            (let [outside (.indexOf (aget s "areas") "outside")
                                                  mapped (set (map #(aget % "id") (array-seq (.. s -geography -features))))
                                                  flows (reduce (fn [result row]
                                                                  (let [[depart arrive from to n] row]
                                                                    (if (or (= from to)
                                                                            (not (or (contains? mapped from) (= from outside)))
                                                                            (not (or (contains? mapped to) (= to outside)))) result
                                                                        (cond-> result
                                                                          (contains? mapped from) (update-in [[depart from] 1] (fnil + 0) n)
                                                                          (contains? mapped to) (update-in [[arrive to] 0] (fnil + 0) n)))))
                                                                {} (array-seq (.-flows s)))]
                                              (doseq [[idx c] (map-indexed vector (array-seq cases))]
                                                (let [k (str "case-" idx)
                                                      ^js opt (js/Option. (aget c "label") k)]
                                                  (.setAttribute opt "data-scenario" "")
                                                  (.add (el "metric") opt)
                                                  (swap! state assoc-in [:cases k] c)))
                                              (let [k (.get q "metric")]
                                                (set! (.-value (el "metric"))
                                                      (if (= k "retail") (or (some (fn [[key c]] (when (and (aget c "venues") (nil? (aget c "changeLabel"))) key)) (:cases @state)) "none")
                                                      (if (or (#{"none" "density" "presence" "arrivals" "departures"} k)
                                                              (and (= id (.get q "release")) (get (:cases @state) k))) k "none"))))
                                              (swap! state assoc  :origins origins
                                                     :km2 (into {} (map (fn [f] [(.-id f) (area-km2 (.-geometry f))]) (array-seq (.. s -geography -features))))
                                                     :centers (into {} (for [f (array-seq (.. s -geography -features))]
                                                                         [(.-id f) (.toArray (.getCenter (bounds #js {:features #js [f]})))]))
                                                     :focus (and (= id (.get q "release")) (.has q "district"))
                                                     :initial-district (when (= id (.get q "release")) (.get q "district"))
                                                     :venue (when (= id (.get q "release")) (.get q "venue"))
                                                     :scene s :agents (aget ptr "agents") :run run :trace-index traces :flows flows
                                                     :person (when (= id (.get q "release"))
                                                               (let [pid (.get q "traveller")]
                                                                 (when (and pid (re-matches (if (= "stuttgart" (.-city run))
                                                                                              #"[0-9]+" #"(?:[0-9]+/[0-9]+|incoming/[0-9]+-[0-9]+/[0-9]+)") pid))
                                                                   pid)))))
                                            (.setAttribute (.querySelector js/document "[data-replay-menu]") "data-replay-menu" (.-city run))
                                            (set! (.-hidden (el "catchment-control")) (nil? origins))
                                            (.setData (.getSource m "origins") (or origins empty-geo))
                                            (catchment! false)
                                            (.setPaintProperty m "roads" "line-opacity"
                                                               (if (= "stuttgart" (.-city run))
                                                                 #js ["interpolate" #js ["linear"] #js ["zoom"] 8 0.04 11 0.13 15 0.4]
                                                                 0.48))
                                            (.setData (.getSource m "roads") roads)
                                            (if-let [saved (when (= id (.get q "release")) (return-camera q))]
                                              (.jumpTo m saved)
                                              (.fitBounds m (bounds (aget s "geography")) #js {:padding 45 :duration 0}))
                                            (set! (.-disabled (.querySelector js/document "[data-replay-menu]")) false)
                                            (set! (.-href (el "evidence")) (str (.-city run) "-model.html"))
                                            (put! "status" (str (.-label run) " · " (.toLocaleString (.-population run)) " residents"
                                                                (cond (pos? (or (.-inbound run) 0)) (str " · " (quantity (.-inbound run)) " inbound commuters")
                                                                      (= "region" (.-coverage run)) " · resident cohort only"
                                                                      :else "")
                                                                (when (= id (:replacement @state)) " · Showing current release for an older link")))
                                            (set! (.-disabled (el "play")) false) (render!)))))))
                    (.catch #(when (= epoch (:epoch @state)) (put! "status" (.-message %)))))))
            (choose! [entry]
              (if (:map-ready? @state)
                (load! entry)
                (swap! state assoc :pending-run entry)))
            (start! []
              (-> (json "data/runs/current.json")
                  (.then (fn [rows]
                           (let [runs (js->clj rows :keywordize-keys true)
                                 by-id (into {} (map (juxt :release identity) runs))
                                 run (or (by-id (.get q "release"))
                                         (first (filter #(and (= (.get q "city") (:city %)) (= "region" (:coverage %))) runs))
                                         (first (filter #(= (.get q "city") (:city %)) runs))
                                         (first runs))]
                             (when (and (.has q "release") (nil? (by-id (.get q "release"))))
                               (swap! state assoc :replacement (:release run)))
                             (.replaceChildren (el "run"))
                             (when-not run (throw (js/Error. "No published weekdays are available.")))
                             (doseq [city (distinct (map :city runs))]
                               (option! "run" (str (.toUpperCase (subs city 0 1)) (subs city 1)) city))
                             (set! (.-value (el "run")) (:city run))
                             (set! (.-disabled (el "run")) false)
                             (set! (.-onchange (el "run"))
                                   #(choose! (or (replay/preferred-run runs (selected) "region")
                                               (replay/preferred-run runs (selected) "city"))))
                             (choose! run))))
                  (.catch #(put! "status" (.-message %)))))]
      (when (.-matches (js/matchMedia "(max-width: 600px), (max-height: 550px)"))
        (set! (.-open (.querySelector js/document ".overview-panel")) false))
      (start!)
      (.on m "moveend"
           (fn []
             (let [center (.wrap (.getCenter m))
                   position (.join #js [(.toFixed (.-lng center) 6) (.toFixed (.-lat center) 6)
                                         (.toFixed (.getZoom m) 4)] ",")]
               (.setAttribute (el "overview-map") "data-camera" position)
               (when (:run @state)
                 (.set q "camera" position)
                 (js/history.replaceState nil "" (.-href url))))))
      (.on m "load"
           (fn []
             (.addControl m overlay)
             (doseq [id ["areas" "roads" "trails" "people" "od" "origins" "venues" "hourly-shops"]] (.addSource m id #js {:type "geojson" :data empty-geo}))
             (.addLayer m #js {:id "origin-fill" :type "fill" :source "origins" :paint #js {:fill-color "#9985ad" :fill-opacity #js ["interpolate" #js ["linear"] #js ["get" "flow"] 0 0.06 6000 0.48]}})
             (.addLayer m #js {:id "origin-edge" :type "line" :source "origins" :paint #js {:line-color "#b2a2c4" :line-width 0.8}})
             (.addLayer m #js {:id "areas" :type "fill" :source "areas" :paint #js {:fill-color #js ["interpolate" #js ["linear"] #js ["coalesce" #js ["feature-state" "level"] 0] -1 "#e8a773" 0 "#303030" 0.35 "#427b8f" 1 "#a2d8ed"]}})
             (.addLayer m #js {:id "edges" :type "line" :source "areas" :paint #js {:line-color "#555555" :line-width #js ["case" #js ["boolean" #js ["feature-state" "selected"] false] 2.5 1]}})
             (.addLayer m #js {:id "roads" :type "line" :source "roads"
                               :paint #js {:line-color "#a8a8a8" :line-opacity 0.48
                                          :line-width #js ["match" #js ["get" "kind"] "bridge" 1.7 "arterial" 1 0.5]}})
             (.addLayer m #js {:id "od" :type "line" :source "od"
                               :paint #js {:line-color #js ["match" #js ["get" "direction"] "in" "#8dcdf5" "#f39280"]
                                          :line-opacity 0.45 :line-offset #js ["match" #js ["get" "direction"] "in" 1 -1]
                                          :line-width #js ["interpolate" #js ["linear"] #js ["get" "weight"] 1 0.4 400 1.5 2000 3]}})
             (.addLayer m #js {:id "trails" :type "line" :source "trails" :paint #js {:line-color "#ffae55" :line-opacity #js ["case" #js ["get" "selected"] 0.9 0.55] :line-width #js ["case" #js ["get" "selected"] 2.8 1.25]}})
             (.addLayer m #js {:id "people" :type "circle" :source "people" :paint #js {:circle-color "#f3be70" :circle-opacity #js ["case" #js ["get" "selected"] 1 0.76] :circle-radius #js ["case" #js ["get" "selected"] 5 2.3]}})
             (.addLayer m #js {:id "shops" :type "circle" :source "venues"
                               :paint #js {:circle-radius #js ["interpolate" #js ["linear"] #js ["abs" #js ["get" "value"]] 0 2 50 4 1000000 5 10000000 8]
                                          :circle-color #js ["case" #js [">" #js ["get" "value"] 0] "#91ccdf" #js ["<" #js ["get" "value"] 0] "#f3a06b" "#aaa"]
                                          :circle-opacity 0.75}})
             (let [sign #js ["case" #js [">" #js ["get" "value"] 0] "#82d5a8" "#f28d7c"]
                   radius (fn [scale cap] #js ["min" cap #js ["+" 2 #js ["*" scale #js ["sqrt" #js ["abs" #js ["get" "value"]]]]]])]
               (.addLayer m #js {:id "revenue-rings" :type "circle" :source "venues" :layout #js {:visibility "none"}
                                 :filter #js ["!=" #js ["get" "value"] 0]
                                 :paint #js {:circle-radius (radius 0.006 60) :circle-color sign :circle-stroke-color sign
                                            :circle-opacity #js ["match" #js ["get" "role"] "closed" 0.035 "opened" 0.45 0.1]
                                            :circle-stroke-width 1.25}})
               (.addLayer m #js {:id "visit-circles" :type "circle" :source "hourly-shops"
                                 :paint #js {:circle-radius (radius 2.5 30) :circle-color sign :circle-opacity 0.45
                                            :circle-stroke-color sign :circle-stroke-width 0.8}}))
             (.addLayer m #js {:id "selected-shop" :type "circle" :source "venues" :filter #js ["==" #js ["get" "id"] ""]
                               :paint #js {:circle-radius 9 :circle-opacity 0 :circle-stroke-color "#fff" :circle-stroke-width 2}})
             (.on m "click" (fn [e]
                              (when-let [f (first (array-seq (.queryRenderedFeatures m (.-point e) #js {:layers #js ["visit-circles" "revenue-rings" "shops" "people" "areas" "origin-fill"]})))]
                                (case (.. f -layer -id)
                                  ("shops" "visit-circles" "revenue-rings") (do (set! (.-open (.querySelector js/document ".overview-panel")) true)
                                              (swap! state assoc :venue (.. f -properties -id)) (render!))
                                  "people" (do (swap! state assoc :person (.. f -properties -id)) (render!))
                                  "origin-fill" (put! "origin-info" (str (.. f -properties -name) " · "
                                                                        (quantity (aget (.-properties f) "flow")) " inbound commuters in the register"))
                                  (do (set! (.-value (el "area")) (.-id f)) (select-area!))))))
             (swap! state assoc :map-ready? true)
             (when-let [entry (:pending-run @state)]
               (swap! state dissoc :pending-run)
               (load! entry))
             (context! m)))
      (.addEventListener js/window "pageshow"
                         (fn [event]
                           (when (.-persisted event)
                             (.resize m)
                             (when-let [run (:run @state)]
                               (set! (.-value (el "run")) (aget run "city"))
                               (render!)))))
      (doseq [id ["people-mode" "agent-limit" "show-trails" "show-connections"]] (set! (.-onchange (el id)) #(do (set! (.-disabled (el "agent-limit")) (.-checked (el "all-agents"))) (render!))))
      (set! (.-onchange (el "all-agents"))
            #(do (set! (.-disabled (el "agent-limit")) (.-checked (el "all-agents"))) (render!)))
      (when (#{"0" "10" "25" "50" "75" "100"} (.get q "basket"))
        (set! (.-value (el "basket")) (.get q "basket")))
      (set! (.-onchange (el "basket")) render!)
      (set! (.-onchange (el "venue")) #(do (swap! state assoc :venue (not-empty (.-value (el "venue")))) (render!)))
      (set! (.-onchange (el "metric")) #(do (catchment! false) (render!)))
      (set! (.-onchange (el "catchment")) #(catchment! true))
      (set! (.-onchange (el "area")) select-area!)
      (set! (.-onclick (el "reset-area"))
            #(when-let [s (:scene @state)]
               (set! (.-checked (el "show-connections")) false)
               (swap! state assoc :focus false :follow false)
               (.fitBounds m (bounds (aget s "geography")) #js {:padding 45 :duration 350}) (render!)))
      (when (= "roster" (.get q "people")) (set! (.-value (el "people-mode")) "roster"))
      (when-let [limit (.get q "limit")]
        (cond (= limit "all") (do (set! (.-checked (el "all-agents")) true) (set! (.-disabled (el "agent-limit")) true))
              (re-matches #"[0-9]{1,8}" limit) (set! (.-value (el "agent-limit")) limit)))
      (set! (.-onclick (el "follow-person")) #(do (swap! state update :follow not) (render!)))
      (set! (.-onclick (el "clear-person")) #(do (swap! state assoc :person nil :follow false) (render!)))
      (set! (.-oninput (el "minute")) #(do (swap! state assoc :minute (.-valueAsNumber (el "minute")) :fraction 0 :tick (js/performance.now)) (render!)))
      (set! (.-onclick (el "play")) #(do (swap! state (fn [s] (assoc s :playing (not (:playing s)) :tick (js/performance.now)))) (put! "play" (if (:playing @state) "Pause" "Play"))))
      (js/setInterval
       (fn []
         (let [{:keys [playing scene minute fraction tick]} @state
               now (js/performance.now) smooth? (= "smooth" (.-value (el "motion")))]
           (when (and playing scene (or smooth? (>= (- now tick) 1000)))
             (let [elapsed (/ (min (- now tick) 1000) 1000)
                   delta (/ (* elapsed (js/Number (.-value (el "speed")))) 60)
                   next-time (+ minute (or fraction 0) delta)
                   new-minute (mod (js/Math.floor next-time) 1440)]
               (swap! state assoc :minute new-minute :tick now
                      :fraction (- next-time (js/Math.floor next-time)))
               (if (= minute new-minute) (draw-people!) (render!)))))) 100))))
