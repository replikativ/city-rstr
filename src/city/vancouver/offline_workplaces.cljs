(ns city.vancouver.offline-workplaces
  "Resolve resident workplace and mode assignments for the evidence builders."
  (:require [clojure.string :as str]
            [goog.object :as obj]))

(defn- trip-state [by-area local changes paid places direct mode-keys labels preserve-modes? rule d i tpl current]
  (when current
      (let [[start _ recorded a b] current
            slots (nth paid tpl)
            worker (.get (aget by-area d) i)
            selected-rule (rule)
            site-changes (changes selected-rule)
            matched (when site-changes (.get (aget site-changes d) i))
            overrides (when (and matched (or (.has matched a) (.has matched b))) matched)
            place (when worker (places (aget worker 1)))
            assigned (when (contains? (get direct tpl) start)
                       (case selected-rule
                         ("local" "sites") (.get (aget local d) i)
                         "tracts" (when-not preserve-modes? (.get (aget local d) i))
                         "usual" (when worker (aget worker 2))
                         nil))
            apply? (and (number? assigned) (<= 0 ^number assigned))
            method (if (#{"local" "sites" "tracts"} selected-rule) "neighbourhood-fitted mode" "usual commute mode")
            site-method (if (= selected-rule "tracts") "census tract workplace scenario" "matched workplace")
            mode (if apply? (mode-keys assigned) recorded)]
        (cond
          (and worker (or (contains? slots a) (contains? slots b)))
          #js {:mode mode :external true :assignedMode (when apply? mode)
               :description
               (if (= "stop" mode)
                 (str "Usual workplace · " place)
                 (str (if apply? (str (labels assigned) " · " method) (str/replace mode "-" " ")) " · "
                      (cond (and (slots a) (slots b)) "between workplace stops in "
                            (slots a) "from "
                            :else "to ")
                      place " · route unresolved"))}
          apply? #js {:replaceMode mode :overrides overrides :method (str method (when overrides (str " · " site-method)))}
          overrides #js {:overrides overrides :method site-method}))))

(defn- site-index [assignments report]
  (when report
    (let [index (.map assignments (fn [_] (js/Map.)))]
      (doseq [[d i slot _ dest] (obj/get report "changes")]
        (let [group (aget index d)]
          (when-not (.has group i) (.set group i (js/Map.)))
          (.set (.get group i) slot dest)))
      index)))

(defn resident-trips
  "Resolve a diary part against the same workplace and mode assignments in playback and validation."
  [report assignments local-rows sites tract rule]
  (let [paid (mapv set (js->clj (obj/get report "slots")))
        direct (mapv set (js->clj (obj/get report "directStarts")))
        local (when local-rows (.map local-rows (fn [rows] (js/Map. rows))))
        changes {"sites" (site-index assignments sites) "tracts" (site-index assignments tract)}
        by-area (.map assignments (fn [rows] (js/Map. (.map rows (fn [row] #js [(aget row 0) row])))))]
    (partial trip-state by-area local changes paid (js->clj (obj/get report "destinations"))
             direct (js->clj (obj/get report "modeKeys")) (js->clj (obj/get report "modes"))
             (boolean (when tract (obj/get tract "preserveDiaryModes"))) rule)))
