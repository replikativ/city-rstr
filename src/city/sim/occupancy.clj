(ns city.sim.occupancy
  "Raster phase for a weekday. One work item represents a resident or a weighted
  group sharing the same itinerary, home-work intervention and treatment rank."
  (:refer-clojure :exclude [aget aset alength])
  (:require [raster.arrays :refer [aget aset alength]]
            [raster.core :refer [deftm]]
            [raster.par :as par]))

(deftm interval-changes!
  [ids :- (Array int), weights :- (Array int), offsets :- (Array int),
   starts :- (Array int), ends :- (Array int), shifts :- (Array int), ranks :- (Array int),
   changes :- (Array int), settings :- (Array int), n :- Long] :- Void
  (par/map-void! i n
    (let [g (int (aget ids i))
          k (int (unchecked-add-int (aget offsets g) (aget settings 1)))
          end (int (aget offsets (unchecked-add-int g 1)))]
      (when (< k end)
        (let [w (int (aget weights i))
              shift (int (if (<= (aget ranks g) (aget settings 0)) (aget shifts k) (int 0)))]
          (par/atomic-add! changes (unchecked-add-int (aget starts k) shift) w)
          (par/atomic-add! changes (unchecked-add-int (aget ends k) shift) (int (unchecked-subtract-int (int 0) w))))))))

(defn- device-call [k] (requiring-resolve (symbol "raster.gpu.core" (name k))))

(defn- device-results [device inputs levels steps]
  (let [s ((device-call :make-session) device)
        n (alength ^ints (:ids inputs))]
    (try
      ((device-call :compile-phases!) s {:events #'interval-changes!} {:dtype :float})
      ((device-call :alloc!) s (into {} (for [[k ^ints a] inputs] [k [:int (alength a) a]])))
      (mapv (fn [level]
              ((device-call :upload!) s :changes (:changes inputs))
              (dotimes [step steps]
                ((device-call :upload!) s :settings (int-array [level step]))
                ((device-call :invoke!) s :events {} [] n))
              ((device-call :download) s :changes))
            levels)
      (finally ((device-call :close-session!) s)))))

(defn- jvm-results [inputs levels steps]
  (let [n (alength ^ints (:ids inputs))]
    (mapv (fn [level]
            (let [changes (int-array (alength ^ints (:changes inputs)))]
              (dotimes [step steps]
                (interval-changes! (:ids inputs) (:weights inputs) (:offsets inputs)
                                    (:starts inputs) (:ends inputs) (:shifts inputs) (:ranks inputs)
                                    changes (int-array [level step]) n))
              changes))
          levels)))

(defn evaluate [inputs levels steps backend]
  (if (= (name backend) "jvm") (jvm-results inputs levels steps) (device-results (keyword backend) inputs levels steps)))

