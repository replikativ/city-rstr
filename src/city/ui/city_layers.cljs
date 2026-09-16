(ns city.ui.city-layers
  "The explorer's deck.gl layers, built from the payloads the page has loaded:
   area boundaries and rates, the 100 m population and rent cells, observed
   records, visits and revenue per venue, scenario changes, trips and people
   along the day's clock, transit stops and the area-to-area arcs. Payload
   data is reshaped once per payload set (`prepared`); `layers` then only
   filters by the current state, and `legend` describes what is drawn."
  (:require ["@deck.gl/layers" :refer [GeoJsonLayer PolygonLayer ScatterplotLayer ArcLayer]]
            ["@deck.gl/geo-layers" :refer [TripsLayer]]
            [city.ui.timeline :as time]))

(def colors {:storefront [215 142 62] :licence [111 143 196] :place [51 112 83]
             :poi [126 106 153] :building [116 122 130] :parcel [143 120 103]})
(def purpose-colors {"work" [65 94 157] "store" [198 129 37] "restaurant" [42 133 122]
                     "home" [137 90 143] "school" [170 149 39] "leisure" [78 135 78] "other" [117 128 140]})
(defonce prepared (atom nil))

(defn ring [g]
  (if (= "Polygon" (:type g)) (first (:coordinates g)) (first (first (:coordinates g)))))

