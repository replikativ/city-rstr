(ns city.sim.network
  "Street network for routing trip legs.

   Input is one Overpass pull of `way[\"highway\"]` with `out geom;` — the way
   geometry, no node ids — so vertices are deduplicated by rounded coordinate
   (1e-6 deg ≈ 0.1 m) to recover the junctions. The graph is flat arrays in the
   same style as the rest of the simulator: CSR adjacency, a uniform grid for
   nearest-node lookup, and an A* with a haversine heuristic that stamps its
   visited/g/f arrays with a generation counter so a query never pays for
   clearing them.

   Routes are cached by [from-node to-node]; legs in a district repeat their
   endpoints often (every home cell centre is shared by the households in it),
   so the cache is what makes a whole simulated day routable in seconds."
  (:require [city.intake.core :as acq]
            [city.sim.world :as w]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.util ArrayList HashMap]))

(def excluded-highways
  "Ways nobody in the model can travel on. Motorways stay in — a car leg may
   legitimately use one — but nothing that is not a line you can move along."
  #{"proposed" "construction" "raceway" "platform" "elevator" "rest_area"})

;; ---- reading the pull ----------------------------------------------------------------------

(def stuttgart-dataset
  "The Stuttgart pull: one `way[\"highway\"]` query over the Stuttgart bbox
   (74 MB, `out geom`), the network every routed leg uses."
  "stuttgart-highways")

(def dataset-paths
  "Where a bulk pull lives when no receipt has been written for it yet. A
   receipt still wins; this is only so a fresh checkout of the data directory
   routes without an `adopt!` step first."
  {"stuttgart-highways" "data/raw/osm-overpass/stuttgart_highways.json"})

(defn receipt
  "Newest Overpass highway pull of dataset `ds`, or nil."
  ([] (receipt stuttgart-dataset))
  ([ds] (first (filter #(and (= :osm-overpass (:acq/source %)) (= ds (:acq/dataset %))) (acq/receipts)))))

(defn source-path
  "The file a dataset name resolves to: its receipt's path, or the known bulk
   path when the pull was never adopted."
  [ds]
  (or (:acq/path (receipt ds))
      (let [p (dataset-paths ds)] (when (and p (.exists (io/file p))) p))))

(defn stream-array!
  "Reduce `f` over the JSON array under the top-level key `k` of `path`, *one
   element at a time*. `clojure.data.json/read` takes a single value off a
   reader and leaves the rest, so the 49 MB city pull never exists as one
   Clojure value — which is the difference between building the city graph in a
   4 GB heap and not building it at all.

   The same reader serves both pull formats the model consumes: Overpass JSON
   (`\"elements\"`) and ohsome GeoJSON (`\"features\"`)."
  [path k f init]
  (with-open [r (java.io.PushbackReader. (io/reader path) 64)]
    (let [pat (seq (str \" k \"))]
      ;; scan to the elements key, then to the opening bracket of its array
      (loop [need pat]
        (when need
          (let [c (.read r)]
            (cond (neg? c) (throw (ex-info "no such array in JSON" {:path path :key k}))
                  (= (char c) (first need)) (recur (next need))
                  (= (char c) (first pat)) (recur (next pat))
                  :else (recur pat)))))
      (loop [] (let [c (.read r)]
                 (cond (neg? c) (throw (ex-info "no such array in JSON" {:path path :key k}))
                       (= \[ (char c)) nil
                       :else (recur))))
      (loop [acc init]
        (let [c (.read r)]
          (cond
            (neg? c) acc
            (= \] (char c)) acc
            (Character/isWhitespace c) (recur acc)
            (= \, (char c)) (recur acc)
            :else (do (.unread r c)
                      (recur (f acc (json/read r :key-fn keyword))))))))))

(defn stream-elements!
  "`stream-array!` over an Overpass pull's `elements`."
  [path f init]
  (stream-array! path "elements" f init))

(defn usable-way
  "The way's geometry as [[lon lat] ...], or nil when nothing can travel on it."
  [e]
  (when (and (= "way" (:type e)) (seq (:geometry e))
             (not (excluded-highways (get-in e [:tags :highway])))
             (not= "yes" (get-in e [:tags :area])))
    (mapv (fn [g] [(double (:lon g)) (double (:lat g))]) (:geometry e))))

(defn ways
  "[[ [lon lat] ... ] ...] — the geometry of every usable highway way, from a
   receipt or from a path."
  [receipt-or-path]
  (let [path (if (string? receipt-or-path) receipt-or-path (:acq/path receipt-or-path))]
    (persistent! (stream-elements! path (fn [acc e] (if-let [w (usable-way e)] (conj! acc w) acc)) (transient [])))))

;; ---- graph ---------------------------------------------------------------------------------

(defn- key-of ^long [^double lon ^double lat]
  (bit-or (bit-shift-left (long (Math/round (* lat 1.0e6))) 32)
          (bit-and (long (Math/round (* lon 1.0e6))) 0xFFFFFFFF)))

(defn build
  "Way geometries → {:n :lon :lat :offsets :targets :weights :grid}."
  [ways]
  (let [ids (HashMap.)
        lons (ArrayList.) lats (ArrayList.)
        node! (fn ^long [[lon lat]]
                (let [k (key-of lon lat)]
                  (if-let [v (.get ids k)]
                    (long v)
                    (let [i (.size lons)]
                      (.add lons lon) (.add lats lat) (.put ids k i)
                      i))))
        ea (ArrayList.) eb (ArrayList.) ew (ArrayList.)]
    (doseq [wpts ways]
      (loop [prev (node! (first wpts)) rest (next wpts)]
        (when-let [p (first rest)]
          (let [cur (node! p)]
            (when (not= prev cur)
              (let [d (w/haversine-m (double (.get lons prev)) (double (.get lats prev))
                                     (double (.get lons cur)) (double (.get lats cur)))]
                (.add ea prev) (.add eb cur) (.add ew d)))
            (recur cur (next rest))))))
    (let [n (.size lons) m (.size ea)
          lon (double-array n) lat (double-array n)
          _ (dotimes [i n] (aset lon i (double (.get lons i))) (aset lat i (double (.get lats i))))
          deg (int-array n)
          _ (dotimes [e m] (let [a (int (.get ea e)) b (int (.get eb e))]
                             (aset deg a (inc (aget deg a))) (aset deg b (inc (aget deg b)))))
          offsets (int-array (inc n))
          _ (dotimes [i n] (aset offsets (inc i) (+ (aget offsets i) (aget deg i))))
          fill (int-array n)
          targets (int-array (* 2 m)) weights (double-array (* 2 m))
          put! (fn [^long a ^long b ^double d]
                 (let [p (+ (aget offsets a) (aget fill a))]
                   (aset targets p (int b)) (aset weights p d) (aset fill a (inc (aget fill a)))))
          _ (dotimes [e m]
              (let [a (int (.get ea e)) b (int (.get eb e)) d (double (.get ew e))]
                (put! a b d) (put! b a d)))]
      {:n n :edges m :lon lon :lat lat :offsets offsets :targets targets :weights weights})))

;; ---- grid index for nearest node -------------------------------------------------------------

(defn index
  "Uniform ~`cell-m` grid over the nodes: cell → int[] of node indices."
  [{:keys [n ^doubles lon ^doubles lat] :as net} & {:keys [cell-m] :or {cell-m 120.0}}]
  (let [west (reduce min (seq lon)) east (reduce max (seq lon))
        south (reduce min (seq lat)) north (reduce max (seq lat))
        dlat (/ cell-m 111320.0)
        dlon (/ cell-m (* 111320.0 (Math/cos (Math/toRadians (/ (+ south north) 2)))))
        W (inc (long (/ (- east west) dlon))) H (inc (long (/ (- north south) dlat)))
        cnt (int-array (* W H))
        cell (fn ^long [^double x ^double y]
               (+ (min (dec W) (max 0 (long (/ (- x west) dlon))))
                  (* W (min (dec H) (max 0 (long (/ (- y south) dlat)))))))
        cells (int-array n)
        _ (dotimes [i n]
            (let [c (cell (aget lon i) (aget lat i))]
              (aset cells i (int c)) (aset cnt c (inc (aget cnt c)))))
        off (int-array (inc (* W H)))
        _ (dotimes [c (* W H)] (aset off (inc c) (+ (aget off c) (aget cnt c))))
        fill (int-array (* W H))
        items (int-array n)
        _ (dotimes [i n]
            (let [c (aget cells i) p (+ (aget off c) (aget fill c))]
              (aset items p (int i)) (aset fill c (inc (aget fill c)))))]
    (assoc net :grid {:west west :south south :dlon dlon :dlat dlat :W W :H H
                      :offsets off :items items :cell-m cell-m})))

(defn- ring-cells
  "The cells at Chebyshev distance r from (cx, cy)."
  [^long cx ^long cy ^long r]
  (if (zero? r)
    [[cx cy]]
    (concat (for [gx (range (- cx r) (inc (+ cx r)))] [gx (- cy r)])
            (for [gx (range (- cx r) (inc (+ cx r)))] [gx (+ cy r)])
            (for [gy (range (inc (- cy r)) (+ cy r))] [(- cx r) gy])
            (for [gy (range (inc (- cy r)) (+ cy r))] [(+ cx r) gy]))))

(defn nearest
  "Index of the node nearest [lon lat], searching the grid ring by ring and
   stopping once the ring is further away than the best node found."
  ^long [{:keys [^doubles lon ^doubles lat grid]} ^double x ^double y]
  (let [{:keys [^double west ^double south ^double dlon ^double dlat
                ^long W ^long H ^ints offsets ^ints items ^double cell-m]} grid
        cx (min (dec W) (max 0 (long (/ (- x west) dlon))))
        cy (min (dec H) (max 0 (long (/ (- y south) dlat))))]
    (loop [r 0 best -1 bd Double/MAX_VALUE]
      (if (or (> r (+ W H))
              (and (>= best 0) (< bd (* r cell-m))))
        best
        (let [[best bd]
              (reduce (fn [[best bd] [gx gy]]
                        (if (or (neg? (long gx)) (neg? (long gy)) (>= (long gx) W) (>= (long gy) H))
                          [best bd]
                          (let [c (+ (long gx) (* W (long gy)))]
                            (loop [p (aget offsets c) best best bd bd]
                              (if (>= p (aget offsets (inc c)))
                                [best bd]
                                (let [i (aget items p)
                                      d (w/haversine-m x y (aget lon i) (aget lat i))]
                                  (if (< d (double bd))
                                    (recur (inc p) (long i) d)
                                    (recur (inc p) best bd))))))))
                      [best bd] (ring-cells cx cy r))]
          (recur (inc r) best bd))))))

;; ---- route diversity ------------------------------------------------------------------------

(def walk-route-variants
  "How many near-shortest alternatives a walk leg picks between. Variant 0 is
   the true shortest path; every other variant runs the same A* over edge
   lengths multiplied by a deterministic per-edge penalty in
   [1, 1 + `walk-route-jitter`], which yields a *different* near-shortest route
   without a k-shortest-path search. A leg draws its variant from its own RNG
   stream, so cross-town walkers spread over parallel streets instead of all
   taking the one diagonal the metric prefers."
  3)

(def walk-route-jitter
  "Upper bound of the per-edge length penalty in a jittered variant. 0.3 means
   a detour is taken when it is under ~30 % longer, which is roughly the range
   real pedestrians are observed to accept."
  0.3)

(def route-cache-max
  "Entries per variant cache before it is dropped. Three caches over a
   city-wide day at stride 1 would otherwise hold a million polylines; a cache
   is only an optimisation, so it is cleared rather than grown.

   At three variants this bounds the cache at 450,000 polylines. Stored as
   vectors of vectors that was about **1.0 GB**; stored as primitive arrays
   (`pairs->coords`) it is about **160 MB**."
  150000)

(defn- mix01
  "splitmix64 → a double in [0,1). Deterministic, so the same (edge, variant)
   always gets the same penalty and a variant is a fixed alternative network."
  ^double [^long x]
  (let [z (unchecked-add x -7046029254386353131)
        z (unchecked-multiply (bit-xor z (unsigned-bit-shift-right z 30)) -4658895280553007687)
        z (unchecked-multiply (bit-xor z (unsigned-bit-shift-right z 27)) -7723592293110705685)
        z (bit-xor z (unsigned-bit-shift-right z 31))]
    (/ (double (unsigned-bit-shift-right z 11)) 9.007199254740992E15)))

(defn- penalty
  "Length multiplier of the undirected edge a–b in `variant`; 1.0 in variant 0.
   Hashed on the unordered node pair so both directions agree."
  ^double [^long a ^long b ^long variant ^double jitter]
  (if (zero? variant)
    1.0
    (+ 1.0 (* jitter (mix01 (+ (* 1000003 (min a b)) (max a b) (* variant 7919)))))))

;; ---- A* -------------------------------------------------------------------------------------

(definterface IHeap
  (^void push [^double k ^long id])
  (^long pop [])
  (^boolean isEmpty []))

(deftype Heap [^:unsynchronized-mutable ^doubles keys
               ^:unsynchronized-mutable ^ints ids
               ^:unsynchronized-mutable ^long size]
  IHeap
  (isEmpty [_] (zero? size))
  (push [_ k id]
    ;; sift-up insert; doubles the arrays when full. Ties break arbitrarily,
    ;; as the PriorityQueue's did, and A*'s correctness never depended on it.
    (when (= size (alength keys))
      (let [cap (* 2 (alength keys)) nk (double-array cap) ni (int-array cap)]
        (System/arraycopy keys 0 nk 0 size) (System/arraycopy ids 0 ni 0 size)
        (set! keys nk) (set! ids ni)))
    (let [^doubles ks keys ^ints is ids]
      (loop [i size]
        (let [p (quot (dec i) 2)]
          (if (and (pos? i) (< k (aget ks p)))
            (do (aset ks i (aget ks p)) (aset is i (aget is p)) (recur p))
            (do (aset ks i k) (aset is i (int id)))))))
    (set! size (inc size)))
  (pop [_]
    ;; the id with the smallest key; sift-down of the last element
    (let [^doubles ks keys ^ints is ids
          top (aget is 0) n (dec size) k (aget ks n) id (aget is n)]
      (set! size n)
      (when (pos? n)
        (loop [i 0]
          (let [l (inc (* 2 i)) r (inc l)
                c (cond (>= l n) -1
                        (and (< r n) (< (aget ks r) (aget ks l))) r
                        :else l)]
            (if (and (>= c 0) (< (aget ks c) k))
              (do (aset ks i (aget ks c)) (aset is i (aget is c)) (recur c))
              (do (aset ks i k) (aset is i id))))))
      (long top))))

(defn- astar
  "Node path [from .. to] or nil. Scratch arrays are stamped with a generation
   counter, so a query costs nothing to set up. With `variant` > 0 the edge
   lengths carry the variant's penalty (see `penalty`); the heuristic stays
   admissible because a penalty only ever lengthens an edge."
  [{:keys [^ints offsets ^ints targets ^doubles weights ^doubles lon ^doubles lat
           ^doubles g ^ints stamp ^ints prev gen]}
   from to variant jitter]
  (let [from (long from) to (long to) variant (long variant) jitter (double jitter)
        gg (vswap! gen inc)
        tx (aget lon to) ty (aget lat to)
        ;; Measured 2026-09-16 on the Stuttgart graph: a query touches ~50,000
        ;; of 428,737 nodes at ~40 ms, and neither the queue (the boxing
        ;; PriorityQueue this heap replaced) nor the heuristic (an
        ;; equirectangular variant tried and reverted) changed that. The cost
        ;; is the search size; the fix is a hierarchy (doc/sources/
        ;; routing-algorithms.md), not a constant.
        h (fn ^double [^long i] (w/haversine-m (aget lon i) (aget lat i) tx ty))
        ;; A primitive binary heap: parallel double keys and int node ids in
        ;; growable arrays. The java.util.PriorityQueue this replaces held a
        ;; boxed vector of a one-element double array per entry and compared
        ;; through a reified Comparator — measured 2026-09-15 at 38.7 ms per
        ;; query on the Stuttgart graph, with the allocation and boxing the
        ;; dominant cost (doc/sources/routing-algorithms.md §0).
        ^Heap open (Heap. (double-array 1024) (int-array 1024) 0)
        push! (fn [^long i ^double f] (.push open f i))]
    (aset g from 0.0) (aset stamp from (int gg)) (aset prev from (int -1))
    (push! from (h from))
    (loop [guard 0]
      (if (or (.isEmpty open) (> guard 400000))
        nil
        (let [cur (.pop open)]
          (if (= cur to)
            (loop [i to acc (list)]
              (if (neg? i) (vec acc) (recur (long (aget prev i)) (conj acc i))))
            (let [gc (aget g cur)]
              (loop [p (aget offsets cur)]
                (when (< p (aget offsets (inc cur)))
                  (let [nb (aget targets p)
                        nd (+ gc (* (aget weights p) (penalty cur (long nb) variant jitter)))]
                    (when (or (not= gg (aget stamp nb)) (< nd (aget g nb)))
                      (aset stamp nb (int gg)) (aset g nb nd) (aset prev nb (int cur))
                      (push! nb (+ nd (h nb))))
                    (recur (inc p)))))
              (recur (inc guard)))))))))

;; ---- simplification --------------------------------------------------------------------------

(defn- perp-m ^double [[^double px ^double py] [^double ax ^double ay] [^double bx ^double by]]
  (let [k (Math/cos (Math/toRadians ay))
        ax' (* ax k) bx' (* bx k) px' (* px k)
        dx (- bx' ax') dy (- by ay)
        len2 (+ (* dx dx) (* dy dy))
        t (if (zero? len2) 0.0 (max 0.0 (min 1.0 (/ (+ (* (- px' ax') dx) (* (- py ay) dy)) len2))))
        qx (+ ax' (* t dx)) qy (+ ay (* t dy))]
    (* 111320.0 (Math/sqrt (+ (* (- px' qx) (- px' qx)) (* (- py qy) (- py qy)))))))

(defn simplify
  "Douglas–Peucker at `eps` metres, then a hard cap on the vertex count
   (index thinning, endpoints kept). Keeps a leg's payload small enough that a
   whole district's day fits in one JSON response."
  [pts & {:keys [eps max-n] :or {eps 12.0 max-n 40}}]
  (let [pts (vec pts) n (count pts)]
    (if (<= n 2)
      pts
      (let [keep (boolean-array n)
            _ (do (aset keep 0 true) (aset keep (dec n) true))
            _ (loop [stack (list [0 (dec n)])]
                (when-let [[a b] (first stack)]
                  (let [stack (rest stack)]
                    (if (<= (- b a) 1)
                      (recur stack)
                      (let [[bi bd] (loop [i (inc a) bi -1 bd 0.0]
                                      (if (>= i b) [bi bd]
                                          (let [d (perp-m (pts i) (pts a) (pts b))]
                                            (if (> d bd) (recur (inc i) i d) (recur (inc i) bi bd)))))]
                        (if (> bd eps)
                          (do (aset keep bi true) (recur (conj stack [a bi] [bi b])))
                          (recur stack)))))))
            out (vec (for [i (range n) :when (aget keep i)] (pts i)))
            k (count out)]
        (if (<= k max-n)
          out
          (let [step (/ (double (dec k)) (dec max-n))]
            (vec (distinct (conj (mapv #(out (min (dec k) (long (Math/round (* % step))))) (range max-n))
                                 (peek out))))))))))

;; ---- polyline storage --------------------------------------------------------------------------

(defn pairs->coords
  "`[[lon lat] ...]` → one `double[]` with lon and lat interleaved.

   A routed polyline is the largest thing this model keeps: the route cache
   holds up to `route-cache-max` of them **per variant**, three variants for
   walking, and a published day keeps one per leg. Measured on this JVM, a
   20-point polyline costs **2,353 bytes** as vectors of vectors and **354** as
   one primitive array — a factor of 6.6, because every point is a
   PersistentVector holding two boxed Doubles. At 450,000 cached entries that
   difference is about a gigabyte, which is most of what the OOM killer took on
   2026-09-12."
  ^doubles [pts]
  (let [v (vec pts) n (count v) a (double-array (* 2 n))]
    (dotimes [i n]
      (let [p (v i)]
        (aset a (* 2 i) (double (nth p 0)))
        (aset a (inc (* 2 i)) (double (nth p 1)))))
    a))

(defn coords->pairs
  "The inverse, for the wire and for callers that want points."
  [^doubles a]
  (let [n (quot (alength a) 2)]
    (vec (for [i (range n)] [(aget a (* 2 i)) (aget a (inc (* 2 i)))]))))

;; ---- the router ------------------------------------------------------------------------------

(defn scratch
  "A* work arrays + one route cache per route variant. One per router; not
   thread safe."
  [net]
  (assoc net
         :g (double-array (:n net))
         :stamp (int-array (:n net) -1)
         :prev (int-array (:n net))
         :gen (volatile! 0)
         :caches (vec (repeatedly walk-route-variants #(java.util.HashMap.)))
         :stats (atom {:routes 0 :hits 0 :misses 0 :failed 0})))

(defn- node-path-meters
  "Length of a node path *before* simplification — the travel distance, which
   `simplify` would otherwise shave by a few percent on curves."
  ^double [{:keys [^doubles lon ^doubles lat]} path]
  (let [v (vec path) n (count v)]
    (loop [q 1 acc 0.0]
      (if (>= q n)
        acc
        (let [a (long (v (dec q))) b (long (v q))]
          (recur (inc q) (+ acc (w/haversine-m (aget lon a) (aget lat a) (aget lon b) (aget lat b)))))))))

(defn router
  "→ (fn [lon1 lat1 lon2 lat2] → {:path polyline :meters d}), cached by node
   pair. `:meters` is the street distance including the two off-graph stubs, so
   it can be divided by a speed; `:path` is the thinned polyline for the wire.
   Falls back to the straight line when the two points are not connected.

   The 5-argument arity takes a *route variant* (see `walk-route-variants`):
   variant 0 is the shortest path, the others are near-shortest alternatives
   over jittered edge lengths. Each variant has its own cache, so the
   alternatives cost cache space, not a k-shortest-path search."
  [net & {:keys [eps max-n jitter] :or {eps 12.0 max-n 40 jitter walk-route-jitter}}]
  (let [caches (:caches net)
        nv (count caches)
        stats (:stats net)
        ^doubles lon (:lon net) ^doubles lat (:lat net)
        go (fn [alon alat blon blat variant]
             (let [alon (double alon) alat (double alat) blon (double blon) blat (double blat)
                   variant (long variant)
                   variant (if (or (neg? variant) (>= variant nv)) 0 variant)
                   ^java.util.HashMap cache (nth caches variant)
                   straight {:path [[alon alat] [blon blat]] :meters (w/haversine-m alon alat blon blat)}
                   a (nearest net alon alat) b (nearest net blon blat)]
               (swap! stats update :routes inc)
               (if (or (neg? a) (neg? b))
                 straight
                 (let [k (bit-or (bit-shift-left (long a) 32) (bit-and (long b) 0xFFFFFFFF))
                       ;; the cache holds the interior as one primitive array, not as
                       ;; vectors of vectors — see `pairs->coords`
                       [^doubles mid m] (if-let [c (.get cache k)]
                                          (do (swap! stats update :hits inc) c)
                                          (let [path (astar net a b variant (double jitter))
                                                pl (when path (simplify (mapv (fn [i] [(aget lon i) (aget lat i)]) path) :eps eps :max-n max-n))
                                                v [(pairs->coords (or pl [])) (if path (node-path-meters net path) 0.0)]]
                                            (swap! stats update (if pl :misses :failed) inc)
                                            (when (> (.size cache) (long route-cache-max)) (.clear cache))
                                            (.put cache k v)
                                            v))]
                   (if (pos? (alength mid))
                     {:path (into [[alon alat]] (conj (coords->pairs mid) [blon blat]))
                      :meters (+ (double m)
                                 (w/haversine-m alon alat (aget lon a) (aget lat a))
                                 (w/haversine-m blon blat (aget lon b) (aget lat b)))}
                     straight)))))]
    (fn
      ([alon alat blon blat] (go alon alat blon blat 0))
      ([alon alat blon blat variant] (go alon alat blon blat variant)))))

;; ---- modes, speeds, transit access -----------------------------------------------------------

(def mode-speeds-kmh
  "Speeds a leg is routed at. Walk and bike are the planning defaults
   (4.8 km/h ≈ 1.33 m/s; 15 km/h). The car speed is a *district door-to-door*
   speed, far under the posted 50: its time goes into junctions, parking and
   the first and last block. Transit is a typical urban bus operating speed,
   in-vehicle only; access, egress and wait are separate. These are assumed,
   not measured for Stuttgart."
  {:walk 4.8 :bike 15.0 :car 25.0 :transit 18.0})

(def transit-wait-min
  "Wait at the boarding stop, a constant: half of a 10-minute headway. The stop
   table carries each stop's own mean headway (`city.intake.gtfs/load-area`);
   using half of it instead is open work."
  5.0)

(def transit-min-ride-m
  "A transit leg shorter than this in-vehicle is not worth the access and the
   wait; the leg degrades to a walk."
  500.0)

(def unknown-mode-walk-m
  "A leg whose diary episode carries no usable mode is walked below this
   distance and driven above it."
  1000.0)

(def profile-walk-max-m
  "A person whose census mode is *walk* walks a leg up to this far (crow
   flight) and takes transit beyond it. The census mode is a commute mode, not
   a promise to walk across the city; 2.5 km is ~30 min at the walking speed,
   about the upper end of observed walk-trip lengths."
  2500.0)

(def profile-bike-max-m
  "Same cap for a *bike* person: beyond it the leg becomes transit."
  8000.0)

(def mode-of-code
  "`city.sim.day/mode-codes` (TUS travel-episode locations) → routing mode.
   −1 (no travel episode at all) and 10 (travel, other/not stated) are
   `:unknown` and get resolved by distance."
  {0 :car 1 :car 2 :walk 3 :transit 4 :bike 5 :car
   6 :car 7 :car 8 :transit 9 :car 10 :unknown -1 :unknown})

(defn minutes-at
  "Minutes to cover `meters` at `kmh`."
  ^double [^double kmh ^double meters]
  (/ (* 60.0 meters) (* 1000.0 kmh)))

(defonce ^{:doc "Transit stops used as access points: an `index`ed pseudo-net
                 plus the stop rows (see `city.intake.gtfs`)."}
  stops (atom nil))

(defn set-stops!
  "Install transit access points. `rows` are maps with at least :lon and :lat
   (the `:stops` rows of `city.intake.gtfs/load-area`); a nil or empty seq clears them,
   which makes every transit leg degrade to a walk."
  [rows]
  (let [rows (vec rows) n (count rows)]
    (reset! stops
            (when (pos? n)
              (assoc (index {:n n
                             :lon (double-array (map #(double (:lon %)) rows))
                             :lat (double-array (map #(double (:lat %)) rows))}
                            :cell-m 250.0)
                     :rows rows)))
    n))

(defn- mode-router*
  "One leg on the mode network; see `mode-router`."
  [route alon alat blon blat mode variant]
  (let [alon (double alon) alat (double alat) blon (double blon) blat (double blat)
        variant (long variant)
        walk-route (fn [x1 y1 x2 y2] (route x1 y1 x2 y2 variant))
        base (walk-route alon alat blon blat)
        walked (fn [] (assoc base :mode :walk :minutes (minutes-at (mode-speeds-kmh :walk) (:meters base))))
        mode (if (= :unknown mode)
               (if (< (double (:meters base)) unknown-mode-walk-m) :walk :car)
               mode)]
    (if (not= :transit mode)
      (assoc base :mode mode :minutes (minutes-at (mode-speeds-kmh mode) (:meters base)))
      (if-let [st @stops]
        (let [^doubles slon (:lon st) ^doubles slat (:lat st)
              sa (nearest st alon alat) sb (nearest st blon blat)]
          (if (or (neg? sa) (neg? sb) (= sa sb))
            (walked)
            (let [acc (walk-route alon alat (aget slon sa) (aget slat sa))
                  ride (route (aget slon sa) (aget slat sa) (aget slon sb) (aget slat sb))
                  egr (walk-route (aget slon sb) (aget slat sb) blon blat)]
              (if (< (double (:meters ride)) transit-min-ride-m)
                (walked)
                (let [acc-min (minutes-at (mode-speeds-kmh :walk) (:meters acc))
                      ride-min (minutes-at (mode-speeds-kmh :transit) (:meters ride))
                      egr-min (minutes-at (mode-speeds-kmh :walk) (:meters egr))
                      total (+ acc-min transit-wait-min ride-min egr-min)]
                  {:mode :transit
                   :path (vec (concat (:path acc) (rest (:path ride)) (rest (:path egr))))
                   :meters (+ (double (:meters acc)) (double (:meters ride)) (double (:meters egr)))
                   :access-m (+ (double (:meters acc)) (double (:meters egr)))
                   :minutes total
                   :sub-legs [{:purpose :access :path (:path acc) :meters (:meters acc)
                               :minutes acc-min :offset-min 0.0}
                              {:purpose :access :path (:path egr) :meters (:meters egr)
                               :minutes egr-min :offset-min (- total egr-min)}]})))))
        (walked)))))

(defn mode-router
  "→ (fn [lon1 lat1 lon2 lat2 mode] → {:mode :path :meters :minutes}), with a
   6-argument arity that also takes a walk *route variant* (see `router`).

   walk / bike / car are the street route at the mode's speed. Transit is
   *walk to the nearest stop + wait + in-vehicle run + walk off*: the
   in-vehicle leg is routed on the street graph between the two stops (no
   timetable, no line topology — the bus goes where the street goes) at the
   transit speed. It degrades to a walk when there is no stop table, when both
   ends share a stop, or when the ride would be under `transit-min-ride-m`.
   `:unknown` walks under `unknown-mode-walk-m` and drives above it.

   A transit leg also returns its two walk stubs in `:sub-legs`
   ({:purpose :access :path :meters :minutes :offset-min}, offset in minutes
   from the leg's departure). Access and egress walking *is* walking: the
   caller emits them as walk legs of their own so the pedestrian target counts
   them, while the leg itself stays one transit trip."
  [route]
  (fn
    ([alon alat blon blat mode] (mode-router* route alon alat blon blat mode 0))
    ([alon alat blon blat mode variant] (mode-router* route alon alat blon blat mode variant))))

;; ---- the shared network ----------------------------------------------------------------------

(defonce ^{:doc "The loaded network, built once (see `load!`)."} net (atom nil))
(defonce ^{:doc "Which pull the loaded network was built from."} net-source (atom nil))

(defn load!
  "Build (once) the routing network from the newest pull of `:ds` (default
   `stuttgart-dataset`), or from the file at `:path`. Loading a different
   source rebuilds even without `:force?`, because everything downstream (the
   venue :street class, every routed leg) reads the shared graph."
  [& {:keys [force? path ds] :or {ds stuttgart-dataset}}]
  (let [src (or path ds)]
    (when (or force? (nil? @net) (not= src @net-source))
      (let [from (or path (source-path ds))]
        (when-not from (throw (ex-info "no Overpass highway pull; acquire it first" {:dataset ds})))
        (reset! net (scratch (index (build (ways from)))))
        (reset! net-source src))))
  (select-keys @net [:n :edges]))

(defn route-fn
  "Mode router over the shared network, or nil when there is no pull to build
   it from; callers then fall back to straight legs at the diary's own timing.

   It routes on whatever network is already loaded and only builds one when
   nothing is loaded at all; `:ds` names a particular pull. It must not reload
   by default: a caller that installed another pull would silently get its legs
   snapped onto a different graph."
  [& {:keys [ds]}]
  (try (if ds (load! :ds ds) (when (nil? @net) (load!)))
       (mode-router (router @net))
       (catch Exception _ nil)))

(defn stats [] (some-> @net :stats deref))
(defn reset-stats! [] (some-> @net :stats (reset! {:routes 0 :hits 0 :misses 0 :failed 0})))
