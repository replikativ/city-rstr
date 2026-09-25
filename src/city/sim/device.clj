(ns city.sim.device
  "`candidates/reduce-dense` on a GPU, for the likelihood.

   `open-dense` compiles the three kernels of `city.sim.kernel` (normaliser,
   weighted distance, money per candidate), and uploads the distance table
   once. `reduce-dense` then takes the same arguments as
   `candidates/reduce-dense` and returns the same map: per call it uploads A^α,
   the kernel numbers and the cell values, runs the three passes, and does
   the per-bucket sums on the host.

   The device reads the same float32 distances, transposed to candidate-major
   and widened to double on upload (lossless), and A^α from `candidates/candidate-weights`, so the only
   differences from the CPU are summation order and, for β outside {1, 2, 3},
   the device's `pow`: about 1e-15 relative. There are no atomics, so a result
   does not depend on scheduling.

   Only the power kernel without a reach bound runs here; anything else
   throws, and the caller uses `candidates/reduce-dense`. A handle serialises
   its calls, so chains running in parallel can share it. A lost device (a
   suspend and resume resets the GPU and every context on it) is reopened
   once and the evaluation repeated; `:recoveries` counts how often.

   The distances live on the device as double, 1.0 GB on Stuttgart: raster
   compiles a double kernel with every floating array in double, so a float32
   buffer cannot be bound to it."
  (:require [city.sim.candidates :as cand]
            [city.sim.day :as d2]
            [city.sim.kernel :as kn]))

(def ^:private upload-chunk (* 4 1024 1024))

(def ^:private blocks
  "Cell blocks of the per-candidate pass (see `kernel/dense-candidate-mass!`)."
  64)

(defn- gpu [sym] (requiring-resolve (symbol "raster.gpu.core" (name sym))))

(defn- scalar-values
  "Scalar arguments in ABI order; the compiler hoists the `let` over `params`
   into scalars, so `values` names those too."
  [sess k values]
  (let [abi (:abi (first (get (:kernels @sess) k)))]
    (vec (for [s abi :when (and (= :scalar (:kind s)) (not= :bound (:role s)))]
           (let [v (get values (str (:name s)))]
             (when (nil? v) (throw (ex-info "no value for kernel scalar" {:kernel k :slot s})))
             {:type (:kernel-dtype s)
              :value (case (:kernel-dtype s) :int (int v) :long (long v) :float (float v) :double (double v))})))))

