(ns city.sim.cityworld
  "The Stuttgart world as columns (`build-stuttgart`). The synthetic persons
   file is streamed straight into arrays, never held as maps; firms come from
   the synthetic register. The labour market follows the published commuting
   shares: residents who work in the city, out-commuters, and in-commuters
   appended with no home. Workplaces are drawn by a gravity kernel on a 300 m
   grid (`assign-workplaces-grid!`); in- and out-commuters are then placed at
   the city boundary on the side they travel (`place-externals!`,
   `place-out-commuters!`).

   Also the area side of a published run: Stadtteil polygons rasterised onto
   the grid (`area-raster`) and the per-area aggregates and OD matrix the
   explorer draws (`area-aggregates`)."
  (:require [clojure.edn :as edn]
            [clojure.java.io :as io]
            [clojure.data.json :as json]
            [city.sim.world :as w]
            [city.sim.day :as d2]))

;; ---- city-scale workplace assignment (grid gravity, not O(persons × firms)) ------------------

(defn assign-workplaces-grid!
  "Each resident worker (employed, not :outside) draws a workplace from a
   per-cell CDF over the top-K firms with capacity (capacity × exp(−d/λ)),
   built once on a 300 m grid; a full firm is retried up to 4 times, then a
   firm is drawn in proportion to its remaining capacity. External
   in-commuters (NaN home) draw in proportion to remaining capacity only."
  [world & {:keys [lambda-m cell-m k seed] :or {lambda-m 6000.0 cell-m 300.0 k 48 seed 1}}]
  (let [{:keys [persons firms]} world
        ^ints work (:work persons) ^ints emp (:employed persons)
        ^ints workstat (or (:workstat persons)
                           ;; older worlds carry :outside instead: 0 = works here
                           (let [^ints o (or (:outside persons) (int-array (:n persons)))
                                 a (int-array (:n persons))]
                             (dotimes [i (:n persons)] (aset a i (if (= 1 (aget o i)) 2 1))) a))
        ^doubles hlon (:home-lon persons) ^doubles hlat (:home-lat persons)
        ^ints femp (:employees firms) ^ints sf (:storefront firms) nf (:n firms)
        cap (int-array (map (fn [j] (max (aget femp j) (if (= 1 (aget sf j)) 3 0))) (range nf)))
        has-cap (int-array (map #(if (pos? (aget cap %)) 1 0) (range nf)))
        grid (d2/grid-spec world :cell-m cell-m)
        attract (double-array (map #(double (aget cap %)) (range nf)))
        table (d2/gravity-table grid firms has-cap :k k :lambda-m lambda-m :attract attract)
        rng (java.util.Random. seed)
        ;; remaining capacity in a Fenwick tree, so the fallback draws a firm in
        ;; proportion to the places it has left, not uniformly among open firms
        fen (long-array (inc nf))
        fen-add! (fn [j ^long delta] (loop [x (inc j)] (when (<= x nf) (aset fen x (+ (aget fen x) delta)) (recur (+ x (bit-and x (- x)))))))
        _ (dotimes [j nf] (fen-add! j (aget cap j)))
        fen-total (fn [] (loop [x nf acc 0] (if (pos? x) (recur (- x (bit-and x (- x))) (+ acc (aget fen x))) acc)))
        top-bit (Long/highestOneBit (max 1 nf))
        take! (fn [j] (aset cap j (dec (aget cap j))) (fen-add! j -1) j)
        random-open (fn []
                      (let [total (long (fen-total))]
                        (when (pos? total)
                          ;; the first firm whose cumulative remaining capacity exceeds r
                          (let [r (long (* total (.nextDouble rng)))]
                            (loop [pos 0 rem r step top-bit]
                              (if (zero? step) pos
                                  (let [nxt (+ pos step)]
                                    (if (and (<= nxt nf) (<= (aget fen nxt) rem))
                                      (recur nxt (- rem (aget fen nxt)) (unsigned-bit-shift-right step 1))
                                      (recur pos rem (unsigned-bit-shift-right step 1))))))))))
        assigned (long-array 2)]
    (dotimes [i (:n persons)]
      ;; only the two roles that hold a *city* job draw a workplace: a resident
      ;; who works in the city (1) and an in-commuter (4)
      (when (and (= 1 (aget emp i)) (or (= 1 (aget workstat i)) (= 4 (aget workstat i))))
        (let [lon (aget hlon i) lat (aget hlat i)
              j (if (Double/isNaN lon)
                  (random-open)
                  (let [cell (d2/cell-of grid lon lat)]
                    (loop [t 0]
                      (if (= t 4) (random-open)
                          (let [j (#'d2/pick-from-cdf table cell (d2/uniform seed i (+ 300000 t)))]
                            (if (pos? (aget cap j)) j (recur (inc t))))))))]
          (when j (aset work i (int (take! j))) (aset assigned (if (Double/isNaN lon) 1 0) (inc (aget assigned (if (Double/isNaN lon) 1 0))))))))
    (assoc world :workplaces {:assigned-residents (aget assigned 0) :assigned-externals (aget assigned 1)
                              :unfilled-capacity (reduce + (map #(aget cap %) (range nf)))})))

;; ---- persons: stream file → columns ---------------------------------------------------------

(defn count-lines ^long [path] (with-open [r (io/reader path)] (count (line-seq r))))

(defn persons-columns
  "Read a synthetic persons file (one EDN map per line, in the PUMF key
   vocabulary `city.synth.stuttgart` writes) into columns, with homes jittered
   uniformly around the centroid of the person's zone (`:da`, a Zensus 100 m
   cell). Returns the :persons block, with :la (the Stadtteil) per person."
  [path da-centroids & {:keys [seed sample jitter-deg] :or {seed 7 sample 1.0 jitter-deg 0.002}}]
  (let [n0 (count-lines path)
        rng (java.util.Random. seed)
        keep? (if (< sample 1.0) (fn [] (< (.nextDouble rng) sample)) (constantly true))
        cap n0
        da (make-array String cap) la (make-array String cap)
        hh (int-array cap) age (int-array cap) sex (int-array cap) labour (int-array cap)
        naics (int-array cap) noc (int-array cap) mode (int-array cap) attsch (int-array cap)
        employed (int-array cap) hlon (double-array cap) hlat (double-array cap)
        ;; the home is uniform in a box the size of the zone the row names (a
        ;; Zensus 100 m cell is 0.0013°)
        jitter (fn [] (* (double jitter-deg) (- (.nextDouble rng) 0.5)))
        i (long-array 1)]
    (with-open [r (io/reader path)]
      (doseq [line (line-seq r) :when (keep?)]
        (let [p (edn/read-string line) k (aget i 0)
              [lon lat] (or (da-centroids (:da p)) [Double/NaN Double/NaN])
              l (long (or (:LFACT p) 0))]
          (aset da k (:da p)) (aset la k (str (:la p)))
          (aset hh k (int (or (:hh p) -1))) (aset age k (int (or (:AGEGRP p) 0))) (aset sex k (int (or (:GENDER p) 0)))
          (aset labour k (int l)) (aset naics k (int (or (:NAICS p) 0))) (aset noc k (int (or (:NOC21 p) 0)))
          (aset mode k (int (or (:MODE p) 0))) (aset attsch k (int (or (:ATTSCH p) 0)))
          (aset employed k (if (<= 1 l 2) 1 0))
          (aset hlon k (+ lon (jitter))) (aset hlat k (+ lat (jitter)))
          (aset i 0 (inc k)))))
    (let [n (aget i 0) trim (fn [arr] (if (= n cap) arr (let [a (java.lang.reflect.Array/newInstance (.getComponentType (class arr)) n)] (System/arraycopy arr 0 a 0 n) a)))]
      {:n n :da (trim da) :la (trim la) :hh (trim hh) :age (trim age) :sex (trim sex) :labour (trim labour)
       :naics (trim naics) :noc (trim noc) :mode (trim mode) :attsch (trim attsch) :employed (trim employed)
       :home-lon (trim hlon) :home-lat (trim hlat) :work (int-array n -1)})))

;; ---- firms: merged clusters per area, cached ------------------------------------------------

(def non-business-place-categories
  "Overture place categories that are not an establishment and must not enter
   the firm register. They arrived with the places layer and 41 of them were
   given synthesized payroll: 969 rows carrying 6,342 phantom jobs between
   lakes, mountains, parks, playgrounds, parking and cash machines."
  #{"lake" "mountain" "park" "playground" "parking" "atms" "ev_charging_station"
    "landmark_and_historical_building" "forest" "river" "beach" "garden"
    "hiking_trail" "picnic_area" "scenic_point" "bus_stop" "train_station_platform"})

(defn business-place?
  "Is this row an establishment at all? Keeps anything with a sector letter (the
   Stuttgart synthesis assigns WZ sections) and rejects the named map features."
  [{:keys [place-category licence-type storefront-category]}]
  (not (and place-category
            (nil? licence-type) (nil? storefront-category)
            (non-business-place-categories place-category))))

(defn file-firms
  "Firm rows from **one** JSON file rather than one per area — the shape
   `city.synth.stuttgart-firms/build!` writes, each row carrying its own
   `:area`. The field names are those of the shared firm schema: for Stuttgart
   `:licence-type` holds the WZ section and `:storefront-category` is empty."
  [path]
  (vec (for [{:keys [eids name lon lat licence-type employees storefront-category
                     place-category kinds website area emp-observed anchor-id]}
             (:firms (json/read-str (slurp path) :key-fn keyword))
             :when (and lon lat (business-place? {:place-category place-category
                                                  :licence-type licence-type
                                                  :storefront-category storefront-category}))]
         {:eid (first eids) :eids eids :name name :lon lon :lat lat
          :area area :area-eid nil
          :type (or licence-type storefront-category place-category)
          ;; The *fine* category, kept beside :type. :type collapses three
          ;; vocabularies and the register's section name wins, so for
          ;; Stuttgart all 3,637 retail firms read "G Handel; Instandhaltung
          ;; und Reparatur von Kraftfahrzeugen" and the assortment is gone.
          ;; city.synth.segments needs the assortment.
          :category place-category
          :employees (long (or employees 0))
          ;; Stuttgart has no employment *register* per establishment, so by
          ;; default every count here is an allocation of a sector total rather
          ;; than a measurement. The exception is a firm matched to a named
          ;; employer with a published headcount by `city.synth.anchors`, which
          ;; sets `:emp-observed` on the row — those are measurements and are
          ;; allowed to outrank the synthesized ones.
          :emp-observed? (= 1 emp-observed)
          :anchor-id anchor-id
          :food? (boolean (or (w/food-types licence-type) (= "Food & Beverage" storefront-category)
                              (and place-category (re-find w/food-place-re place-category))))
          :storefront? (boolean (some #{"storefront"} kinds))
          :retail? (boolean (or (w/retail-storefront storefront-category)
                                (and place-category (re-find w/retail-place-re place-category))
                                (and licence-type (re-find w/retail-licence-re licence-type))))
          :website website :kinds kinds})))

;; ---- world -----------------------------------------------------------------------------------

(defn firm-columns [firms]
  (let [n (count firms)]
    {:n n
     :eid (long-array (map :eid firms))
     :name (into-array String (map #(str (:name %)) firms))
     :type (into-array String (map #(str (:type %)) firms))
     ;; the assortment category, when the source had one (see file-firms)
     :category (into-array String (map #(str (:category %)) firms))
     :lon (double-array (map :lon firms)) :lat (double-array (map :lat firms))
     :employees (int-array (map :employees firms))
     ;; 1 when the employee count is a *measurement* (a licence declares it),
     ;; 0 when it was synthesized. The destination kernel must not read a
     ;; synthesized headcount as a shop's size: Stuttgart's synthesis put 2,889
     ;; employees on a convenience store and 1 on the median Königstraße shop,
     ;; and the street-density proxy that exists for exactly this case never
     ;; ran because a number was always present.
     :emp-observed (int-array (map #(if (:emp-observed? %) 1 0) firms))
     :food (int-array (map #(if (:food? %) 1 0) firms))
     :retail (int-array (map #(if (:retail? %) 1 0) firms))
     :storefront (int-array (map #(if (:storefront? %) 1 0) firms))
     :alive (int-array n 1)
     ;; the local area the firm was pulled for: the aggregate view's segment key
     :la (into-array String (map #(str (:area %)) firms))}))

(def workstat-names
  "What an employed person's working day looks like, from the commuting
   statistics: works in the city, commutes out, has no fixed workplace, or
   commutes in. The split follows the published shares, so city firms are
   filled by the residents who work in the city plus the in-commuters the same
   statistics count, and not by every employed resident. Germany's statistics
   have no 'no fixed workplace' category, so role 3 is empty for Stuttgart."
  {0 :not-employed 1 :works-in-city 2 :commutes-out 3 :no-fixed-workplace 4 :in-commuter})

(defn labour-roles!
  "Give every employed resident one of the three resident roles and append the
   published count of in-commuters as persons with no home.
   Writes :workstat (see `workstat-names`) and keeps :outside as the
   'has no city workplace' flag the older modules read."
  [world {:keys [residents-with-workplace share-work-in-city jobs-in-city]} & {:keys [sample seed] :or {sample 1.0 seed 11}}]
  (let [{:keys [persons]} world
        n (:n persons) ^ints emp (:employed persons)
        n-emp (areduce emp i s 0 (+ s (aget emp i)))
        stay (* (double share-work-in-city) (double residents-with-workplace))
        out (- (double residents-with-workplace) stay)
        p-stay (min 1.0 (/ (* sample stay) (max 1.0 (double n-emp))))
        p-out (min (- 1.0 p-stay) (/ (* sample out) (max 1.0 (double n-emp))))
        n-ext (max 0 (long (Math/round (* sample (- (double jobs-in-city) stay)))))
        rng (java.util.Random. seed)
        workstat (int-array (+ n n-ext))
        _ (dotimes [i n]
            (when (= 1 (aget emp i))
              (let [u (.nextDouble rng)]
                (aset workstat i (int (cond (< u p-stay) 1 (< u (+ p-stay p-out)) 2 :else 3))))))
        _ (dotimes [k n-ext] (aset workstat (+ n k) (int 4)))
        grow (fn [arr fill]
               (let [m (+ n n-ext)]
                 (cond (instance? (Class/forName "[I") arr) (let [a (int-array m fill)] (System/arraycopy arr 0 a 0 n) a)
                       (instance? (Class/forName "[D") arr) (let [a (double-array m fill)] (System/arraycopy arr 0 a 0 n) a)
                       :else (let [a (make-array String m)] (System/arraycopy arr 0 a 0 n)
                                   (dotimes [k n-ext] (aset a (+ n k) "external")) a))))
        persons' (-> persons
                     (assoc :n (+ n n-ext))
                     (update :da grow nil) (update :la grow nil) (update :hh grow -1)
                     (update :age grow 0) (update :sex grow 0) (update :labour grow 1)
                     (update :naics grow 0) (update :noc grow 0)
                     (update :mode grow 0) (update :attsch grow 0) (update :employed grow 1)
                     (update :home-lon grow Double/NaN) (update :home-lat grow Double/NaN)
                     (update :work grow -1)
                     (assoc :workstat workstat)
                     (assoc :outside (let [a (int-array (+ n n-ext))]
                                       (dotimes [i (+ n n-ext)] (aset a i (if (#{2 3} (aget workstat i)) 1 0))) a))
                     (assoc :external (let [a (int-array (+ n n-ext))] (dotimes [k n-ext] (aset a (+ n k) 1)) a)))]
    ;; externals are working-age adults; the diary tables need an age and a sex
    (dotimes [k n-ext]
      (aset ^ints (:age persons') (+ n k) (int (+ 5 (.nextInt rng 8))))
      (aset ^ints (:sex persons') (+ n k) (int (inc (.nextInt rng 2)))))
    (assoc world :persons persons'
           :commute {:employed-residents n-emp
                     :works-in-city (count (filter #(= 1 (aget workstat %)) (range n)))
                     :commutes-out (count (filter #(= 2 (aget workstat %)) (range n)))
                     :no-fixed-workplace (count (filter #(= 3 (aget workstat %)) (range n)))
                     :external-in-commuters n-ext
                     :p-works-in-city (/ (Math/round (* 1000.0 p-stay)) 1000.0)
                     :p-commutes-out (/ (Math/round (* 1000.0 p-out)) 1000.0)})))

(defn origins
  "In-commuter origins as [{:name :lon :lat :flow}], from a JSONL file written
   by the geocoding step. Returns nil when the file is absent, which leaves
   in-commuters where they were."
  [path]
  (when (.exists (io/file path))
    (with-open [r (io/reader path)]
      (vec (for [l (line-seq r) :let [m (json/read-str l :key-fn keyword)]] m)))))

(defn place-externals!
  "Give every external in-commuter a home **at the edge of the city, on the
   side they come from**, so that they actually commute in.

   Without this they would begin the simulated day already at their desk:
   326,153 people in Stuttgart who generate no commute, contribute nothing to
   the morning peak, and cross none of the counted sites.

   The entry point is their origin municipality's centroid **clamped into the
   city's own bounding box**, jittered. The model is explicit about what it
   claims: we simulate the *in-city* portion of an in-commute, entered from the
   correct side: a person from Ludwigsburg enters on the northern boundary,
   one from Esslingen on the eastern one. Nothing is claimed about the journey before that point, which happens outside every
   graph, boundary and counter this model has.

   Call this **after** `assign-workplaces-grid!`: an in-commuter's workplace is
   drawn from capacity alone (the census does not say where in the city they
   work), and giving them a boundary home first would pull all of them onto the
   edge by the gravity kernel.

   `origins` is a seq of `{:name :lon :lat :flow}`; draws are proportional to
   :flow. The boundary point becomes the person's home, so `day/prepare` gives
   them a home cell there and their day starts and ends at it."
  [world origins & {:keys [seed jitter-deg] :or {seed 13 jitter-deg 0.004}}]
  (if-not (seq origins)
    world
    (let [ps (:persons world) n (:n ps)
          ^ints ext (or (:external ps) (int-array n))
          ^doubles hlon (:home-lon ps) ^doubles hlat (:home-lat ps)
          ^objects da (:da ps)
          fs (:firms world) ^doubles flon (:lon fs) ^doubles flat (:lat fs) nf (:n fs)
          ;; the city's own extent: resident homes and firms, never the externals
          bb (let [w (double-array 1 Double/POSITIVE_INFINITY) e (double-array 1 Double/NEGATIVE_INFINITY)
                   s (double-array 1 Double/POSITIVE_INFINITY) nn (double-array 1 Double/NEGATIVE_INFINITY)]
               (dotimes [i n]
                 (when (and (zero? (aget ext i)) (not (Double/isNaN (aget hlon i))))
                   (aset w 0 (min (aget w 0) (aget hlon i))) (aset e 0 (max (aget e 0) (aget hlon i)))
                   (aset s 0 (min (aget s 0) (aget hlat i))) (aset nn 0 (max (aget nn 0) (aget hlat i)))))
               (dotimes [j nf]
                 (aset w 0 (min (aget w 0) (aget flon j))) (aset e 0 (max (aget e 0) (aget flon j)))
                 (aset s 0 (min (aget s 0) (aget flat j))) (aset nn 0 (max (aget nn 0) (aget flat j))))
               {:west (aget w 0) :east (aget e 0) :south (aget s 0) :north (aget nn 0)})
          os (vec origins)
          tot (double (reduce + (map #(double (or (:flow %) 1)) os)))
          cdf (double-array (count os))
          _ (loop [k 0 acc 0.0]
              (when (< k (count os))
                (let [acc (+ acc (/ (double (or (:flow (os k)) 1)) tot))]
                  (aset cdf k acc) (recur (inc k) acc))))
          pick (fn [^double u] (loop [k 0] (if (or (= k (dec (count os))) (< u (aget cdf k))) k (recur (inc k)))))
          clamp (fn ^double [^double x ^double lo ^double hi] (max lo (min hi x)))
          rng (java.util.Random. seed)
          placed (long-array (count os))]
      (dotimes [i n]
        (when (= 1 (aget ext i))
          (let [k (pick (.nextDouble rng))
                o (os k)
                jit (fn [] (* (double jitter-deg) (- (.nextDouble rng) 0.5)))]
            (aset hlon i (+ (clamp (double (:lon o)) (:west bb) (:east bb)) (jit)))
            (aset hlat i (+ (clamp (double (:lat o)) (:south bb) (:north bb)) (jit)))
            (aset da i (str (:name o)))
            (aset placed k (inc (aget placed k))))))
      (assoc world :entry-points
             {:bbox bb :origins (count os)
              :placed (vec (for [k (range (count os))] {:name (:name (os k)) :n (aget placed k)}))
              :total (reduce + (seq placed))}))))

(def stuttgart-out-destinations
  "Where Stuttgart's out-commuters go, from `data/derived/stuttgart_commuter_flows.json`
   (Monatsheft 6/2021, 2020, SvB basis, verified to sum to the published 95,896).
   Kreis centroids are given to about a kilometre, which is all this needs: what
   the model claims is the *side of the city* a person leaves by, not where they
   end up. Everything past the boundary happens outside every graph and counter
   we have, exactly as for an in-commuter's inbound journey."
  [{:name "Esslingen"        :lon 9.40 :lat 48.70 :flow 20783}
   {:name "Ludwigsburg"      :lon 9.15 :lat 48.95 :flow 19109}
   {:name "Böblingen"        :lon 8.95 :lat 48.65 :flow 15535}
   {:name "Rems-Murr-Kreis"  :lon 9.45 :lat 48.85 :flow 11123}
   {:name "Reutlingen"       :lon 9.25 :lat 48.48 :flow 1962}
   {:name "Heilbronn"        :lon 9.20 :lat 49.15 :flow 1366}
   {:name "Göppingen"        :lon 9.70 :lat 48.68 :flow 1223}
   ;; "Übrige" is 21,085 of 95,896 and is genuinely dispersed; it is placed at
   ;; the flow-weighted centre of the named destinations rather than dropped,
   ;; since dropping it would leave a fifth of out-commuters immobile again.
   {:name "Übrige"           :lon 9.25 :lat 48.78 :flow 21085}])

(defn place-out-commuters!
  "The mirror of `place-externals!`, and it exists for the same reason.

   An **in**-commuter is given a home at the city edge on the side they come
   from, so they commute in. An **out**-commuter was identified and then given
   nothing: no workplace, therefore no work leg, therefore a person who sits at
   home all day. Measured on 2026-09-12 that is 122,195 people — 23 % of
   eligible residents — at a mobile share of 0.597, which is the whole of the
   resident trip-generation gap (residents 0.737 against a 0.834 diary pool).

   They are given an **exit point**: a destination centroid clamped into the
   city's bounding box, so the leg runs from home to the boundary on the correct
   side. `:exit-lon` / `:exit-lat` are written on the persons block rather than
   as firms, deliberately — phantom boundary firms would be handed 122,195
   workers by `city.sim.firms/init` and would wreck a size distribution whose
   tail exponent is currently 1.52 against an observed 1.50.

   Call **after** `assign-workplaces-grid!`, like its mirror: an out-commuter
   must first be excluded from the city's job market, not competing for it."
  [world destinations & {:keys [seed jitter-deg] :or {seed 17 jitter-deg 0.004}}]
  (if-not (seq destinations)
    world
    (let [ps (:persons world) n (:n ps)
          ^ints out (or (:outside ps) (int-array n))
          ^doubles hlon (:home-lon ps) ^doubles hlat (:home-lat ps)
          ^ints ext (or (:external ps) (int-array n))
          fs (:firms world) ^doubles flon (:lon fs) ^doubles flat (:lat fs) nf (:n fs)
          bb (let [w (double-array 1 Double/POSITIVE_INFINITY) e (double-array 1 Double/NEGATIVE_INFINITY)
                   so (double-array 1 Double/POSITIVE_INFINITY) no (double-array 1 Double/NEGATIVE_INFINITY)]
               (dotimes [i n]
                 (when (and (zero? (aget ext i)) (not (Double/isNaN (aget hlon i))))
                   (aset w 0 (min (aget w 0) (aget hlon i))) (aset e 0 (max (aget e 0) (aget hlon i)))
                   (aset so 0 (min (aget so 0) (aget hlat i))) (aset no 0 (max (aget no 0) (aget hlat i)))))
               (dotimes [j nf]
                 (aset w 0 (min (aget w 0) (aget flon j))) (aset e 0 (max (aget e 0) (aget flon j)))
                 (aset so 0 (min (aget so 0) (aget flat j))) (aset no 0 (max (aget no 0) (aget flat j))))
               {:west (aget w 0) :east (aget e 0) :south (aget so 0) :north (aget no 0)})
          ds (vec destinations)
          tot (double (reduce + (map #(double (or (:flow %) 1)) ds)))
          cdf (double-array (count ds))
          _ (loop [k 0 acc 0.0]
              (when (< k (count ds))
                (let [acc (+ acc (/ (double (or (:flow (ds k)) 1)) tot))]
                  (aset cdf k acc) (recur (inc k) acc))))
          pick (fn [^double u] (loop [k 0] (if (or (= k (dec (count ds))) (< u (aget cdf k))) k (recur (inc k)))))
          clamp (fn ^double [^double x ^double lo ^double hi] (max lo (min hi x)))
          rng (java.util.Random. seed)
          xlon (double-array n Double/NaN) xlat (double-array n Double/NaN)
          placed (long-array (count ds))]
      (dotimes [i n]
        (when (and (= 1 (aget out i)) (zero? (aget ext i)))
          (let [k (pick (.nextDouble rng)) d (ds k)
                jit (fn [] (* (double jitter-deg) (- (.nextDouble rng) 0.5)))]
            (aset xlon i (+ (clamp (double (:lon d)) (:west bb) (:east bb)) (jit)))
            (aset xlat i (+ (clamp (double (:lat d)) (:south bb) (:north bb)) (jit)))
            (aset placed k (inc (aget placed k))))))
      (-> world
          (assoc-in [:persons :exit-lon] xlon)
          (assoc-in [:persons :exit-lat] xlat)
          (assoc :exit-points
                 {:bbox bb :destinations (count ds)
                  :placed (vec (for [k (range (count ds))] {:name (:name (ds k)) :n (aget placed k)}))
                  :total (reduce + (seq placed))})))))

(defn build
  "A world from a persons file, zone centroids, a firm file and the commuting
   `shares` (`{:residents-with-workplace :share-work-in-city :jobs-in-city}`):
   every employed resident is a city worker, an out-commuter or a person with
   no fixed workplace in the published proportions, and `jobs − jobs held by
   residents` in-commuters are appended (`labour-roles!`). Firm capacity is
   rescaled from the register's employee counts to the published count of jobs
   in the city (and to the sample)."
  [{:keys [persons-path da-centroids year sample seed lambda-m shares firms-path jitter-deg origins
           out-destinations]
    :or {year 2025 sample 1.0 seed 7 lambda-m 6000.0 jitter-deg 0.002}}]
  (let [persons (persons-columns persons-path da-centroids :seed seed :sample sample :jitter-deg jitter-deg)
        firms (file-firms firms-path)
        fcols (firm-columns firms)
        ;; Register employee counts are a target, not truth: rescale total capacity
        ;; to the published count of jobs in the city, and to the population sample.
        licence-cap (reduce + (map :employees firms))
        jobs (double (:jobs-in-city shares))
        cap-scale (* sample (/ jobs (max 1.0 licence-cap)))
        ^ints emp (:employees fcols)
        _ (dotimes [j (:n fcols)] (aset emp j (int (Math/round (* cap-scale (aget emp j))))))
        world {:persons persons :firms fcols}
        world (labour-roles! world shares :sample sample :seed seed)
        world (assign-workplaces-grid! world :lambda-m lambda-m :seed seed)
        ;; homes for the in-commuters come last: their workplace is drawn from
        ;; capacity alone, and a boundary home would bias it to the edge
        world (place-externals! world origins :seed seed)
        ;; and the mirror: an out-commuter leaves by the boundary on the side of
        ;; their destination, instead of holding no workplace and staying home
        world (if (seq out-destinations)
                (place-out-commuters! world out-destinations :seed seed)
                world)]
    (assoc world :meta {:persons (:n persons) :firms (count firms) :sample sample :year year
                        :licence-capacity licence-cap :capacity-scale cap-scale
                        :commute (:commute world) :workplaces (:workplaces world)})))

(defn build-stuttgart
  "The Stuttgart world, from files. Every input is produced from aggregates by
   `city.synth.stuttgart` and `city.synth.stuttgart-firms`:

   - persons: `data/derived/synth_stuttgart_persons.edn`, `:da` a Zensus 100 m
     cell, `:la` a Stadtteil;
   - centroids: `data/derived/stuttgart_cell_centroids.jsonl`, one per cell;
   - firms: `data/derived/firms/stuttgart-2025.json`, one file for the city;
   - shares: `data/derived/stuttgart_commute_shares.edn` from the BA
     Gemeindedaten. Germany has no 'no fixed workplace' category, so every
     employed resident is a city worker or an out-commuter."
  [& {:keys [sample seed lambda-m persons-path firms-path shares-path]
      :or {sample 1.0 seed 7 lambda-m 6000.0
           persons-path "data/derived/synth_stuttgart_persons.edn"
           firms-path "data/derived/firms/stuttgart-2025.json"
           shares-path "data/derived/stuttgart_commute_shares.edn"}}]
  (let [cents (with-open [r (io/reader "data/derived/stuttgart_cell_centroids.jsonl")]
                (into {} (for [l (line-seq r) :let [m (json/read-str l :key-fn keyword)]]
                           [(:da m) [(:lon m) (:lat m)]])))
        shares (edn/read-string (slurp shares-path))]
    (assoc (build {:persons-path persons-path :da-centroids cents :firms-path firms-path
                   :shares shares :sample sample :seed seed :lambda-m lambda-m :year 2025
                   :jitter-deg 0.0013
                   :origins (origins "data/derived/stuttgart_incommuter_origins.jsonl")
                   :out-destinations stuttgart-out-destinations})
           :city :stuttgart :shares shares)))

(def mid-2023-stuttgart-modes
  "**MiD 2023 small-area estimate for Stadt Stuttgart** — the mode split of all
   trips by Stuttgart residents, from the same table
   (`MiD23_SAE_..._Gemeindedaten.xlsx`, GKZ 8111000) that supplies the trip
   *level* of 2.861: Fuß 31.11, Rad 9.50, MIV-Mitfahrer 11.35, MIV-Fahrer
   24.69, ÖV 23.36 %. Car driver and car passenger are one `:car`, the router
   having one road mode.

   **Not used by the published run**, which draws from the 2017 split below.
   The model therefore mixes a 2023 trip level with a 2017 mode split, an
   inconsistency worth naming: the bike share rises 8 → 9.5 % and the car share
   falls 40 → 36 % between the two vintages. Switching is a change of its own,
   because the bicycle target is scored against the bike share."
  {:walk 31 :bike 10 :car 36 :transit 23 :other 0})

(def mid-2017-stuttgart-modes
  "**MiD 2017, Stadt Stuttgart Grundauswertung** — the modal split of all trips
   made by Stuttgart residents (n = 6,252 trips): walk 29 %, bike 8 %, car
   driver 31 %, car passenger 9 %, public transport 23 %
   (`doc/sources/activity-time-use.md`).

   Shaped as `city.sim.day/mode-order` counts so it can be handed to
   `day/prepare` as `:mode-shares`, where `day/city-wide?` recognises it
   as *one* profile for the whole city. Two properties are worth keeping in
   sight:

   - it is a split of **all trips**, not of commutes, which is the right
     measurement for shopping and leisure legs as well;
   - it has **no small-area version**. MiD publishes Stadt Stuttgart and
     nothing below it, so every resident of every Stadtteil draws from the same
     row: the model has no more spatial variation in mode than the source does.

   Car driver and car passenger are both `:car` — the router has one road mode
   — so the car share is 40 %. `:other` is 0: MiD's five categories cover the
   whole trip population."
  {:walk 29 :bike 8 :car 40 :transit 23 :other 0})

;; ---- local areas: geometry, and the aggregate view ------------------------------------------

(defn area-polygons-fc
  "Area boundaries from a GeoJSON FeatureCollection (`city.web/areas`) as
   `[{:eid :name :rings [[[lon lat] ...] ...] :west :south :east :north}]`.
   Holes and multi-part areas need no special case: the ray cast XORs over
   every ring, so a point inside a hole crosses twice and falls out.

   Stuttgart's aggregate areas are its 152 Stadtteile, the level the person
   and firm columns carry in `:la`, and therefore the only level the aggregate
   can be reduced to rather than redistributed onto."
  [fc]
  (vec (for [f (:features fc)
             :let [g (:geometry f)
                   rings (vec (if (= "Polygon" (:type g)) (:coordinates g) (apply concat (:coordinates g))))
                   pts (apply concat rings)]]
         {:eid (get-in f [:properties :eid]) :name (get-in f [:properties :name])
          :rings (mapv #(mapv (fn [c] [(double (first c)) (double (second c))]) %) rings)
          :west (reduce min (map first pts)) :east (reduce max (map first pts))
          :south (reduce min (map second pts)) :north (reduce max (map second pts))})))

(defn- inside? [{:keys [rings west east south north]} ^double x ^double y]
  (and (<= (double west) x (double east)) (<= (double south) y (double north))
       (loop [rs (seq rings) odd false]
         (if-let [ring (first rs)]
           (let [v ring n (count v)]
             (recur (next rs)
                    (loop [i 0 j (dec n) odd odd]
                      (if (>= i n) odd
                          (let [[xi yi] (v i) [xj yj] (v j)
                                xi (double xi) yi (double yi) xj (double xj) yj (double yj)
                                cross (and (not= (> yi y) (> yj y))
                                           (< x (+ xi (/ (* (- xj xi) (- y yi)) (- yj yi)))))]
                            (recur (inc i) i (if cross (not odd) odd)))))))
           odd))))

(defn area-raster
  "Local-area index per grid cell — one point-in-polygon test per cell centre,
   so mapping a trip endpoint to an area afterwards is an array lookup rather
   than 22 ray casts."
  [grid polys]
  (let [n (:n grid) cell (int-array n -1) ps (vec polys)]
    (dotimes [c n]
      (let [[lon lat] (d2/cell-center grid c)]
        (aset cell c (int (or (first (keep-indexed (fn [i p] (when (inside? p (double lon) (double lat)) i)) ps)) -1)))))
    {:cell cell :grid grid :areas (mapv #(select-keys % [:eid :name]) ps)}))

(defn area-at
  "Local-area index for a point, or −1 (outside the city)."
  ^long [{:keys [^ints cell grid]} ^double lon ^double lat]
  (let [{:keys [^double west ^double south ^double dlon ^double dlat ^long W ^long H]} grid]
    (if (and (<= west lon (+ west (* W dlon))) (<= south lat (+ south (* H dlat))))
      (aget cell (d2/cell-of grid lon lat))
      -1)))

(defn area-aggregates
  "Per local area, the quantities the zoomed-out view shows, all from **one**
   run: who lives there, who works there, where the workers come from, how many
   storefront visits the day produced — plus the origin–destination matrix of
   resident trips between areas, counted on the traced day and scaled by its
   stride.

   Residence and workplace come from the person and firm columns (`:la`), so no
   geometry is needed for them; only the trip endpoints are rasterized.

   `legs` is either the nested traces (`[{:person :legs}]`) or a flat sequence
   of leg maps — only `:path` and `:access` are ever read, so both work. The
   flat form exists because holding the nested traces *and* the flattened copy
   at once is what killed a 6 GB heap mid-Stuttgart on 2026-09-11: the publish
   path now builds only the flat legs and this reduce consumes them directly."
  [world {:keys [visits]} legs* & {:keys [stride raster] :or {stride 10}}]
  (let [ps (:persons world) n (:n ps) fs (:firms world) nf (:n fs)
        ^objects pla (:la ps) ^objects fla (:la fs)
        ^ints work (:work ps) ^ints emp (:employed ps) ^ints workstat (:workstat ps)
        ^ints sf (:storefront fs)
        ;; one canonical area order for everything: the raster's, because the OD
        ;; keys are raster indices and the resident/firm columns are area *names*
        names (mapv :name (:areas raster))
        ix (zipmap names (range)) na (count names)
        residents (long-array na) res-workers (long-array na)
        in-comm (long-array na) out-comm (long-array na)
        storefronts (long-array na) jobs (long-array na)
        sf-visits (long-array na)
        bump! (fn [^longs a k] (when-let [q (ix k)] (aset a (long q) (inc (aget a (long q))))))]
    (dotimes [i n]
      (let [home (aget pla i) ws (aget workstat i)
            wj (aget work i)
            wla (when (>= wj 0) (aget fla wj))]
        (when (and home (not= "external" home))
          (bump! residents home)
          (when (= 1 (aget emp i)) (bump! res-workers home)))
        (when wla
          (bump! jobs wla)
          (if (or (nil? home) (= "external" home) (not= home wla))
            (bump! in-comm wla)
            nil))
        ;; out-commuters: a resident with a job that is not in their own area,
        ;; plus everyone the census sends out of the city altogether
        (when (and home (not= "external" home))
          (when (or (= 2 ws) (and (= 1 ws) wla (not= wla home)))
            (bump! out-comm home)))))
    (dotimes [j nf]
      (when-let [a (ix (aget fla j))]
        (when (= 1 (aget sf j))
          (aset storefronts a (inc (aget storefronts a)))
          (aset sf-visits a (+ (aget sf-visits a) (d2/visits-total visits j))))))
    (let [od (java.util.HashMap.)
          ;; accept nested traces or an already-flat leg sequence
          legs (if (and (seq legs*) (contains? (first legs*) :legs))
                 (mapcat :legs legs*)
                 legs*)]
      (doseq [{:keys [path access]} legs
              ;; a transit leg's access/egress walk stub is part of that trip,
              ;; not another trip: it must not enter the OD matrix
              :when (and (not access) (>= (count path) 2))]
        (let [[alon alat] (first path) [blon blat] (peek path)
              a (area-at raster (double alon) (double alat))
              b (area-at raster (double blon) (double blat))]
          (when (and (>= a 0) (>= b 0))
            ;; the pair packed into one long. The stride is the area *count*:
            ;; Stuttgart has 152 Stadtteile, and a fixed stride of 64 would
            ;; silently fold area 70 onto area 6.
            (let [k (+ (* (long a) (long na)) (long b))]
              (.put od k (inc (long (or (.get od k) 0))))))))
      {:areas (vec (for [[name q] (map vector names (range))
                         :let [r (aget residents q)]]
                     {:area name :eid (:eid (nth (:areas raster) q))
                      :residents r
                      :resident-workers (aget res-workers q)
                      :jobs (aget jobs q)
                      :in-commuters (aget in-comm q)
                      :out-commuters (aget out-comm q)
                      :storefronts (aget storefronts q)
                      :storefront-visits (aget sf-visits q)
                      :visits-per-resident (when (pos? r) (/ (Math/round (* 1000.0 (/ (double (aget sf-visits q)) r))) 1000.0))}))
       :od (vec (sort-by #(- (:trips %))
                         (for [[k v] od]
                           {:from (names (quot (long k) (long na))) :to (names (mod (long k) (long na)))
                            :trips (* (long stride) (long v))})))
       :stride stride
       :od-legs (count (remove :access legs))})))
