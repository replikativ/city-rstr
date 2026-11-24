(ns city.trajectory
  "Publish clocked, individually identified street journeys for the shared explorer."
  (:require [city.artifact :as artifact]
            [city.sim.network :as network]
            [city.street-replay :as stuttgart]
            [city.vancouver.diary-clock :as clock]
            [city.vancouver.roster :as roster]
            [clojure.data.json :as json]
            [clojure.java.io :as io])
  (:import [java.io File Writer]
           [java.lang ProcessBuilder$Redirect]
           [java.nio.file Files]
           [java.util ArrayList]))

(defn- read-json [file]
  (with-open [reader (io/reader file)]
    (json/read reader :key-fn keyword)))

(defn- check-exit! [^Process child stage]
  (let [status (.waitFor child)]
    (when-not (zero? status)
      (throw (ex-info "Trajectory build failed" {:stage stage :exit status})))))

(defn- shard! [dir write-json!]
  ;; Existing content addresses use ECMAScript's shortest number spelling.
  ;; Feed one shard at a time through its original encoder for byte-identical releases.
  (let [file (File/createTempFile ".encoding-" ".json" dir)
        cmd ["node" "-e" "process.stdout.write(JSON.stringify(JSON.parse(require('node:fs').readFileSync(0,'utf8'))))"]
        child (.start (doto (ProcessBuilder. ^java.util.List cmd)
                        (.redirectError ProcessBuilder$Redirect/INHERIT) (.redirectOutput file)))]
    (try
      (with-open [writer (io/writer (.getOutputStream child))] (write-json! writer))
      (check-exit! child :json-encoding)
      (let [digest (artifact/sha256-file file)]
        (artifact/publish-staged-file! file (io/file dir (str digest ".json")))
        digest)
      (finally (.destroy child) (Files/deleteIfExists (.toPath file))))))

