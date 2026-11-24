(ns city.street-replay
  "Restore street geometry between the retained waypoints of a published Stuttgart trip."
  (:require [city.sim.network :as net]
            [city.street-speed :as speed]
            [clojure.data.json :as json]
            [clojure.java.io :as io]))

(defn- coord-key [x y]
  (bit-or (bit-shift-left (Math/round (* 1e5 (double y))) 32)
          (bit-and (Math/round (* 1e5 (double x))) 0xffffffff)))

(defn- road-geometry [graph]
  (let [xs ^doubles (:lon graph) ys ^doubles (:lat graph)
        nodes (java.util.HashMap.)
        cache (java.util.HashMap.)]
    (dotimes [i (:n graph)] (.put nodes (coord-key (aget xs i) (aget ys i)) i))
    (fn [path]
      ;; Off-network access stubs have no street geometry in the archive.
      (let [via (dedupe (keep (fn [[x y]] (.get nodes (coord-key x y))) path))]
        (when (next via)
          (loop [road [(first via)] pairs (seq (partition 2 1 via))]
            (if-let [[a b] (first pairs)]
              (let [key [a b]
                    piece (or (.get cache key)
                              (let [p (net/shortest-node-path graph a b)]
                                (when (> (.size cache) 60000) (.clear cache))
                                (.put cache key p) p))]
                (when (seq piece) (recur (into road (next piece)) (next pairs))))
              (mapv (fn [i] [(/ (Math/round (* 1e6 (aget xs i))) 1e6)
                             (/ (Math/round (* 1e6 (aget ys i))) 1e6)]) road))))))))

(defn -main [osm trip-file directory]
  (let [{:keys [ways edge motor-ways motor]} (speed/streets osm)
        route (road-geometry (net/scratch (net/build ways)))
        drive (speed/motor-router motor-ways motor)
        totals (atom {})
        hours (mapv #(io/writer (io/file directory (str % ".jsonl"))) (range 24))]
    (try
      (with-open [reader (io/reader trip-file)]
        (doseq [{:keys [pid purpose mode path timestamps]} (json/read reader :key-fn keyword)
                :let [start (first timestamps) end (peek timestamps)]
                :when (< start end)
                :let [original (route path)
                      initial (when original (speed/timed-path edge original mode start end))
                      [alternative access egress] (when (and (nil? initial) (#{"car" "transit"} mode) (next path))
                                                   (drive (first path) (peek path)))
                      geometry (or alternative original)
                      times (or initial (when alternative (speed/timed-path edge alternative mode
                                                                             (+ start access) (- end egress))))
                      visible? (and times (< (first times) 1440) (pos? (peek times)))
                      status (cond (or (>= start 1440) (<= end 0) (and times (not visible?))) :outsideDay
                                   initial :shown times :rerouted geometry :infeasible :else :unrouted)
                      _ (swap! totals update-in [mode status] (fnil inc 0))]
                :when visible?]
          (let [row (json/write-str {:id (str pid) :agent pid :mode mode :purpose purpose
                                     :path geometry :times times})]
            (doseq [hour (range (max 0 (long (Math/floor (/ (first times) 60.0))))
                               (min 24 (long (Math/ceil (/ (peek times) 60.0)))))]
              (.write ^java.io.Writer (hours hour) (str row "\n"))))))
      (spit (io/file directory "timing.json") (json/write-str @totals))
      (finally (doseq [w hours] (.close ^java.io.Writer w))))))