(defn- open-session
  "A GPU session with the three kernels compiled and `dense`'s distances
   resident, candidate-major and widened to double."
  [{:keys [^floats dist n nc]} device]
  (let [n (long n) nc (long nc) total (* n nc)
        sess ((gpu 'make-session) device)]
    (try
      ((gpu 'compile-phases!) sess {:z #'kn/dense-cell-totals! :d #'kn/dense-cell-distance! :m #'kn/dense-candidate-mass!}
                              {:dtype :double})
      ((gpu 'alloc!) sess {:dist-t [:double total nil] :aw [:double nc nil] :params [:double 3 nil]
                           :cell-value [:double n nil] :z [:double n nil] :dz [:double n nil] :mass [:double (* nc blocks) nil]})
      ;; transpose to candidate-major and widen, a few candidates at a time, so
      ;; the heap never holds a second full copy
      (let [rows (max 1 (quot upload-chunk n))]
        (loop [q0 0]
          (when (< q0 nc)
            (let [k (min rows (- nc q0)) buf (double-array (* k n))]
              (dotimes [dq k]
                (let [q (+ q0 dq) o (* dq n)]
                  (dotimes [c n] (aset buf (+ o c) (double (aget dist (+ (* c nc) q)))))))
              ((gpu 'upload-range!) sess :dist-t buf {:src-element 0 :dst-element (* q0 n) :elements (* k n)})
              (recur (+ q0 k))))))
      sess
      (catch Throwable t ((gpu 'close-session!) sess) (throw t)))))

(defn open-dense
  "A device handle for `dense` (from `candidates/build-dense`): kernels
   compiled, distances resident. Close it with `close!`."
  [dense & {:keys [device] :or {device :ze:0}}]
  {:sess (atom (open-session dense device)) :dense dense :device device :lock (Object.)
   :recoveries (atom 0)})

(defn close! [{:keys [sess]}] ((gpu 'close-session!) @sess))

(defn- device-lost?
  "A Level Zero or OpenCL failure the device does not come back from without a
   new session: what a suspend and resume, or a driver reset, leaves behind."
  [^Throwable t]
  (some #(re-find #"Level Zero error|OpenCL error|CL_OUT_OF_RESOURCES|DEVICE_LOST" (str (.getMessage ^Throwable %)))
        (take-while some? (iterate #(.getCause ^Throwable %) t))))

(defn- run-passes
  "Upload the θ-dependent inputs, run the three kernels, download Z, D and the
   per-block money."
  [sess n nc aw params cell-value]
  (let [values {"n" n "nc" nc "blocks" blocks "inv-d0" (aget ^doubles params 0) "nbeta" (aget ^doubles params 1) "bmode" (aget ^doubles params 2)}]
    ((gpu 'upload!) sess :aw aw)
    ((gpu 'upload!) sess :params params)
    ((gpu 'upload!) sess :cell-value cell-value)
    ((gpu 'invoke!) sess :z {} (scalar-values sess :z values) n)
    ((gpu 'invoke!) sess :d {} (scalar-values sess :d values) n)
    ((gpu 'invoke!) sess :m {} (scalar-values sess :m values) (* nc blocks))
    [((gpu 'download) sess :z) ((gpu 'download) sess :dz) ((gpu 'download) sess :mass)]))

(defn reduce-dense
  "`candidates/reduce-dense` computed by the three kernels: on `handle`'s
   device, or, with a nil handle, as plain JVM loops (how the tests check the
   passes against `candidates/reduce-dense`). Same arguments, same result."
  [handle {:keys [^ints cand ^floats dist n nc]} ^doubles attract spec
   {:keys [^doubles cell-value ^ints bucket n-buckets ^longs cell-pop]}]
  (let [{:keys [alpha beta d0-m kernel max-m]} (merge (:retail d2/default-venue-kernels) spec)
        _ (when-not (and (= :power kernel) (not (and max-m (pos? (double max-m)))))
            (throw (ex-info "the device reduce runs the power kernel without a reach bound"
                            {:kernel kernel :max-m max-m})))
        n (long n) nc (long nc) beta (double beta)
        params (double-array [(/ 1.0 (double d0-m)) (- beta)
                              (cond (= 1.0 beta) 1.0 (= 2.0 beta) 2.0 (= 3.0 beta) 3.0 :else 0.0)])
        aw (cand/candidate-weights cand attract alpha)
        [^doubles z ^doubles dz ^doubles mass]
        (if-let [{:keys [sess lock]} handle]
          (locking lock
            (try (run-passes @sess n nc aw params cell-value)
                 (catch Throwable t
                   (when-not (device-lost? t) (throw t))
                   ;; one new session and one retry; the evaluation itself is
                   ;; deterministic, so repeating it changes nothing
                   (swap! (:recoveries handle) inc)
                   (binding [*out* *err*] (println "city.sim.device: device lost, reopening:" (.getMessage t)))
                   (try ((gpu 'close-session!) @sess) (catch Throwable _))
                   (reset! sess (open-session (:dense handle) (:device handle)))
                   (run-passes @sess n nc aw params cell-value))))
          (let [z (double-array n) dz (double-array n) mass (double-array (* nc blocks))
                dist-t (let [t (float-array (* n nc))]
                         (dotimes [c n] (dotimes [q nc] (aset t (+ (* q n) c) (aget dist (+ (* c nc) q)))))
                         t)]
            (kn/dense-cell-totals! dist-t aw params z n nc)
            (kn/dense-cell-distance! dist-t aw params dz n nc)
            (kn/dense-candidate-mass! dist-t aw params cell-value z mass n nc blocks)
            [z dz mass]))
        out (double-array n-buckets)]
    (dotimes [q nc]
      (let [b (aget bucket q)
            m (loop [k 0 m 0.0] (if (= k blocks) m (recur (inc k) (+ m (aget mass (+ (* q blocks) k))))))]
        (aset out b (+ (aget out b) m))))
    ;; the cells `reduce-dense` visits: something to allocate or people to
    ;; count, and a candidate within reach
    (let [[allocated num den]
          (loop [c 0 al 0.0 num 0.0 den 0.0]
            (if (= c n) [al num den]
                (let [zc (aget z c) v (aget cell-value c) p (double (aget cell-pop c))]
                  (if (and (pos? zc) (or (pos? v) (pos? p)))
                    (recur (inc c) (+ al v)
                           (if (pos? p) (+ num (* p (/ (aget dz c) zc))) num)
                           (if (pos? p) (+ den p) den))
                    (recur (inc c) al num den)))))]
      {:bucket out
       :allocated allocated
       :expected-distance-m (when (pos? den) (/ num den))
       :cells-served (count (filter #(pos? (aget cell-value %)) (range n)))})))
