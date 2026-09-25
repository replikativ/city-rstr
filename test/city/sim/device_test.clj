(ns city.sim.device-test
  "The likelihood's three kernel passes, run as JVM loops, against
   `candidates/reduce-dense` on a small world: same buckets, same total, same
   expected distance, for the β with exact reciprocals and for a general β.
   The device run of the same passes is `dev/checks/likelihood_device.clj`."
  (:require [clojure.test :refer [deftest is testing]]
            [city.sim.candidates :as cand]
            [city.sim.device :as dev]))

(defn- small-dense [n nc seed]
  (let [rng (java.util.Random. seed)]
    {:cand (int-array (range nc)) :n n :nc nc
     :dist (float-array (repeatedly (* n nc) #(float (* 15000.0 (.nextDouble rng)))))}))

(defn- close? [a b] (<= (Math/abs (- (double a) (double b))) (* 1e-12 (max 1.0 (Math/abs (double b))))))

(deftest three-passes-equal-reduce-dense
  (let [n 400 nc 90 rng (java.util.Random. 4)
        dense (small-dense n nc 7)
        ;; zeros: candidates outside the choice set, cells with nothing to allocate
        attract (double-array (map #(if (zero? (mod % 7)) 0.0 (* 100.0 (.nextDouble rng))) (range nc)))
        opts {:cell-value (double-array (map #(if (zero? (mod % 5)) 0.0 (* 2000.0 (.nextDouble rng))) (range n)))
              :cell-pop (long-array (map #(if (zero? (mod % 3)) 0 (inc (mod % 11))) (range n)))
              :bucket (int-array (map #(mod % 6) (range nc))) :n-buckets 6}]
    (doseq [spec [{:kernel :power :alpha 1.0 :beta 2.0 :d0-m 500.0}
                  {:kernel :power :alpha 0.8 :beta 1.6 :d0-m 700.0}]]
      (testing (pr-str spec)
        (let [a (cand/reduce-dense dense attract spec opts)
              b (dev/reduce-dense nil dense attract spec opts)]
          (is (every? true? (map close? (:bucket b) (:bucket a))))
          (is (close? (:allocated b) (:allocated a)))
          (is (close? (:expected-distance-m b) (:expected-distance-m a)))
          (is (= (:cells-served b) (:cells-served a))))))))

(deftest refuses-what-it-does-not-compute
  (let [dense (small-dense 4 3 1) opts {:cell-value (double-array 4) :cell-pop (long-array 4) :bucket (int-array 3) :n-buckets 1}]
    (is (thrown? clojure.lang.ExceptionInfo (dev/reduce-dense nil dense (double-array 3) {:kernel :exp :lambda-m 500.0} opts)))
    (is (thrown? clojure.lang.ExceptionInfo (dev/reduce-dense nil dense (double-array 3) {:kernel :power :beta 2.0 :d0-m 500.0 :max-m 3000.0} opts)))))
