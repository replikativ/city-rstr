(ns city.sim.publication-test
  "What the simulation server does with a published run, and how the world
   places workers."
  (:require [clojure.test :refer [deftest is]]
            [city.sim.cityworld :as cw]
            [city.sim.day :as d2]
            [city.sim.network :as net]
            [city.sim.serve :as serve]))

(deftest lazy-traces-use-the-published-configuration
  ;; a stride the run was not traced at is traced on demand with the run's own
  ;; seed and diary-mode settings, not the defaults
  (let [seen (atom [])]
    (with-redefs [serve/outputs (atom {"stuttgart" {:world {:city :stuttgart :daily-tables {}}
                                                   :config {:city :stuttgart :seed 37
                                                            :p-keep-diary-mode 0.15 :route-variants 2}}})
                  serve/routing! (constantly nil) net/reset-stats! (constantly nil) net/stats (constantly {})
                  d2/step-day-traces (fn [_ _ seed & opts]
                                          (swap! seen conj [seed (apply hash-map opts)])
                                          {:traces []})]
      (is (= 200 (:status (serve/handler {:uri "/sim/trips" :query-string "area=stuttgart&stride=2"}))))
      (is (= [[37 {:stride 2 :route nil :p-keep 0.15 :route-variants 2}]] @seen)))))

(defn- two-firm-world [n workstat home-lon]
  {:persons {:n n :work (int-array n -1) :employed (int-array n 1) :workstat (int-array n workstat)
             :home-lon (double-array (repeat n home-lon)) :home-lat (double-array (repeat n (if (Double/isNaN home-lon) Double/NaN 48.77)))}
   :firms {:n 2 :lon (double-array [9.15 9.18]) :lat (double-array [48.77 48.78])
           :employees (int-array [300 3000]) :storefront (int-array [0 0]) :alive (int-array [1 1])}})

(deftest workplace-order-is-seeded
  (let [run (fn [seed] (vec (get-in (cw/assign-workplaces-grid! (two-firm-world 40 1 9.16) :seed seed) [:persons :work])))]
    (is (= (run 31) (run 31)))
    (is (not= (run 31) (run 32)))))

(deftest in-commuters-fill-firms-in-proportion-to-capacity
  ;; 400 in-commuters (no home) and two firms with 300 and 3,000 places: a
  ;; uniform draw among open firms sends half to each, capacity sends a tenth
  (let [out (cw/assign-workplaces-grid! (two-firm-world 400 4 Double/NaN) :seed 5)
        work (vec (get-in out [:persons :work]))
        small (count (filter zero? work))]
    (is (= 400 (count (filter #(>= % 0) work))) "everyone is placed")
    (is (< 15 small 65) (str small " of 400 at the small firm; about 36 expected"))))
