;; The likelihood's allocation on a device against `candidates/reduce-dense`,
;; at Stuttgart's size (34,650 cells × 3,637 candidates) on synthetic
;; distances: largest relative difference per bucket, and time per call.
;;   clojure -J-Xmx6g -J--add-modules=jdk.incubator.vector -M -i dev/checks/likelihood_device.clj   (CITY_DEVICE, default ze:0)
;; Needs a Level Zero or OpenCL device and about 1.5 GB of device memory.
(require '[city.sim.candidates :as cand] '[city.sim.device :as dev])

(def device (keyword (or (System/getenv "CITY_DEVICE") "ze:0")))
(def rng (java.util.Random. 11))
(def n 34650) (def nc 3637) (def nb 24)
(def dense {:cand (int-array (range nc)) :n n :nc nc
            :dist (let [a (float-array (* n nc))] (dotimes [i (alength a)] (aset a i (float (* 25000.0 (.nextDouble rng))))) a)})
(def attract (double-array (map #(if (zero? (mod % 11)) 0.0 (* 500.0 (Math/exp (* 3.0 (.nextDouble rng))))) (range nc))))
(def opts {:cell-value (double-array (map #(if (zero? (mod % 3)) 0.0 (* 5000.0 (.nextDouble rng))) (range n)))
           :cell-pop (long-array (map #(if (zero? (mod % 3)) 0 (inc (mod % 40))) (range n)))
           :bucket (int-array (map #(mod % nb) (range nc))) :n-buckets nb})

(defn rel [a b] (/ (Math/abs (- (double a) (double b))) (max 1e-300 (Math/abs (double b)))))
(defn timed [f] (let [t (System/nanoTime) r (f)] [r (/ (- (System/nanoTime) t) 1e6)]))

(def handle (let [[h ms] (timed #(dev/open-dense dense :device device))] (println :open-ms (Math/round ms)) h))
(def worst
  (reduce max 0.0
          (for [spec [{:kernel :power :alpha 1.0 :beta 2.0 :d0-m 500.0}
                      {:kernel :power :alpha 0.8 :beta 1.6 :d0-m 700.0}
                      {:kernel :power :alpha 1.2 :beta 2.7 :d0-m 300.0}]]
            (let [[a cpu-ms] (timed #(cand/reduce-dense dense attract spec opts))
                  _ (dev/reduce-dense handle dense attract spec opts)          ; warm
                  [b gpu-ms] (timed #(dev/reduce-dense handle dense attract spec opts))
                  r (reduce max (rel (:expected-distance-m b) (:expected-distance-m a))
                            (map rel (:bucket b) (:bucket a)))]
              (println (select-keys spec [:alpha :beta :d0-m]) :cpu-ms (Math/round cpu-ms) :gpu-ms (Math/round gpu-ms) :max-rel r)
              r))))
(dev/close! handle)
(println :LIKELIHOOD-DEVICE-CHECK (if (< worst 1e-12) :equal {:max-rel worst}))
(shutdown-agents)
(System/exit (if (< worst 1e-12) 0 1))
