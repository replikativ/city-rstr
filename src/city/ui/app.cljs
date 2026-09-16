(ns city.ui.app
  "The page shell: the map and its deck.gl overlay. Everything the page shows
   is `city.ui.explorer`."
  (:require ["maplibre-gl" :as ml]
            ["@deck.gl/mapbox" :refer [MapboxOverlay]]
            [city.ui.explorer :as explorer]))

(defonce the-map (atom nil))
(defonce overlay (atom nil))

(defn- el ^js [id] (js/document.getElementById id))

(defn- warn! [message]
  (set! (.-hidden (el "map-warning")) false)
  (set! (.-textContent (el "map-warning")) message))

(def default-style
  "OpenFreeMap's positron style: vector tiles with building heights, free to use
   with attribution. A page may name another style with
   <meta name=\"city-map-style\" content=\"…\">."
  "https://tiles.openfreemap.org/styles/positron")

(defn- style []
  (or (some-> (js/document.querySelector "meta[name=city-map-style]") (.getAttribute "content"))
      default-style))

(defn- map! []
  (let [m (ml/Map. #js {:container "lab-map" :center #js [9.18 48.78] :zoom 11.5 :pitch 45 :bearing 0
                        :attributionControl #js {:compact true} :style (style)})]
    (reset! the-map m)
    ;; the camera opens tilted; without a compass there is no visible way back
    ;; to north or to a flat view
    (.addControl m (ml/NavigationControl. #js {:visualizePitch true :showZoom true :showCompass true}) "top-right")
    (.on m "error" (fn [_] (warn! "Some basemap tiles are unavailable. Data layers load independently.")))
    (.on m "load" (fn []
                    (try
                      (let [o (MapboxOverlay. #js {:interleaved false :layers #js []})]
                        (.addControl m o)
                        (reset! overlay o)
                        (explorer/draw!))
                      (catch :default _
                        (warn! "Data overlays could not render. Evidence tables and outcomes remain available.")))))))

(defn init []
  (try (map!)
       (catch :default _
         (warn! "Map rendering unavailable. Evidence tables and outcomes remain available.")
         (doseq [id ["camera" "home"]] (set! (.-disabled (el id)) true))))
  (set! (.-onclick (el "camera")) (fn [_] (explorer/camera!)))
  (set! (.-onclick (el "home")) (fn [_] (explorer/recenter!)))
  (explorer/init! {:map the-map :overlay overlay}))

(defn reload! [] (explorer/render!))
