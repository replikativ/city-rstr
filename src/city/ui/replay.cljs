(ns city.ui.replay
  "Browser adapters for the shared replay contract."
  (:require [city.replay :as replay]))

(defn- runs [rows]
  (js->clj rows :keywordize-keys true))

(defn preferred-run [rows city coverage]
  (some-> (replay/preferred-run (runs rows) city coverage) clj->js))

(defn weekday-query [city coverage release]
  (clj->js (replay/weekday-query {:city city :coverage coverage :release release})))

(defn city-link [rows city minute]
  (when-let [{:keys [path query]} (replay/change-city (runs rows) city minute)]
    (str path "?" (js/URLSearchParams. (clj->js query)))))
