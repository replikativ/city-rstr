(ns city.ui.app
  "The page shell: the map and its deck.gl overlay. Everything the page shows
   is `city.ui.explorer`."
  (:require ["maplibre-gl" :as ml]
            ["@deck.gl/mapbox" :refer [MapboxOverlay]]
            [city.ui.catalog :as catalog]
            [city.ui.overview :as overview]
            [city.ui.map-view :as view]
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
  (let [loaded? (atom false)
        fallback? (atom false)
        m (view/create-map ml/Map ml/NavigationControl #js {:container "lab-map" :center (clj->js (get-in catalog/cities [:stuttgart :center])) :zoom 11.5
                        :attributionControl #js {:compact true} :style (style)})]
    (reset! the-map m)
    (.on m "style.load" (fn [_] (view/style-vector-basemap! m)))
    (.once m "style.load" (fn [_] (reset! loaded? true)))
    (.on m "error"
         (fn [_]
           (if (and (not @loaded?) (compare-and-set! fallback? false true))
             (do (warn! "Online basemap unavailable. Showing the simulation on its area boundaries.")
                 (.setStyle m #js {:version 8 :sources #js {}
                                   :layers #js [#js {:id "background" :type "background"
                                                     :paint #js {:background-color "#e3e9e4"}}]}))
             (when-not @fallback? (warn! "Some basemap tiles are unavailable.")))))
    (.on m "load" (fn []
                    (try
                      (let [o (MapboxOverlay. #js {:interleaved false :layers #js []})]
                        (js-invoke m "addControl" o)
                        (reset! overlay o)
                        (explorer/draw!))
                      (catch :default error
                        (js/console.error "City map overlays" error)
                        (warn! "Data overlays could not render. Evidence tables and outcomes remain available.")))))))

(defn- archived-explorer! []
  (try (map!)
       (catch :default _
         (warn! "Map rendering unavailable. Evidence tables and outcomes remain available.")
         (doseq [id ["camera" "home"]] (set! (.-disabled (el id)) true))))
  (set! (.-onclick (el "camera")) (fn [_] (explorer/camera!)))
  (set! (.-onclick (el "home")) (fn [_] (explorer/recenter!)))
  (explorer/init! {:map the-map :overlay overlay}))

(defn init []
  (if (el "weekday-explorer") (overview/init) (archived-explorer!)))

(defn reload! [] (explorer/render!))
