(ns city.build
  "Build the explorer products from one city's versioned producer inputs."
  (:require [city.artifact :as artifact]
            [city.build-inputs :as inputs]
            [city.replay :as replay]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str]
            [clojure.walk :as walk])
  (:import [java.io File]
           [java.nio.file Files FileVisitOption Path StandardCopyOption]
           [java.nio.file.attribute FileAttribute]
           [java.util.zip GZIPInputStream]))

(defn- read-json [f]
  (with-open [r (io/reader f)] (json/read r :key-fn keyword)))

(defn- selected [root city release]
  (when (and city release)
    (throw (ex-info "Choose a city or an exact release" {})))
  (let [city (some-> city name)
        catalog (read-json (io/file root "runs/current.json"))
        rows (cond release (filter #(= release (:release %)) catalog)
                   city (when-let [preferred (or (replay/preferred-run catalog city "region")
                                                 (replay/preferred-run catalog city "city"))]
                          [preferred])
                   :else catalog)]
    (when (or (empty? rows) (and (or release city) (not= 1 (count rows))))
      (throw (ex-info "Unknown or ambiguous weekday selection" {:city city :release release})))
    (mapv (fn [{:keys [release] :as entry}]
            (when-not (and (string? release) (re-matches #"[a-f0-9]{64}" release))
              (throw (ex-info "Invalid catalogue release" {:release release})))
            (let [run (read-json (io/file root "runs" (str release ".json")))]
              (when-not (= entry (select-keys run (keys entry)))
                (throw (ex-info "Catalogue and run manifest disagree" {:release release})))
              run))
          rows)))

(defn- inventory [file]
  (with-open [r (io/reader (GZIPInputStream. (io/input-stream file)))]
    (into {} (keep #(when-let [[_ hash name] (re-matches #"([a-f0-9]{64})  data/overview/([^/]+)" %)]
                      [name hash])) (line-seq r))))

(defn- paths [^Path root]
  (with-open [s (Files/walk root (make-array FileVisitOption 0))]
    (vec (iterator-seq (.iterator s)))))

(def ^:private attrs (make-array FileAttribute 0))

(defn- link! [dest source]
  (Files/createSymbolicLink (.toPath (io/file dest)) (.toPath (.getCanonicalFile (io/file source))) attrs))

(defn- stuttgart-day! [work stage archive release inputs]
  ;; Stuttgart's historical world builder uses cwd-relative paths and can write
  ;; derived caches. Expose only the recipe inputs in its private working tree.
  (let [archive-path (.toPath archive)
        cp (str/join File/pathSeparator
                     (map #(.getCanonicalPath (io/file %))
                          (str/split (System/getProperty "java.class.path")
                                     (re-pattern (java.util.regex.Pattern/quote File/pathSeparator)))))]
    (doseq [^File source (vals (:archive-files inputs))]
      (let [relative (.relativize archive-path (.toPath source))
            target (.toFile (.resolve (.toPath work) relative))]
        (io/make-parents target)
        (if (.startsWith relative "data/derived")
          (Files/copy (.toPath source) (.toPath target) (make-array StandardCopyOption 0))
          (link! target source))))
    (let [proc (.start (doto (ProcessBuilder.
                              [(str (System/getProperty "java.home") "/bin/java") "-Xmx5g" "-XX:ActiveProcessorCount=5"
                               "--add-modules=jdk.incubator.vector" "--enable-native-access=ALL-UNNAMED"
                               "-cp" cp "clojure.main" "-m" "city.overview" (str stage) release])
                         (.directory work) (.inheritIO)))]
      (when-not (zero? (.waitFor proc))
        (throw (ex-info "Stuttgart weekday preparation failed" {:release release}))))))

(defn- install! [stage dest release expected]
  (let [dir (io/file stage "overview")
        pointers (mapv #(io/file dir (str release % ".json")) ["" "-cases" "-traces"])
        [day scenarios traces :as indexes] (mapv read-json pointers)
        json-ids (concat [(:scene day) (:cases scenarios) (:roads traces)]
                         (when (:origins traces) [(:origins traces)]) (:hours traces))
        packs [(:agents day) (:schedules day)]]
    (when-not (and (every? #(= release (:release %)) indexes)
                   (= 24 (count (:hours traces)))
                   (every? #(and (string? %) (re-matches #"[a-f0-9]{64}" %)) (concat json-ids packs)))
      (throw (ex-info "Incomplete weekday build" {:release release})))
    (let [shards (distinct (concat (map #(io/file dir (str % ".json")) json-ids)
                                   (map #(io/file dir (str % ".gz")) packs)))
          files (concat shards pointers)]
      ;; Check the entire closure before moving any pointer. On a retry only
      ;; complete content-addressed data can become visible through an index.
      (doseq [^File file files]
        (let [name (.getName file)
              actual (artifact/sha256-file file)]
          (when (and (not (some #{file} pointers)) (not (str/starts-with? name actual)))
            (throw (ex-info "Corrupt weekday shard" {:release release :file name})))
          (when (and expected (not= actual (get expected name)))
            (throw (ex-info "Rebuild differs from reviewed data" {:file name :release release :actual actual
                                                                  :expected (get expected name)})))))
      (doseq [^File file files
              :let [target (io/file dest (.getName file))]
              :when (or (not (.isFile target))
                        (not= -1 (Files/mismatch (.toPath file) (.toPath target))))]
        (artifact/publish-staged-file! file target))
      {:release release :files (count files)})))

(defn build!
  "Rebuild from the producer datasets. Select :city or :release, or omit both
  for the catalogue. :describe returns validated inputs without building.
  :verify checks staged output against the reviewed inventory before installation."
  [{:keys [data archive release city describe verify output]
    :or {data "public/data" archive "../Simulations/city"}}]
  (let [root (.getCanonicalFile (io/file data))
        archive (.getCanonicalFile (io/file archive))
        expected (when verify (inventory "deploy/weekday-data.sha256.gz"))]
    (mapv
     (fn [{:keys [release city] :as run}]
       (let [inputs (inputs/resolve-inputs root archive run {:verify-sources? (boolean verify)})]
         (if describe
           {:release release :city city :inputs inputs}
           (let [dest (.getCanonicalFile (if output (io/file output) (io/file root "overview")))
                 _ (.mkdirs dest)
                 temp (Files/createTempDirectory (.toPath dest) ".weekday-" attrs)
                 work (.toFile temp)
                 stage (io/file work "producer")]
             (try
               (.mkdirs stage)
               (doseq [name ["runs" city]] (link! (io/file stage name) (io/file root name)))
               (println "Preparing schedules and scenarios for" city release)
               (if (= city "stuttgart")
                 (stuttgart-day! work stage archive release inputs)
                 ((requiring-resolve 'city.overview/publish-day!) stage run inputs))
               (println "Publishing hourly trajectories for" city release)
               ((requiring-resolve 'city.trajectory/publish!) stage run inputs)
               (install! stage dest release expected)
               (finally
                 (doseq [^Path p (reverse (paths temp))] (Files/deleteIfExists p))))))))
     (selected root city release))))

(defn -main [& args]
  (let [options (loop [[k v & more :as args] args result {}]
                  (cond
                    (empty? args) result
                    (#{"--verify" "--describe"} k) (recur (next args) (assoc result (keyword (subs k 2)) true))
                    (and (#{"--data" "--archive" "--output" "--release" "--city"} k) v (not (str/starts-with? v "--")))
                    (recur more (assoc result (keyword (subs k 2)) v))
                    :else (throw (ex-info "Expected --city NAME, --release ID, --data DIR, --archive DIR, --output DIR, --describe or --verify"
                                          {:argument k}))))]
    (doseq [result (build! options)]
      (prn (walk/postwalk #(if (instance? File %) (.getPath ^File %) %) result)))))
