(ns city.ui.vancouver.route-timeline
  (:require [city.ui.timeline :as time]))

(defn track [path timestamps minute trail-minutes]
  (let [{:keys [position trail]} (time/recent-path {:path path :timestamps timestamps} minute trail-minutes)]
    #js {:position (to-array position)
         :trail (when trail (into-array (map to-array trail)))}))
