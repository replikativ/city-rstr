(ns city.intake.stuttgart-counts
  "Observed count targets for the Stuttgart world.

   **Bicycles.** Mobidata BW republishes the Baden-Württemberg Eco-Counter
   network as one gzipped CSV per month of *hourly* values
   (`mobidata-bw.de/dataset/eco-counter-fahrradzahler` →
   `daten/eco-counter/v2/fahrradzaehler_stundenwerten_<yyyymm>.csv.gz`, dl-de/by-2.0).
   Nineteen of its permanent counters stand inside the Stuttgart bbox: a fixed
   site, a full hourly profile, and a count of one mode only. It runs every day
   of the year, so the target is a *mean weekday* and not a single
   observation.

   **Pedestrians.** hystreet's free ranking page carries monthly pedestrian
   totals for six Stuttgart locations, three of them on Königstraße
   (`counts_hystreet_ranking_<yyyy-mm>_public.json`). A monthly total is a much
   weaker target than an hourly profile — it cannot say anything about shape —
   but Königstraße is the one street in the city whose footfall is measured at
   all, so it is worth the one number it gives. hystreet's terms do not allow
   republishing its counts, so they are read for a comparison only and are not
   part of the published run (see DATA.md)."
  (:require [city.intake.core :as acq]
            [clojure.data.json :as json]
            [clojure.java.io :as io]
            [clojure.string :as str])
  (:import [java.io BufferedReader InputStreamReader]
           [java.util.zip GZIPInputStream]))

;; ---- Eco-Counter hourly bicycle counts -------------------------------------------------------

(def eco-counter-url-pattern
  "https://mobidata-bw.de/daten/eco-counter/v2/fahrradzaehler_stundenwerten_%s.csv.gz")

(defn eco-counter-path [yyyymm]
  (format "data/raw/probes/counts_mobidata_eco_counter_stundenwerte_%s.csv.gz" yyyymm))

(def stuttgart-bbox
  "The City of Stuttgart, same rectangle as the world's transit and street
   pulls. The BW file is state-wide (Mannheim, Freiburg, Tübingen …); this is
   what makes it a Stuttgart target."
  {:west 9.038 :south 48.69 :east 9.315 :north 48.87})

(def stuttgart-domain
  "Eco-Counter publishes by *operator domain*, and a rectangle over Stuttgart
   also catches the Rems-Murr-Kreis counters in Fellbach and Waiblingen and a
   Landkreis Böblingen one in Waldenbuch — counters on roads the Stuttgart
   world does not contain. The city's own eighteen counters are exactly the
   rows of this domain."
  "Landeshauptstadt Stuttgart")

(def bw-holidays-2026
  "Public holidays in Baden-Württemberg that fall on a Mon–Fri in 2026. A
   holiday is not a weekday for this target: Fronleichnam empties the commute
   peak and fills the afternoon, which is exactly the shape being compared."
  #{"2026-01-01" "2026-01-06" "2026-04-03" "2026-04-06" "2026-05-01"
    "2026-05-14" "2026-05-25" "2026-06-04" "2026-10-03" "2026-11-01"
    "2026-12-25"})

(defn- split-csv
  "One CSV row → fields, honouring double quotes (a counter site can carry a
   comma in its name)."
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

(defn- parse-num [s] (try (Double/parseDouble (str/trim s)) (catch Exception _ nil)))

(defn- in-bbox? [{:keys [west south east north]} lon lat]
  (and lon lat (<= (double west) (double lon) (double east)) (<= (double south) (double lat) (double north))))

(defn- rows!
  "Stream the gzipped monthly CSV, calling `(f row)` for every data line whose
   site is inside `bbox`. Never holds the file: 24 MB uncompressed, 117k rows,
   and there is no reason for either to be a Clojure value."
  [path bbox f]
  (with-open [rd (BufferedReader. (InputStreamReader. (GZIPInputStream. (io/input-stream path)) "UTF-8") (int 1048576))]
    (let [ix (into {} (map-indexed (fn [i c] [(str/replace (str/trim c) "﻿" "") i]) (split-csv (.readLine rd))))
          g (fn [fields k] (str/trim (nth fields (ix k) "")))]
      (loop [n 0 kept 0]
        (if-let [l (.readLine rd)]
          (let [fields (split-csv l)
                lon (parse-num (g fields "longitude")) lat (parse-num (g fields "latitude"))]
            (if (in-bbox? bbox lon lat)
              (do (f {:site (g fields "counter_site") :site-id (g fields "counter_site_id")
                      :domain (g fields "domain_name")
                      :lon lon :lat lat
                      :ts (g fields "iso_timestamp")
                      :in (parse-num (g fields "channels_in")) :out (parse-num (g fields "channels_out"))
                      :all (parse-num (g fields "channels_all"))})
                  (recur (inc n) (inc kept)))
              (recur (inc n) kept)))
          {:rows n :kept kept})))))

