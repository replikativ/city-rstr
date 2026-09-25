;; Compile the store decisions (store-choices!) for a device and compare them
;; with the JVM on a small synthetic world: identical diaries and choices, and
;; so an identical money day.
;;   clojure -J--add-modules=jdk.incubator.vector -M -i dev/checks/kernel_device.clj   (CITY_DEVICE, default ze:0)
;; Needs a Level Zero or OpenCL device; CI does not run it.
(require '[raster.gpu.core :as gpu] '[city.sim.kernel :as kn] '[city.econ.day :as eday])

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
(def max-s 2)
(def store-rank (eday/store-ranks {:diary-offsets diary-offsets :ep-loc ep-loc}))
(def dims (long-array [np nc 11 ncell max-s]))

(defn device-run
  "Compile `kernel` alone, bind `bufs`, launch over `np` persons and download
   the `out` buffers. Scalars follow the ABI: the compiler hoists the `let`
   that reads `params`/`dims` into scalar arguments, so `values` names them."
  [kernel bufs values out]
  (let [sess (gpu/make-session device)]
    (try
      (gpu/compile-phases! sess {:k kernel} {:dtype :double})
      (gpu/alloc! sess bufs)
      (let [ki (first (get (:kernels @sess) :k))
            abi (or (:abi ki) (:kernel-abi ki) (get-in ki [:kernel :abi]))
            scalars (vec (for [s abi :when (and (= :scalar (:kind s)) (not= :bound (:role s)))]
                           (let [v (get values (str (:name s)))]
                             (when (nil? v) (throw (ex-info "no value for scalar" {:slot s})))
                             {:type (:kernel-dtype s) :value (case (:kernel-dtype s) :int (int v) :long (long v) :float (float v) :double (double v) v)})))]
        (gpu/invoke! sess :k {} scalars np)
        (into {} (for [[k b] out] [k (vec (gpu/download sess b))])))
      (finally (gpu/close-session! sess)))))

(defn money-counts [{:keys [diary choice]}]
  (:counts (eday/money-from-choices {:diary (int-array diary) :choice (int-array choice) :max-s max-s}
                                    {:diary-offsets diary-offsets :ep-loc ep-loc :ep-minute ep-minute} spend3 np nc)))

(defn report [label jvm dev]
  (println label :jvm-money-counts (money-counts jvm) :device-money-counts (money-counts dev))
  (println label (if (= jvm dev) :identical
                     (into {} (for [k (keys jvm)] [k (count (filter false? (map = (get jvm k) (get dev k))))]))))
  (= jvm dev))

(def jvm
  (let [diary (int-array np -1) choice (int-array (* np max-s) -9)]
    (kn/store-choices! ptype home-cell work work-cell type-offsets type-cdf diary-offsets ep-loc
                       cell-xy cand-xy att3 totals3 params3 shares store-rank diary choice dims)
    {:diary (vec diary) :choice (vec choice)}))

(def ok
  (report :store-choices jvm
          (device-run #'kn/store-choices!
                      {:ptype [:int np ptype] :home-cell [:int np home-cell] :work [:int np work] :work-cell [:int nc work-cell]
                       :type-offsets [:int 3 type-offsets] :type-cdf [:double 3 type-cdf] :diary-offsets [:int 4 diary-offsets]
                       :ep-loc [:int 9 ep-loc] :cell-xy [:double (* 2 ncell) cell-xy] :cand-xy [:double (* 2 nc) cand-xy]
                       :att3 [:double (* 3 nc) att3] :totals3 [:double (* 3 ncell) totals3] :params3 [:double 9 params3] :shares [:double 6 shares]
                       :store-rank [:int 9 store-rank] :diary [:int np (int-array np -1)] :choice [:int (* np max-s) (int-array (* np max-s) -9)] :dims [:long 5 dims]}
                      {"n" np "nc" nc "seed" 11 "ncell" ncell "max-s" max-s}
                      {:diary :diary :choice :choice})))

(println :KERNEL-DEVICE-CHECK (if ok :identical :differs))
(shutdown-agents)
(System/exit (if ok 0 1))