(defn center [g]
  (let [r (ring g)] (when (seq r) (mapv #(/ (reduce + (map % r)) (count r)) [first second]))))

(defn- data! [payloads]
  (when-not (= payloads (:basis @prepared))
    (let [areas (:areas payloads)
          agg (into {} (map (juxt :area identity) (get-in payloads [:aggregates :areas])))
          centers (into {} (keep (fn [f] (when-let [c (center (:geometry f))] [(get-in f [:properties :name]) c])) (:features areas)))
          rates (sort (keep :visits-per-resident (vals agg)))
          lo (or (nth (vec rates) (int (* 0.05 (count rates))) nil) 0)
          hi (or (nth (vec rates) (min (max 0 (dec (count rates))) (int (* 0.95 (count rates)))) nil) 1)
          cells (mapv (fn [f] (let [[x y] (get-in f [:geometry :coordinates])]
                               (assoc (:properties f) :position [x y]
                                      :polygon [[(- x 0.00062) (- y 0.00041)] [(+ x 0.00062) (- y 0.00041)]
                                                [(+ x 0.00062) (+ y 0.00041)] [(- x 0.00062) (+ y 0.00041)]])))
                      (get-in payloads [:cells :features]))
          area-data (update areas :features
                            (fn [fs] (mapv (fn [f] (let [r (agg (get-in f [:properties :name]))]
                                                     (assoc f :properties (merge (:properties f) r
                                                                                {:rate (when r (max 0 (min 1 (/ (- (or (:visits-per-resident r) lo) lo) (max 1e-9 (- hi lo))))))})))) fs)))
          od (->> (get-in payloads [:aggregates :od]) (remove #(= (:from %) (:to %)))
                  (filter #(and (centers (:from %)) (centers (:to %)))) (sort-by :trips >) (take 60)
                  (mapv #(assoc % :source (centers (:from %)) :target (centers (:to %)))))]
      (reset! prepared {:basis payloads :areas (clj->js area-data) :cells (clj->js cells)
                        :points (clj->js (:points payloads))
                        :visits (clj->js (get-in payloads [:visits :features]))
                        :revenue (clj->js (get-in payloads [:revenue :features]))
                        :scenario (clj->js (get-in payloads [:scenario :venues]))
                        :scenario-visits (clj->js (get-in payloads [:scenario :visits :venues]))
                        ;; the district polygons carry the scenario's delta so the
                        ;; map can show the effect at city zoom, not only per venue
                        :districts (let [by-name (into {} (map (juxt :district :delta-total) (get-in payloads [:scenario :districts])))
                                         lim (apply max 1 (map #(js/Math.abs (or (:mean %) 0)) (vals by-name)))]
                                     (clj->js (update (get-in payloads [:districts]) :features
                                                      (fn [fs] (mapv (fn [f] (let [d (by-name (get-in f [:properties :name]))]
                                                                              (assoc f :properties (merge (:properties f) {:delta (:mean d) :q05 (:q05 d) :q95 (:q95 d) :lim lim}))))
                                                                     fs)))))
                        :firms (clj->js (get-in payloads [:firms :features]))
                        :stops (clj->js (get-in payloads [:stops :features]))
                        :trips (clj->js (:trips payloads)) :groups (time/group-trips (:trips payloads))
                        :od (clj->js od)})))
  @prepared)

(defn layers [{:keys [payloads overlays hour three-d elevation-scale area trail] :as state} pick!]
  (let [{:keys [areas cells points visits revenue scenario scenario-visits districts firms stops trips groups od]} (data! payloads)
        population? (overlays :population) rent? (overlays :rent)
        point-pos (fn [^js d] (.. d -geometry -coordinates))
        click (fn [kind] (fn [^js info] (when-let [d (.-object info)] (pick! kind (js->clj d :keywordize-keys true)))))
        hour-index (min 23 (int hour))]
    (clj->js
     (remove nil?
      [(when (and (overlays :scenario) scenario (seq (.-features districts)))
         ;; scenario minus baseline per Stadtbezirk, diverging: coral loses, green
         ;; gains, saturation by the posterior mean against the largest move
         (GeoJsonLayer.
          #js {:id "city-scenario-districts" :data districts :pickable true :stroked true :filled true
               :lineWidthMinPixels 1 :getLineColor #js [71 84 103 120]
               :getFillColor (fn [^js f] (let [p (.-properties f) d (.-delta p)]
                                           (if (number? d)
                                             (let [v (min 1 (/ (js/Math.abs d) (max 1 (.-lim p))))]
                                               (if (neg? d) #js [242 141 124 (+ 20 (* 150 v))] #js [111 196 154 (+ 20 (* 150 v))]))
                                             #js [0 0 0 0])))
               :onClick (click :district-delta)}))
       (when (or (overlays :areas) (overlays :choropleth))
         (GeoJsonLayer.
          #js {:id "city-areas" :data areas :pickable true :stroked true :filled true
               :lineWidthMinPixels 1 :getLineColor #js [71 84 103 180]
               :getFillColor (fn [^js f]
                               (let [p (.-properties f) r (.-rate p)]
                                 (cond
                                   (= (str (.-eid p)) (str (:eid area))) #js [229 188 106 85]
                                   (and (overlays :choropleth) (number? r))
                                   #js [(+ 45 (* r 150)) (+ 92 (* r 50)) (- 153 (* r 85)) 150]
                                   :else #js [102 123 144 15])))
               :updateTriggers #js {:getFillColor #js [(boolean (overlays :choropleth)) (:eid area)]}
               :onClick (click :area)}))
       (when (or population? rent?)
         (PolygonLayer.
          #js {:id "city-cells" :data cells :getPolygon (fn [^js d] (.-polygon d))
               :getElevation (fn [^js d] (* (or elevation-scale 1)
                                            (if rent? (* 7 (or (.-rent d) 0)) (* 0.55 (or (.-population d) 0)))))
               :extruded three-d :opacity 0.65 :pickable true
               :getFillColor (fn [^js d]
                               (if rent?
                                 (if (number? (.-rent d))
                                   (let [v (max 0 (min 1 (/ (.-rent d) 30)))]
                                     #js [(- 220 (* 85 v)) (- 203 (* 115 v)) (- 175 (* 135 v))])
                                   #js [149 149 149])
                                 (let [v (min 1 (/ (or (.-population d) 0) 400))]
                                   #js [(- 145 (* 80 v)) (- 177 (* 65 v)) (- 208 (* 40 v))])))
               :updateTriggers #js {:getFillColor rent? :getElevation #js [rent? elevation-scale]}
               :onClick (click :cell)}))
       (when (seq points)
         (GeoJsonLayer.
          #js {:id "city-observations" :parameters #js {:depthCompare "always"} :data points :pickable true :pointType "circle"
               :getPointRadius 5 :pointRadiusUnits "pixels" :pointRadiusMinPixels 3
               :getFillColor (fn [^js f] (clj->js (get colors (keyword (.. f -properties -kind)) [70 70 70])))
               :onClick (click :entity)}))
       (when (overlays :visits)
         (ScatterplotLayer.
          #js {:id "city-visits" :parameters #js {:depthCompare "always"} :data visits :getPosition point-pos :pickable true :stroked true
               :radiusUnits "pixels" :radiusMinPixels 0 :radiusMaxPixels 24
               :getRadius (fn [^js d] (let [v (or (aget (.. d -properties -hours) hour-index) 0)]
                                       (if (pos? v) (+ 2 (* 2 (js/Math.sqrt v))) 0)))
               :getFillColor #js [183 95 106 30] :getLineColor #js [161 58 87] :lineWidthMinPixels 1.5
               :updateTriggers #js {:getRadius hour-index} :onClick (click :visits)}))
       (when (overlays :revenue)
         ;; the economic day: one ring per retail venue, radius by annual revenue
         ;; summed over the three demand classes, colour by the dominant class
         ;; (food ochre, clothing plum, long-term goods slate)
         (ScatterplotLayer.
          #js {:id "city-revenue" :parameters #js {:depthCompare "always"} :data revenue :getPosition point-pos :pickable true :stroked true
               :radiusUnits "pixels" :radiusMinPixels 2 :radiusMaxPixels 40
               :getRadius (fn [^js d] (let [r (reduce + (array-seq (.. d -properties -revenue-eur-year)))]
                                       (if (pos? r) (+ 2 (* 0.012 (js/Math.sqrt r))) 0)))
               :getFillColor (fn [^js d] (let [rs (array-seq (.. d -properties -revenue-eur-year))
                                               k (.indexOf (to-array rs) (apply max rs))]
                                           (case k 0 #js [204 152 62 40] 1 #js [138 74 128 40] #js [74 96 112 40])))
               :getLineColor (fn [^js d] (let [rs (array-seq (.. d -properties -revenue-eur-year))
                                               k (.indexOf (to-array rs) (apply max rs))]
                                           (case k 0 #js [176 122 34] 1 #js [108 48 98] #js [52 74 92])))
               :lineWidthMinPixels 1.5 :onClick (click :revenue)}))
       (when (overlays :scenario)
         ;; the policy scenario: one ring per venue whose expected resident
         ;; revenue moves, radius by √|Δ| (posterior mean), green for a gain and
         ;; coral for a loss; a closed venue is drawn hollow, an opened one solid
         (ScatterplotLayer.
          #js {:id "city-scenario" :parameters #js {:depthCompare "always"} :data scenario :pickable true :stroked true :filled true
               :getPosition (fn [^js d] #js [(aget d "lon") (aget d "lat")])
               :radiusUnits "pixels" :radiusMinPixels 2 :radiusMaxPixels 60
               :getRadius (fn [^js d] (+ 2 (* 0.006 (js/Math.sqrt (js/Math.abs (or (aget (aget d "delta-total") "mean") 0))))))
               :getFillColor (fn [^js d] (let [m (or (aget (aget d "delta-total") "mean") 0) role (aget d "role")]
                                           (cond (= role "closed") #js [242 141 124 20]
                                                 (= role "opened") #js [111 196 154 150]
                                                 (pos? m) #js [111 196 154 70]
                                                 :else #js [242 141 124 70])))
               :getLineColor (fn [^js d] (if (pos? (or (aget (aget d "delta-total") "mean") 0)) #js [47 122 84] #js [176 63 45]))
               :lineWidthMinPixels 1.5 :onClick (click :scenario)}))
       (when (overlays :scenario-visits)
         ;; the same economic day under the scenario: visits gained or lost per
         ;; venue in the playhead hour, paired with the baseline by seed
         (ScatterplotLayer.
          #js {:id "city-scenario-visits" :parameters #js {:depthCompare "always"} :data scenario-visits :pickable true :stroked true :filled true
               :getPosition (fn [^js d] #js [(aget d "lon") (aget d "lat")])
               :radiusUnits "pixels" :radiusMinPixels 0 :radiusMaxPixels 30
               ;; a same-seed re-draw moves a few visits between near-equal
               ;; venues everywhere; below five visits in the hour a ring is
               ;; that noise, not the intervention, and is not drawn
               :getRadius (fn [^js d] (let [v (or (aget (aget d "delta-hours") hour-index) 0)] (if (< (js/Math.abs v) 5) 0 (+ 2 (* 2.5 (js/Math.sqrt (js/Math.abs v)))))))
               :getFillColor (fn [^js d] (if (pos? (or (aget (aget d "delta-hours") hour-index) 0)) #js [111 196 154 90] #js [242 141 124 90]))
               :getLineColor (fn [^js d] (if (pos? (or (aget (aget d "delta-hours") hour-index) 0)) #js [47 122 84] #js [176 63 45]))
               :lineWidthMinPixels 1 :updateTriggers #js {:getRadius hour-index :getFillColor hour-index :getLineColor hour-index}
               :onClick (click :scenario-visits)}))
       (when (overlays :stops)
         (ScatterplotLayer.
          #js {:id "city-stops" :parameters #js {:depthCompare "always"} :data stops :getPosition point-pos :getRadius 5 :radiusUnits "pixels"
               :pickable true :stroked true :getFillColor #js [239 236 225] :getLineColor #js [64 82 92]
               :lineWidthMinPixels 2 :onClick (click :stop)}))
       (when (overlays :trips)
         (TripsLayer.
          #js {:id "city-trips" :parameters #js {:depthCompare "always"} :data trips :getPath (fn [^js d] (.-path d)) :getTimestamps (fn [^js d] (.-timestamps d))
               :getColor (fn [^js d] (clj->js (get purpose-colors (.-purpose d) [110 110 110])))
               :currentTime (* hour 60) :trailLength trail :widthMinPixels 2 :opacity 0.85}))
       (when (overlays :people)
         (ScatterplotLayer.
          #js {:id "city-people" :parameters #js {:depthCompare "always"} :data (clj->js (keep #(time/person-at % (* hour 60)) groups))
               :getPosition (fn [^js d] (.-position d)) :getRadius 4 :radiusUnits "pixels"
               :getFillColor (fn [^js d] (if (aget d "moving?") #js [213 157 62] #js [66 78 94]))
               :pickable true :onClick (click :person)}))
       (when (overlays :od)
         (ArcLayer.
          #js {:id "city-od" :parameters #js {:depthCompare "always"} :data od :getSourcePosition (fn [^js d] (.-source d)) :getTargetPosition (fn [^js d] (.-target d))
               :getWidth (fn [^js d] (min 8 (+ 1 (/ (js/Math.sqrt (.-trips d)) 20))))
               :getSourceColor #js [71 107 162] :getTargetColor #js [194 142 62]
               :pickable true :onClick (click :flow)}))]))))

(defn legend [{:keys [overlays]}]
  (let [swatch (fn [color label] (str "<span><i style='display:inline-block;width:9px;height:9px;margin-right:5px;background:" color "'></i>" label "</span>"))]
    (str
     (when (and (overlays :population) (not (overlays :rent)))
       (swatch "linear-gradient(90deg,#91b1d0,#4170a8)" "population: 0–400 residents/~100 m cell (color clipped)"))
     (when (overlays :rent) (swatch "linear-gradient(90deg,#dccbaf,#875828)" "rent: 0–30 €/m² (color clipped) · grey: unavailable"))
     (apply str (for [[kind rgb] colors :when (overlays kind)]
                  (swatch (str "rgb(" (first rgb) "," (second rgb) "," (nth rgb 2) ")") (str "observed " (name kind)))))
     (when (overlays :visits) (swatch "#a13a57" "circles: simulated hourly visits"))
     (when (overlays :revenue) (swatch "linear-gradient(90deg,#cc983e,#8a4a80,#4a6070)" "rings: economic day, annual revenue per venue — food · clothing · long-term (dominant class)"))
     (when (overlays :scenario)
       (str (swatch "#6fc49a" "scenario: district / venue gains resident revenue") (swatch "#f28d7c" "loses · ring ∝ √|Δ €/year| · hollow: closed")))
     (when (overlays :scenario-visits) (swatch "linear-gradient(90deg,#f28d7c,#6fc49a)" "scenario: visits lost / gained per venue in this hour, same seed"))
     (when (overlays :stops) (swatch "#40525c" "transit stops / source data"))
     (when (overlays :choropleth) (swatch "linear-gradient(90deg,#2d5c99,#c38e44)" "area visits/resident: p5–p95 (clipped)"))
     (when (overlays :od) (swatch "linear-gradient(90deg,#476ba2,#c28e3e)" "simulated OD: origin → destination"))
     (when (overlays :people) (swatch "#d59d3e" "sampled people: amber moving · dark parked"))
     (when (overlays :trips)
       (apply str (for [[purpose rgb] (sort-by key purpose-colors)]
                    (swatch (str "rgb(" (first rgb) "," (second rgb) "," (nth rgb 2) ")") (str "trip: " purpose))))))))
