(ns city.intake.gtfs
  "Static GTFS → the two things the movement layer needs from transit:

   1. **access points**: where a walking leg can board (stop coordinates), used
      by `city.sim.network/set-stops!` as the transit entry/exit points;
   2. **service level**: the mean weekday headway 07:00–19:00 at each stop, so
      the map can show which stops are trunk service and which are a bus every
      half hour, and so the 5-minute wait constant can later be replaced by
      half the stop's own headway.

   The feed is NVBW's Baden-Württemberg GTFS. It is read straight out of its
   zip, streaming `stop_times.txt` (726 MB) once and keeping only rows whose
   stop is inside the Stuttgart bbox and whose trip runs on the chosen weekday.
   The result is written once as a derived stop table
   (`write-stuttgart-derived!`) and read from there afterwards
   (`stops-for-stuttgart`). Nothing is loaded into a database."
  (:require [city.intake.core :as acq]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str])
  (:import [java.io BufferedReader InputStreamReader]
           [java.util HashMap HashSet]
           [java.util.zip ZipFile]))

(def stuttgart-path
  "The NVBW Baden-Württemberg feed, `ohne Linienverlauf` (no shapes): 56 MB
   zipped, 726 MB of `stop_times.txt`."
  "data/raw/probes/transit_nvbw_bw_gesamt_gtfs_ohne_linienverlauf.zip")

(def stuttgart-derived-path "data/derived/stuttgart_gtfs_stops.json")

(def stuttgart-source-url
  "https://www.nvbw.de/open-data")