(defn bike-counts
  "Mean weekday hourly bicycle counts per Stuttgart Eco-Counter site, for one
   month of the Mobidata BW hourly file.

   → `{:month :path :sites [{:key :site-id :lon :lat :domain :days :total
   :hours {h mean}}] :weekday-dates [...]}`

   A site's hourly value is `channels_all` (both directions past the counter)
   and falls back to `in + out` when the file leaves `all` at `na`. Only Mon–Fri
   are kept, and `bw-holidays-2026` are dropped from those. The mean is over
   the days the site actually reported, not over the calendar: a counter that
   was down for a fortnight contributes the fortnight it was up, and `:days`
   says how many that was."
  [& {:keys [yyyymm path bbox domain] :or {yyyymm "202606" domain stuttgart-domain}}]
  (let [path (or path (eco-counter-path yyyymm))
        bbox (or bbox stuttgart-bbox)
        acc (java.util.HashMap.)      ;; site-id → {:meta .. :sum double[24] :days #{}}
        dates (java.util.HashSet.)
        keep! (fn [{:keys [site site-id lon lat ts in out all] dom :domain}]
                (let [date (subs ts 0 10)
                      hour (Long/parseLong (subs ts 11 13))
                      dow (.getDayOfWeek (java.time.LocalDate/parse date))
                      weekday? (and (<= (.getValue dow) 5) (not (bw-holidays-2026 date)))
                      v (or all (when (and in out) (+ (double in) (double out))))]
                  (when (and weekday? v (or (nil? domain) (= domain dom)))
                    (.add dates date)
                    (let [e (or (.get acc site-id)
                                (let [e {:key site :site-id site-id :domain dom :lon lon :lat lat
                                         :sum (double-array 24) :n (long-array 24) :days (java.util.HashSet.)}]
                                  (.put acc site-id e) e))]
                      (aset ^doubles (:sum e) (int hour) (+ (aget ^doubles (:sum e) (int hour)) (double v)))
                      (aset ^longs (:n e) (int hour) (inc (aget ^longs (:n e) (int hour))))
                      (.add ^java.util.HashSet (:days e) date)))))
        stats (rows! path bbox keep!)]
    {:month yyyymm :path path :bbox bbox :domain domain :scanned stats
     :weekday-dates (vec (sort dates))
     :sites (vec (sort-by #(- (:total %))
                          (for [[_ e] acc
                                :let [^doubles sum (:sum e) ^longs n (:n e)
                                      hours (into {} (for [h (range 24) :when (pos? (aget n h))]
                                                       [h (/ (aget sum h) (aget n h))]))]]
                            {:key (:key e) :site-id (:site-id e) :domain (:domain e)
                             :lon (:lon e) :lat (:lat e)
                             :days (count (:days e))
                             :hours hours
                             :total (reduce + (vals hours))})))}))

(defn adopt-month!
  "Register a downloaded monthly file as a receipt."
  [yyyymm]
  (let [p (eco-counter-path yyyymm)]
    (acq/adopt! {:source :mobidata-bw :url (format eco-counter-url-pattern yyyymm) :path p
                 :dataset (str "mobidata-eco-counter-hourly-" yyyymm)
                 :note {:licence "dl-de/by-2.0" :unit "bicycles per hour per counter site"}})))

;; ---- hystreet monthly pedestrian totals ------------------------------------------------------

(def hystreet-path "data/raw/probes/counts_hystreet_ranking_2026-08_public.json")

(defn hystreet-stuttgart
  "The Stuttgart rows of hystreet's free monthly ranking page: one *monthly*
   pedestrian total per measured location. No hours, no days, no coordinates —
   the free page carries the ranking and nothing else, and the hourly series
   behind it is a paid API (from ~€700/yr). The locations' positions are the
   published street segments and are filled in here by hand."
  ([] (hystreet-stuttgart hystreet-path))
  ([path]
   (when (.exists (io/file path))
     (let [d (json/read-str (slurp path) :key-fn keyword)
           ;; the segments the three Königstraße counters sit on, read off the
           ;; hystreet location pages; only used to place the comparison, never
           ;; to weight it
           ;; the centroid of the street's own OSM geometry in
           ;; `stuttgart_highways.json` — Königstraße is 35 ways running
           ;; 48.7733–48.7826, split into equal thirds by latitude, which is
           ;; what hystreet's Süd/Mitte/Nord name. It places the comparison to
           ;; within a block; hystreet does not publish the sensor position.
           coords {"Königstraße (Süd)"    [9.17539 48.77509]
                   "Königstraße (Mitte)"  [9.17747 48.77765]
                   "Königstraße (Nord)"   [9.17976 48.77994]
                   "Schulstraße"          [9.17706 48.77579]
                   "Stiftstraße"          [9.17744 48.77648]
                   "Hirschstraße (Mitte)" [9.17695 48.77478]}]
       {:month (:month d) :year (:year d)
        :locations (vec (for [l (:topLocations d) :when (= "Stuttgart" (:cityName l))
                              :let [[lon lat] (coords (:locationName l))]]
                          {:key (:locationName l) :id (:locationId l)
                           :pedestrians-month (:pedestriansCount l)
                           :lon lon :lat lat}))}))))
