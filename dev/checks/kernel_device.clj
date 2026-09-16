;; Compile the day kernels for a device and compare them with the JVM on a
;; small synthetic world: identical visit and revenue arrays, identical counts.
;;   clojure -J--add-modules=jdk.incubator.vector -M -i dev/checks/kernel_device.clj   (CITY_DEVICE, default ze:0)
;; Needs a Level Zero or OpenCL device; CI does not run it.
(require '[raster.gpu.core :as gpu] '[city.sim.kernel :as kn])

(def device (keyword (or (System/getenv "CITY_DEVICE") "ze:0")))
(def rng (java.util.Random. 5))
(def nc 64) (def ncell 400) (def np 20000)
(def cell-xy (double-array (mapcat (fn [c] [(+ 9.1 (* 0.002 (mod c 20))) (+ 48.7 (* 0.0015 (quot c 20)))]) (range ncell))))
(def cand-xy (double-array (mapcat (fn [_] [(+ 9.1 (* 0.04 (.nextDouble rng))) (+ 48.7 (* 0.03 (.nextDouble rng)))]) (range nc))))
;; class vectors with closed venues (zeros) in every class
(def att3 (double-array (for [s (range 3) q (range nc)] (if (zero? (mod (+ q s) 7)) 0.0 (* 50.0 (Math/exp (* 3.0 (.nextDouble rng))))))))
(def params3 (double-array [0.8 2.2 400.0  1.1 1.4 900.0  0.0 2.0 600.0]))
(def totals3
  (let [a (double-array (* 3 ncell))]
    (dotimes [s 3]
      (let [att (double-array nc) _ (System/arraycopy att3 (* s nc) att 0 nc)
            cl (double-array (map #(aget ^doubles cell-xy (* 2 %)) (range ncell))) ca (double-array (map #(aget ^doubles cell-xy (inc (* 2 %))) (range ncell)))
            ql (double-array (map #(aget ^doubles cand-xy (* 2 %)) (range nc))) qa (double-array (map #(aget ^doubles cand-xy (inc (* 2 %))) (range nc)))
            tot (double-array ncell) p (double-array 3)]
        (System/arraycopy params3 (* s 3) p 0 3)
        (kn/cell-totals! cl ca ql qa att p tot ncell nc)
        (System/arraycopy tot 0 a (* s ncell) ncell)))
    a))
(def type-offsets (int-array [0 1 3])) (def type-cdf (double-array [1.0 0.4 1.0]))
(def diary-offsets (int-array [0 4 7 9]))
(def ep-loc (int-array [0 2 2 0  0 1 2  0 2])) (def ep-minute (int-array [420 600 660 720  420 540 720  420 1080]))
(def ptype (int-array (map #(mod % 2) (range np))))
(def home-cell (int-array (map #(if (zero? (mod % 9)) -1 (mod (* % 13) ncell)) (range np))))
(def work (int-array (map #(if (or (odd? %) (zero? (mod % 9))) (mod % nc) -1) (range np))))
(def work-cell (int-array (map #(mod (* % 31) ncell) (range nc))))
(def spend3 (int-array (for [s (range 3) i (range np)] (+ 500 (* 100 s) (mod i 11)))))
(def shares (double-array [0.65 0.85 1.0 0.1 0.0 0.3]))
(def dims (long-array [np nc 11 ncell]))

(defn jvm-day []
  (let [rev (int-array (* 3 nc 24)) vis (int-array (* 3 nc 24)) cnt (int-array 8)]
    (kn/spend-day! ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc ep-minute
                   cell-xy cand-xy att3 totals3 params3 shares spend3 rev vis cnt dims)
    {:revenue (vec rev) :visits (vec vis) :counts (vec cnt)}))

(def JVM (jvm-day))
(println :jvm-counts (:counts JVM))
(def SESS (gpu/make-session device))
(gpu/compile-phases! SESS {:spend-day #'kn/spend-day!} {:dtype :double})
(gpu/alloc! SESS {:ptype [:int np ptype] :home-cell [:int np home-cell] :work [:int np work] :work-cell [:int nc work-cell]
                  :type-offsets [:int 3 type-offsets] :type-cdf [:double 3 type-cdf] :diary-offsets [:int 4 diary-offsets]
                  :ep-loc [:int 9 ep-loc] :ep-minute [:int 9 ep-minute] :cell-xy [:double (* 2 ncell) cell-xy] :cand-xy [:double (* 2 nc) cand-xy]
                  :att3 [:double (* 3 nc) att3] :totals3 [:double (* 3 ncell) totals3] :params3 [:double 9 params3] :shares [:double 6 shares]
                  :spend3 [:int (* 3 np) spend3] :revenue3 [:int (* 3 nc 24) (int-array (* 3 nc 24))] :visits3 [:int (* 3 nc 24) (int-array (* 3 nc 24))]
                  :counts [:int 8 (int-array 8)] :dims [:long 4 dims]})
(def abi (let [ki (first (get (:kernels @SESS) :spend-day))] (or (:abi ki) (:kernel-abi ki) (get-in ki [:kernel :abi]))))
(def values {"n" np "nc" nc "seed" 11 "ncell" ncell})
(def scalars (vec (for [s abi :when (and (= :scalar (:kind s)) (not= :bound (:role s)))]
                    (let [v (get values (str (:name s)))]
                      (when (nil? v) (throw (ex-info "no value for scalar" {:slot s})))
                      {:type (:kernel-dtype s) :value (case (:kernel-dtype s) :int (int v) :long (long v) :float (float v) :double (double v) v)}))))
(gpu/invoke! SESS :spend-day {} scalars np)
(def DEV {:revenue (vec (gpu/download SESS :revenue3)) :visits (vec (gpu/download SESS :visits3)) :counts (vec (gpu/download SESS :counts))})
(gpu/close-session! SESS)
(println :device-counts (:counts DEV))
(println :KERNEL-DEVICE-CHECK
         (if (= JVM DEV) :identical
             {:counts-equal (= (:counts JVM) (:counts DEV))
              :visit-cells-differing (count (filter false? (map = (:visits JVM) (:visits DEV))))
              :revenue-cells-differing (count (filter false? (map = (:revenue JVM) (:revenue DEV))))}))
(shutdown-agents)
(System/exit 0)
