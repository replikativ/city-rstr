(ns city.ui.replay
  "Browser adapters for the shared replay contract."
  (:require [city.replay :as replay]
            [city.resident :as resident]
            [city.ui.replay-shell :as shell]))

(defn- runs [rows]
  (js->clj rows :keywordize-keys true))

(defn preferred-run [rows city coverage]
  (some-> (replay/preferred-run (runs rows) city coverage) clj->js))

(defn weekday-query [city coverage release]
  (clj->js (replay/weekday-query {:city city :coverage coverage :release release})))

(defn city-link [rows city minute]
  (when-let [{:keys [path query]} (replay/change-city (runs rows) city minute)]
    (str path "?" (js/URLSearchParams. (clj->js query)))))

(defn visit-at [^js visit minute]
  (let [{:keys [phase from to start end fraction]}
        (resident/visit-at {:depart (.-depart visit) :arrive (.-arrive visit)
                            :leave (.-leave visit) :finish (.-finish visit)
                            :from (.-from visit) :stop (.-stop visit) :to (.-to visit)}
                           minute)]
    (when phase
      #js {:phase (name phase) :from from :to to :start start :end end :fraction fraction})))

(defn change-study-area [href rows coverage]
  (let [url (js/URL. href)
        params (.-searchParams url)
        query (into {} (map (fn [[key value]] [key value])) (array-seq (js/Array.from params)))
        {:keys [query anchor]} (replay/change-study-area query (.-hash url) (runs rows) coverage)]
    (set! (.-search url) (str (js/URLSearchParams. (clj->js query))))
    (set! (.-hash url) anchor)
    (.-href url)))

(defn mount-inspector [initial reveal]
  (let [{:keys [select! show! open-anchor!]} (shell/mount-inspector! {:initial initial :reveal? reveal})]
    #js {:select (fn [view ^js options] (select! view (some-> options .-remember) true))
         :show show! :openAnchor open-anchor!}))

(defn mount-clock [^js options]
  (let [update-clock! (shell/mount-clock! {:play (.-play options) :seek (.-seek options) :step (.-step options)})]
    (fn [^js display]
      (update-clock! {:text (.-text display) :minute (.-minute display)
                      :playing? (.-playing display) :available? (.-available display)}))))

(defn render-result [result]
  (shell/render-result! (js->clj result :keywordize-keys true)))
