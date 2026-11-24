(ns city.trip-evidence
  "Release-scoped aggregate trip counts and links to synthetic resident examples."
  (:require [datahike.api :as d]))

(defn release-id [city atlas day version]
  (str "trip-demand/" city "/" atlas "/" day "/" version))

(defn present? [db id]
  (some? (d/q '[:find ?r . :in $ ?id :where [?r :entity/ext-id ?id] [?r :trip/source _]] db id)))

(defn transaction [id {:strs [city atlas day source cells]}]
  (into [{:entity/ext-id id :run/city city :run/atlas atlas :run/day day :trip/source source}]
        (mapcat
          (fn [[zone mode purpose fifths [da i minute] diaries]]
            (let [resident (when da (str "resident/" city "/" atlas "/" da "/" i))
                  cell {:entity/ext-id (str id "/" (pr-str [zone mode purpose])) :trip/release [:entity/ext-id id]
                        :trip/zone zone :trip/mode mode :trip/purpose purpose :trip/adult-fifths fifths :trip/diary diaries}]
              (if resident
                [{:entity/ext-id resident :resident/da da :resident/position i}
                 (assoc cell :trip/example [:entity/ext-id resident] :trip/minute minute)]
                [cell]))))
        cells))

(defn cells [db id]
  (let [diaries (group-by first
                  (d/q '[:find ?c ?d :in $ ?id :where [?r :entity/ext-id ?id]
                         [?c :trip/release ?r] [?c :trip/diary ?d]] db id))
        examples (into {} (map (fn [[c da i minute]] [c [da i minute]]))
                       (d/q '[:find ?c ?da ?i ?m :in $ ?id :where
                              [?r :entity/ext-id ?id] [?c :trip/release ?r] [?c :trip/example ?p]
                              [?p :resident/da ?da] [?p :resident/position ?i] [?c :trip/minute ?m]] db id))]
    (sort-by (juxt first second #(nth % 2))
             (for [[c z mode purpose n]
                   (d/q '[:find ?c ?z ?mode ?purpose ?n :in $ ?id :where
                          [?r :entity/ext-id ?id] [?c :trip/release ?r] [?c :trip/zone ?z]
                          [?c :trip/mode ?mode] [?c :trip/purpose ?purpose] [?c :trip/adult-fifths ?n]] db id)]
               [z mode purpose n (get examples c) (sort (map second (diaries c)))]))))