(defn- geo-shard! [dir features]
  (shard! dir #(json/write {:type "FeatureCollection" :features features} %)))

(defn- road-features [groups]
  (for [[kind lines] groups]
    {:type "Feature" :properties {:kind (name kind)}
     :geometry {:type "MultiLineString" :coordinates lines}}))

(defn- stuttgart-roads [osm]
  (let [round-coordinate (fn [v] (/ (Math/round (* (double v) 1e6)) 1e6))]
    (network/stream-elements!
     osm (fn [groups {:keys [tags geometry]}]
           (let [{:keys [highway area bridge]} tags]
             (if (and (next geometry) highway (not= area "yes") (not (network/excluded-highways highway)))
               (update groups (cond (and bridge (not= bridge "no")) :bridge
                                    (re-find #"^(primary|secondary|trunk|motorway)" highway) :arterial
                                    :else :street)
                       conj (mapv (fn [{:keys [lon lat]}] [(round-coordinate lon) (round-coordinate lat)]) geometry))
               groups)))
     {:street [] :arterial [] :bridge []})))

(defn- commuter-origins [file]
  (with-open [reader (io/reader file)]
    (let [rows (map #(json/read-str % :key-fn keyword) (line-seq reader))
          origins (into {} (map (juxt :ags identity)) rows)
          areas (read-json (io/resource "city/stuttgart-municipalities.json"))]
      (for [{:keys [properties geometry]} (:features areas)
            :let [origin (origins (:ags properties))] :when origin]
        {:type "Feature" :geometry geometry :properties (select-keys origin [:name :flow])}))))

(defn- hour [minute] (long (Math/floor (/ (double minute) 60.0))))

(defn- record! [hours periodic? {:keys [times agent] :as leg}]
  (let [start (hour (first times)) end (long (Math/ceil (/ (double (peek times)) 60.0)))
        ;; This permutation keeps the rendered sample stable across hours and limits.
        rank (bit-and (* (long agent) 2654435761) 0xffffffff)
        encode (fn [row] (json/write-str row :escape-unicode false :escape-slash false))
        plain (delay (encode leg))]
    (doseq [h (range start end) :when (or periodic? (<= 0 h 23))]
      (let [offset (* 1440 (Math/floorDiv (long h) (long 24)))
            row (if (and periodic? (not (zero? offset)))
                  (encode (assoc leg :times (mapv #(- % offset) times))) @plain)]
        (.add ^ArrayList (hours (mod h 24)) [rank row])))))

(defn- write-hour! [writer rows]
  (let [^Writer out writer]
    (.write out "[")
    (doseq [[idx [_ row]] (map-indexed vector rows)]
      (when (pos? idx) (.write out ","))
      (.write out ^String row))
    (.write out "]")))

(defn- hour-shards! [dir hours sort-by-roster?]
  (mapv (fn [rows]
          (let [ordered (if sort-by-roster? (sort-by first rows) rows)]
            (shard! dir #(write-hour! % ordered))))
        hours))

(defn- resident-jobs [day atlas places population]
  (let [das (:das day)
        population-of #(get-in atlas [:das (keyword %) :population])
        offsets (roster/area-offsets das population-of)
        templates (mapv
                   (fn [template donor]
                     (filterv (fn [[start duration mode]]
                                (and (not= mode "stop")
                                     (every? (fn [[other n _ label]]
                                               (or (>= other (+ start duration)) (<= (+ other n) start) (= mode label)))
                                             (:episodes donor))))
                              (:parts template)))
                   (:templates day) (:templates atlas))]
    (when-not (= population (reduce + 0 (map population-of das)))
      (throw (ex-info "Trace IDs disagree with resident population" {:population population})))
    (for [[district person template plan] (:sample day)
          [start duration mode a b] (templates template)
          :let [from (get places (get plan a)) to (get places (get plan b))]
          :when (and from to)]
      {:id (str (das district) "/" person) :agent (+ (offsets district) person)
       :mode mode :purpose (get-in day [:templates template :slots b])
       :request [(hour start) mode from to start duration false]})))

(def ^:private commuter-modes
  {"Car driver" "car-driver" "Car passenger" "car-passenger" "Taxi" "taxi" "Ride-hail" "ridehail" "Walking" "walk"})

(defn- commuter-jobs [folder run places]
  (when folder
    (let [report (read-json (io/file folder "commuters.json"))
          ordinal (volatile! -1)
          jobs (vec
                (for [group (sort (map name (keys (:groups report))))
                      :let [{:keys [people homePoints]} (read-json (io/file folder (str group ".json")))]
                      [i [h j _ _ mode start duration span attending]] (map-indexed vector people)
                      :when (= 1 attending)
                      :let [n (vswap! ordinal inc) label (nth (:modes report) mode)]
                      :when (and (zero? (mod n 32)) (commuter-modes label))
                      :let [home (homePoints h) work (places j)]
                      [from to leave purpose] [[home work start "inbound work"]
                                               [work home (+ start duration span) "return home"]]]
                  {:id (str "incoming/" group "/" i) :agent (+ (:population run) n)
                   :mode label :purpose purpose
                   :request [(hour leave) (commuter-modes label) from to leave duration true]}))]
      (when-not (= (inc @ordinal) (:inbound run))
        (throw (ex-info "Regional commuter IDs disagree with the roster" {:workers folder})))
      jobs)))

(defn- leg-times [offsets minutes begin duration agent run]
  (let [times (mapv #(+ begin (* (/ (double %) (double minutes)) duration)) offsets)]
    (if (:regionalWorkers run)
      (let [shift (clock/phase agent)
            arrival (peek times) departure (first times)
            shifted (fn [t] (if (and (< agent (:population run)) (zero? (mod (- t 240) 1440))) t (+ t shift)))
            a (shifted departure) b (shifted arrival)]
        (mapv #(+ a (/ (* (- % departure) (- b a)) (- arrival departure))) times))
      times)))

(defn- record-route! [hours run {:keys [id agent mode purpose request sample-order]} path offsets minutes]
  (let [[_ _ _ _ start duration] request
        leg {:id id :agent agent :mode mode :purpose purpose :path path}
        timed (fn [t] (assoc leg :times (leg-times offsets minutes t duration agent run)))]
    (if (:regionalWorkers run)
      (record! hours true (timed (mod start 1440)))
      ;; The municipal releases retain their published sample order. Their
      ;; midnight clock wraps the start before adding the route offsets.
      (doseq [h (range (hour start) (long (Math/ceil (/ (+ start duration) 60.0))))
              :let [wrapped (- start (* 1440 (quot h 24)))]]
        (.add ^ArrayList (hours (mod h 24))
              [sample-order (json/write-str (timed wrapped) :escape-unicode false :escape-slash false)])))))

(defn- vancouver-traces! [run inputs hours]
  (let [folder (:day inputs)
        day (read-json (io/file folder "day.json"))
        places (read-json (io/file folder "places.json"))
        atlas (read-json (io/file (:roster inputs) "atlas.json"))
        cache (:route-files inputs)
        ;; Stable local-clock order also resolves ties for two legs of the same person.
        jobs (vec (sort-by #(mod (first (:request %)) 24)
                           (concat (map-indexed #(assoc %2 :sample-order %1)
                                                (resident-jobs day atlas places (:population run)))
                                   (commuter-jobs (:incoming-workers inputs) run places))))
        source (io/file (io/resource "city/trajectory.clj"))
        adapter (io/file (.getParentFile (.getParentFile (.getParentFile source))) "scripts/vancouver_route_geometry.mjs")
        command ["node" (str adapter) (str cache) (str (:roads inputs)) (str (:drive-profile inputs))]
        child (.start (doto (ProcessBuilder. ^java.util.List command)
                        (.redirectError ProcessBuilder$Redirect/INHERIT)))]
    (try
      (with-open [out (io/writer (.getOutputStream child))] (json/write (map :request jobs) out))
      (with-open [in (io/reader (.getInputStream child))]
        (doseq [line (line-seq in)]
          (let [[i path offsets minutes] (json/read-str line)]
            (record-route! hours run (jobs i) path offsets minutes))))
      (check-exit! child :route-geometry)
      (finally (.destroy child)))))

(defn publish! [root {:keys [city release] :as run} inputs]
  (let [dir (io/file root "overview")
        hours (mapv (fn [_] (ArrayList.)) (range 24))]
    (.mkdirs dir)
    (let [index
          (case city
            "stuttgart"
            (let [osm (get-in inputs [:archive-files :roads])
                  timing (stuttgart/emit-traces! osm (get-in inputs [:release-files :trips.json]) #(record! hours false %))]
              {:release release :hours (hour-shards! dir hours false) :timing timing
               :roads (geo-shard! dir (road-features (stuttgart-roads osm)))
               :origins (geo-shard! dir (commuter-origins (get-in inputs [:archive-files :commuter-origins])))})
            "vancouver"
            (do
              (vancouver-traces! run inputs hours)
              {:release release :hours (hour-shards! dir hours true)
               :roads (geo-shard! dir (road-features (:roads (read-json (io/file (:roster inputs) "basemap.json")))))}))]
      (artifact/publish-file! (io/file dir (str release "-traces.json")) (.getBytes (json/write-str index) "UTF-8"))
      index)))
