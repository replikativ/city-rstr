;; The likelihood on Stuttgart, CPU against GPU: the simulator at the
;; posterior mean (turnover per district and class, expected distance per
;; class), then a short Metropolis–Hastings fit with each backend from the
;; same seed, whose chains should end in the same states.
;;   clojure -J-Xmx7g -J-Xss8m -J--add-modules=jdk.incubator.vector -M -i dev/checks/likelihood_stuttgart.clj
;; Needs data/, the evidence store and a GPU.
(require '[city.demo.stuttgart :as demo] '[city.store :as store] '[city.sim.device :as dev])

(store/connect!)
(def ctx (-> (demo/build-world) demo/segment-inputs))
(def theta (demo/posterior-mean (demo/load-posterior)))
(defn timed [f] (let [t (System/nanoTime) r (f)] [r (/ (- (System/nanoTime) t) 1e6)]))
(defn rel [a b] (/ (Math/abs (- (double a) (double b))) (max 1e-300 (Math/abs (double b)))))

(def handle (let [[h ms] (timed #(dev/open-dense (:dense ctx)))] (println :open-ms (Math/round ms)) h))
(let [cpu (demo/segmented-simulator ctx) gpu (demo/segmented-simulator (assoc ctx :device handle))
      [a cpu-ms] (timed #(cpu theta)) _ (gpu theta) [b gpu-ms] (timed #(gpu theta))]
  (println :simulator :cpu-ms (Math/round cpu-ms) :gpu-ms (Math/round gpu-ms)
           :turnover-max-rel (reduce max (for [[k v] (:turnover a)] (rel (get-in b [:turnover k]) v)))
           :km-max-rel (reduce max (for [[s v] (:km a)] (rel (get-in b [:km s]) v)))))
(dev/close! handle)

(let [[p ms-cpu] (timed #(demo/fit-posterior ctx :n 4 :iterations 3 :seed 7))
      [q ms-gpu] (timed #(demo/fit-posterior ctx :n 4 :iterations 3 :seed 7 :backend :gpu))]
  (println :fit :cpu-ms (Math/round ms-cpu) :gpu-ms (Math/round ms-gpu)
           :same-states (= (:values p) (:values q))
           :max-rel (let [nums #(filter number? (tree-seq coll? seq %))]
                      (reduce max 0.0 (map rel (nums (:values q)) (nums (:values p)))))))
(shutdown-agents)
(System/exit 0)
