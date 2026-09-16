(ns city.sim.validate-load-test
  "city.sim.validate must compile from a cold JVM.

   It once did not: retail-centrality called retail-demand-share, which was
   defined later in the file, and the REPL only ever saw it work because an
   earlier reload had already interned the var. The suite never loaded the
   namespace, so HEAD stayed broken for a day. This test is the cold start."
  (:require [clojure.test :refer [deftest is]]))

(deftest validate-loads-cold
  (require 'city.sim.validate)
  (is (some? (resolve 'city.sim.validate/retail-demand-share)))
  (is (some? (resolve 'city.sim.validate/retail-centrality)))
  (is (some? (resolve 'city.sim.validate/retail-revenue)))
  (is (some? (resolve 'city.sim.validate/trip-rate))))
