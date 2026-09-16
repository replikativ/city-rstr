(ns city.sim.run-test
  "The run config and the kernel table agree: the default config resolves to
   the default kernels, and the store and restaurant kernels are the ones the
   published Stuttgart run records."
  (:require [clojure.test :refer [deftest is]]
            [city.sim.day :as d2]
            [city.sim.run :as run]))

(deftest the-default-config-resolves-to-the-default-kernels
  (is (= d2/default-venue-kernels (d2/venue-kernels (run/config {})))))

(deftest store-and-restaurant-kernels-are-the-published-ones
  (let [k (d2/venue-kernels (run/config {}))
        published {:kernel :power :alpha 1.0 :d0-m 500.0 :beta 1.6 :lambda-m 400.0 :k 64}]
    (is (= published (:retail k)))
    (is (= published (:food k)))))

(deftest an-override-moves-store-and-restaurant-only
  (let [k (d2/venue-kernels (run/config {:venue-beta 2.0}))]
    (is (= 2.0 (get-in k [:retail :beta]) (get-in k [:food :beta])))
    (is (= (:clinic d2/default-venue-kernels) (:clinic k)))))
