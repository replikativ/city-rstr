(ns city.ui.map-view
  "Overview colours shared by the vector-tile and local-geometry maps.")

(def palette
  {:land "#333d41" :water "#213947" :park "#40584b" :road "#a7b4b5"
   :building "#465155" :bridge "#c2af82" :label "#e0e5e6"})

(defn overview-colors [] (clj->js palette))

(defn create-map
  "The shared overview camera and navigation controls. Each dataset supplies
   its initial extent, style, attribution and compatible MapLibre constructors."
  [map-constructor navigation-constructor options]
  (let [m (new map-constructor (js/Object.assign #js {:pitch 0 :bearing 0} options))]
    (js-invoke m "addControl" (new navigation-constructor #js {:visualizePitch true}) "top-right")
    m))

(defn style-vector-basemap! [^js m]
  (doseq [layer (array-seq (.-layers (.getStyle m)))]
    (let [id (.-id layer) source (aget layer "source-layer")
          [property color]
          (case (.-type layer)
            "background" ["background-color" (:land palette)]
            "fill" ["fill-color" (case source
                                   "water" (:water palette)
                                   "building" (:building palette)
                                   "park" (:park palette)
                                   "landcover" (:park palette)
                                   (:land palette))]
            "line" (when (= source "transportation") ["line-color" (:road palette)])
            "symbol" (when (some? (some-> layer .-layout (aget "text-field")))
                       ["text-color" (:label palette)])
            nil)]
      (when property
        (.setPaintProperty m id property color)
        (when (= property "text-color") (.setPaintProperty m id "text-halo-color" (:land palette)))))))
