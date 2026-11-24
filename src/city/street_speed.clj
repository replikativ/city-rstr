(ns city.street-speed
  "Illustrative segment speeds for the Stuttgart street replay, in km/h."
  (:require [city.sim.network :as net]
            [city.sim.world :as world]
            [clojure.string :as str]))

(defn- point-key [[lon lat]]
  (bit-or (bit-shift-left (Math/round (* (double lat) 1e6)) 32)
          (bit-and 0xffffffff (Math/round (* (double lon) 1e6)))))

(defn- edge-key [a b]
  (let [a (point-key a) b (point-key b)]
    (if (< a b) [a b] [b a])))

(defn- limit-kmh [tag]
  (when-let [[_ value unit] (and (string? tag) (re-matches #"(?i)\s*(\d+(?:\.\d+)?)\s*(mph|km/h)?\s*" tag))]
    (let [v (* (Double/parseDouble value) (if (= "mph" (some-> unit str/lower-case)) 1.609344 1.0))]
      (when (pos? v) v))))

(defn- profile [{:keys [highway maxspeed motor_vehicle motorcar vehicle access]}]
  (let [kind (str/replace (or highway "") #"_link$" "")
        motor (case kind
                "motorway" 90 "trunk" 65 "primary" 45 "secondary" 40 "tertiary" 35
                "living_street" 7 "service" 15 ("residential" "unclassified") 30
                ("steps" "path" "footway" "cycleway" "pedestrian" "bridleway") nil 25)]
    {:motor (when (and motor (not (#{"no" "private"} (or motorcar motor_vehicle vehicle access)))) (min motor (or (limit-kmh maxspeed) motor)))
     :walk (case kind ("motorway" "trunk") nil "steps" 3.0 5.0)
     :bike (case kind ("motorway" "trunk") nil ("steps" "footway" "pedestrian") 4.5
                 ("track" "path" "bridleway") 12.0 "cycleway" 20.0 18.0)}))

(defn streets [osm]
  (let [edges (java.util.HashMap.)
        motors (java.util.ArrayList.)
        motor-speeds (java.util.HashMap.)
        ways (net/stream-elements! osm
               (fn [ways element]
                 (if-let [points (net/usable-way element)]
                   (let [tags (:tags element) speeds (profile tags)
                         oneway (or (:oneway tags) (when (or (= "roundabout" (:junction tags))
                                                              (= "motorway" (:highway tags))) "yes"))]
                     (when (:motor speeds) (.add motors points))
                     (doseq [[a b] (partition 2 1 points)]
                       (.put edges (edge-key a b) speeds)
                       (when-let [v (:motor speeds)]
                         (doseq [[from to allowed limit] [[a b (not= "-1" oneway) (:maxspeed:forward tags)]
                                                         [b a (not (#{"yes" "true" "1"} oneway)) (:maxspeed:backward tags)]]
                                 :when allowed]
                           (.put motor-speeds [(point-key from) (point-key to)] (min v (or (limit-kmh limit) v))))))
                     (conj! ways points))
                   ways)) (transient []))
        motor (fn [a b] (.get motor-speeds [(point-key a) (point-key b)]))]
    {:ways (persistent! ways) :motor-ways motors :motor motor
     :edge (fn [a b] (assoc (.get edges (edge-key a b)) :motor (motor a b)))}))

(defn motor-router [ways speed]
  (let [g (net/build ways)
        xs ^doubles (:lon g) ys ^doubles (:lat g)
        point (fn [i] [(aget xs i) (aget ys i)])
        offsets ^ints (:offsets g) targets ^ints (:targets g) weights ^doubles (:weights g)
        allowed (int-array (alength offsets))]
    ;; Compact legal directed arcs in place. Multiplying metres by 90/speed
    ;; preserves an admissible distance heuristic while minimizing travel time.
    (dotimes [i (:n g)]
      (let [a (point i)]
        (aset allowed (inc i)
              (loop [j (aget offsets i) out (aget allowed i)]
                (if (= j (aget offsets (inc i))) out
                  (let [b (aget targets j)]
                    (if-let [v (speed a (point b))]
                      (do (aset targets out b)
                          (aset weights out (* (aget weights j) (/ 90.0 v)))
                          (recur (inc j) (inc out)))
                      (recur (inc j) out))))))))
    (let [graph (net/scratch (net/index (assoc g :offsets allowed)))
          cache (java.util.HashMap.)]
      (fn [from to]
        (let [a (apply net/nearest graph from) b (apply net/nearest graph to)
              access (world/haversine-m (first from) (second from) (aget xs a) (aget ys a))
              egress (world/haversine-m (first to) (second to) (aget xs b) (aget ys b))
              key [a b]]
          (when (and (not= a b) (<= (max access egress) 200))
            (when-not (.containsKey cache key)
              (.put cache key (some->> (net/shortest-node-path graph a b) (mapv point))))
            (when-let [path (.get cache key)]
              [path (* 0.012 access) (* 0.012 egress)])))))))

(defn timed-path [edge points mode start end]
  (let [hour (mod (quot (long start) 60) 24)
        ;; An assumed peak-period slowdown, applied at departure.
        traffic (if (or (<= 7 hour 8) (<= 16 hour 17)) 0.75 1.0)]
    (loop [pairs (seq (partition 2 1 points)) offsets [0.0]]
      (if-let [[[a b :as from] [c d :as to]] (first pairs)]
        (let [{:keys [walk bike motor]} (edge from to)
              speed (case mode "walk" walk "bike" bike "car" (some-> motor (* traffic))
                          "transit" (when motor (* traffic (min motor 35))) nil)]
          (when speed
            (recur (next pairs) (conj offsets (+ (peek offsets) (/ (* 0.06 (world/haversine-m a b c d)) speed))))))
        (let [needed (peek offsets) available (- end start)]
          (when (and (pos? needed) (<= needed available))
            (mapv #(+ start (* available (/ % needed))) offsets)))))))