(defn receipt!
  "Receipt for the NVBW feed at `path`, adopting the file on first use."
  ([] (receipt! stuttgart-path))
  ([path]
   (let [ds "nvbw-gtfs-static"]
     (or (first (filter #(= ds (:acq/dataset %)) (acq/receipts)))
         (acq/adopt! {:source :nvbw-gtfs :url stuttgart-source-url :path path :dataset ds
                      :note "NVBW Baden-Württemberg static GTFS ohne Linienverlauf, downloaded outside acquire! (56 MB)"})))))

;; ---- csv -------------------------------------------------------------------------------------

(defn- split-csv
  "GTFS CSV row → vector of fields, honouring double quotes (route names carry
   commas). Only used on the small files; `stop_times.txt` is split on plain
   commas, which its columns allow."
  [^String line]
  (let [n (.length line)]
    (loop [i 0 start 0 q? false out (transient [])]
      (if (>= i n)
        (persistent! (conj! out (.substring line start n)))
        (let [c (.charAt line i)]
          (cond
            (= c \") (recur (inc i) start (not q?) out)
            (and (= c \,) (not q?)) (recur (inc i) (inc i) q? (conj! out (.substring line start i)))
            :else (recur (inc i) start q? out)))))))

(defn- unquote-field [^String s]
  (let [s (str/trim s)]
    (if (and (> (count s) 1) (str/starts-with? s "\"") (str/ends-with? s "\""))
      (subs s 1 (dec (count s)))
      s)))

(defn- reader-for ^BufferedReader [^ZipFile z ^String entry]
  (BufferedReader. (InputStreamReader. (.getInputStream z (.getEntry z entry)) "UTF-8") (int 1048576)))

(defn- header-index
  "column name → position, from the first line (BOM stripped)."
  [^BufferedReader rd]
  (let [h (str/replace (or (.readLine rd) "") "﻿" "")]
    (into {} (map-indexed (fn [i c] [(unquote-field c) i]) (split-csv h)))))

(defn- each-row!
  "Call `(f ix fields)` for every data row of `entry`, where `ix` is the header
   index map. Returns the row count."
  [^ZipFile z ^String entry f]
  (with-open [rd (reader-for z entry)]
    (let [ix (header-index rd)]
      (loop [n 0]
        (if-let [l (.readLine rd)]
          (do (f ix (split-csv l)) (recur (inc n)))
          n)))))

;; ---- calendar --------------------------------------------------------------------------------

(defn weekday-services
  "Service ids that run on all five weekdays and not at the weekend — the
   regular weekday service. Services that exist only through
   `calendar_dates.txt` exceptions (holiday and special-event patterns) are
   deliberately excluded: they are not what a typical weekday looks like."
  [^ZipFile z]
  (let [out (HashSet.)]
    (each-row! z "calendar.txt"
               (fn [ix f]
                 ;; every field is unquoted: TransLink writes `1`, NVBW writes
                 ;; `"1"`, and the same reader has to answer for both feeds
                 (let [g (fn [k] (unquote-field (nth f (ix k) "")))
                       wk (mapv #(= "1" (str/trim (g %))) ["monday" "tuesday" "wednesday" "thursday" "friday"])
                       we (mapv #(= "1" (str/trim (g %))) ["saturday" "sunday"])]
                   (when (and (every? true? wk) (not (every? true? we)))
                     (.add out (str/trim (g "service_id")))))))
    out))

(def stuttgart-weekday-date
  "The reference weekday for the NVBW feed: **Wednesday 23 September 2026**.

   NVBW writes an all-zero `calendar.txt` — all 16,657 services have every
   weekday column at `0` — and puts every service day in `calendar_dates.txt`
   as an exception. There is therefore no such thing as a service that runs
   Monday to Friday in this feed, and the only honest weekday is **one named
   weekday**. This date is a Wednesday in school term (BW summer holidays end
   12 September) and outside every public holiday in the feed's range; the
   services running on it number 3,960, against 3,940–3,990 on the other
   Mon–Thu of its month, 4,170 on the Fridays, 3,600 on the Saturdays and
   3,030 on the Sundays."
  "20260923")

(defn services-on
  "GTFS service ids running on `yyyymmdd`, by the spec: `calendar.txt` rows
   whose date range covers the day and whose weekday column is 1, plus
   `calendar_dates.txt` additions (exception_type 1), minus its removals (2).

   This is what a feed that keeps its whole calendar in the exceptions file
   needs, and it is also the stricter reading of a feed that does not."
  [^ZipFile z ^String yyyymmdd]
  (let [d (java.time.LocalDate/parse yyyymmdd (java.time.format.DateTimeFormatter/ofPattern "yyyyMMdd"))
        dow (str/lower-case (.name (.getDayOfWeek d)))
        out (HashSet.)]
    (each-row! z "calendar.txt"
               (fn [ix f]
                 (let [g (fn [k] (unquote-field (nth f (ix k) "")))
                       from (g "start_date") to (g "end_date")]
                   (when (and (= "1" (g dow))
                              (or (empty? from) (<= (compare from yyyymmdd) 0))
                              (or (empty? to) (>= (compare to yyyymmdd) 0)))
                     (.add out (g "service_id"))))))
    (each-row! z "calendar_dates.txt"
               (fn [ix f]
                 (let [g (fn [k] (unquote-field (nth f (ix k) "")))]
                   (when (= yyyymmdd (g "date"))
                     (if (= "2" (g "exception_type"))
                       (.remove out (g "service_id"))
                       (.add out (g "service_id")))))))
    out))

;; ---- stops -----------------------------------------------------------------------------------

(defn- in-bbox? [[s w n e] ^double lat ^double lon]
  (and (<= (double s) lat (double n)) (<= (double w) lon (double e))))

(defn expand-bbox
  "[south west north east] grown by `m` metres."
  [[s w n e] m]
  (let [dlat (/ (double m) 111320.0)
        dlon (/ (double m) (* 111320.0 (Math/cos (Math/toRadians (/ (+ (double s) (double n)) 2.0)))))]
    [(- (double s) dlat) (- (double w) dlon) (+ (double n) dlat) (+ (double e) dlon)]))

(def stuttgart-bbox
  "The City of Stuttgart, for the Stuttgart world. The NVBW feed covers all of
   Baden-Württemberg (and, through the neighbouring associations, bits of
   Austria and Switzerland), so the bbox is not a convenience here — it is the
   only thing that keeps 60,000 stops out of the access-point index."
  [48.69 9.038 48.87 9.315])

(defn- stops-in [^ZipFile z bbox]
  (let [out (HashMap.)]
    (each-row! z "stops.txt"
               (fn [ix f]
                 (let [g (fn [k] (unquote-field (nth f (ix k) "")))
                       lat (try (Double/parseDouble (g "stop_lat")) (catch Exception _ Double/NaN))
                       lon (try (Double/parseDouble (g "stop_lon")) (catch Exception _ Double/NaN))]
                   (when (and (not (Double/isNaN lat)) (not (Double/isNaN lon)) (in-bbox? bbox lat lon))
                     (.put out (g "stop_id")
                           {:stop-id (g "stop_id") :code (g "stop_code") :name (g "stop_name")
                            :lat lat :lon lon})))))
    out))

;; ---- the load --------------------------------------------------------------------------------

(def peak-window
  "Headways are measured over this window, in minutes after midnight."
  [(* 7 60) (* 19 60)])

(defn- hhmmss->min
  "GTFS times may pass 24:00:00 (a trip that starts before midnight); those
   minutes stay above 1440 and fall outside the window by themselves."
  ^long [^String s]
  (let [p (str/split (str/trim s) #":")]
    (if (< (count p) 2)
      -1
      (try (+ (* 60 (Long/parseLong (nth p 0))) (Long/parseLong (nth p 1)))
           (catch Exception _ -1)))))

(defn load-area
  "Read the feed for one bbox → {:stops [...] :n-stops :n-trips :window :counts}.

   Each stop row is `{:stop-id :code :name :lon :lat :routes [..] :departures
   :headway-min}`, where `:departures` counts regular-weekday departures in the
   07:00–19:00 window and `:headway-min` is 720 / departures — the *mean*
   headway of everything that calls at the stop, which is what a passenger
   waiting for 'a bus that goes downtown' experiences when the routes overlap,
   and an underestimate of the wait for one specific route."
  ([path bbox] (load-area path bbox nil))
  ([path bbox date]
   (with-open [z (ZipFile. (io/file path))]
     (let [[w0 w1] peak-window
           svc (if date (services-on z date) (weekday-services z))
           stops (stops-in z bbox)
           ;; route_id → short name
           routes (let [m (HashMap.)]
                    (each-row! z "routes.txt"
                               (fn [ix f]
                                 (.put m (unquote-field (nth f (ix "route_id") ""))
                                       (let [s (unquote-field (nth f (ix "route_short_name") ""))]
                                         (if (seq s) s (unquote-field (nth f (ix "route_long_name") "")))))))
                    m)
           ;; trip_id → route short name, weekday trips only
           trips (let [m (HashMap.)]
                   (each-row! z "trips.txt"
                              (fn [ix f]
                                (when (.contains svc (unquote-field (nth f (ix "service_id") "")))
                                  (.put m (unquote-field (nth f (ix "trip_id") ""))
                                        (.get routes (unquote-field (nth f (ix "route_id") "")))))))
                   m)
           dep (HashMap.)   ;; stop-id → departures in window
           srv (HashMap.)   ;; stop-id → #{route}
           n-rows (with-open [rd (reader-for z "stop_times.txt")]
                    (let [ix (header-index rd)
                          i-trip (ix "trip_id") i-dep (ix "departure_time") i-stop (ix "stop_id")
                          need (inc (max i-trip i-dep i-stop))
                          ;; +1: `split` with a limit keeps the whole remainder
                          ;; in the last element, so ask for one more field
                          ;; than we read
                          lim (inc need)]
                      (loop [n 0]
                        (if-let [l (.readLine rd)]
                          (let [f (str/split l #"," lim)]
                            (when (>= (count f) need)
                              ;; `unquote-field`, not `trim`: the NVBW feed
                              ;; quotes every value, and a quoted `"14:00:00"`
                              ;; parses as no minute at all
                              (let [sid (unquote-field (nth f i-stop))]
                                (when (.containsKey stops sid)
                                  (let [tid (unquote-field (nth f i-trip))]
                                    (when-let [rt (.get trips tid)]
                                      (let [m (hhmmss->min (unquote-field (nth f i-dep)))]
                                        (when (and (>= m (long w0)) (< m (long w1)))
                                          (.put dep sid (inc (long (or (.get dep sid) 0))))
                                          (let [^HashSet s (or (.get srv sid) (let [s (HashSet.)] (.put srv sid s) s))]
                                            (.add s rt)))))))))
                            (recur (inc n)))
                          n))))
           span (double (- (long w1) (long w0)))
           rows (vec (sort-by :stop-id
                              (for [[sid s] stops
                                    :let [d (long (or (.get dep sid) 0))]]
                                (assoc s
                                       :routes (vec (sort (or (some-> ^HashSet (.get srv sid) vec) [])))
                                       :departures d
                                       :headway-min (when (pos? d) (/ (Math/round (* 10.0 (/ span d))) 10.0))))))]
       {:stops rows
        :n-stops (count rows)
        :n-served (count (filter #(pos? (long (:departures %))) rows))
        :n-weekday-trips (.size trips)
        :stop-time-rows n-rows
        :window {:from (long w0) :to (long w1)}
        :date date
        :bbox bbox}))))

;; ---- derived table ---------------------------------------------------------------------------

(defn write-derived!
  "Run `load-area` over `bbox` and write the stop table (with a receipt) to
   `out`, so the simulation JVM does not have to re-read the feed's
   `stop_times.txt` on every boot."
  ([path bbox out] (write-derived! path bbox out nil))
  ([path bbox out date]
   (let [r (receipt! path)
         res (load-area path bbox date)]
     (io/make-parents out)
     (spit out (json/write-str (assoc res :source-receipt (str (:acq/sha256 r)))))
     (acq/adopt! {:source :derived :url (str "file://" out) :path out
                  :dataset (if (= out stuttgart-derived-path) "stuttgart-gtfs-stops" "gtfs-stops")
                  :note (str "GTFS stops in " (pr-str bbox) ", with mean weekday "
                             "07:00–19:00 headways; derived from " (:acq/path r))})
     (dissoc res :stops))))

(defn read-derived
  "The written stop table at `path`, or nil."
  [path]
  (when (.exists (io/file path))
    (let [d (json/read-str (slurp path) :key-fn keyword)]
      (update d :stops #(mapv (fn [s] (update s :routes vec)) %)))))

(defn write-stuttgart-derived!
  "The stop table over the Stuttgart bbox, out of the NVBW BW feed. One pass
   over 726 MB of `stop_times.txt`, so it is written once and read from
   `stuttgart-derived-path` afterwards."
  []
  (write-derived! stuttgart-path (expand-bbox stuttgart-bbox 300.0) stuttgart-derived-path
                  stuttgart-weekday-date))

(defn stops-for-stuttgart
  "Stuttgart's stop rows, from the derived table when it is there and from the
   feed itself when it is not."
  []
  (or (:stops (read-derived stuttgart-derived-path))
      (:stops (load-area stuttgart-path (expand-bbox stuttgart-bbox 300.0) stuttgart-weekday-date))))
