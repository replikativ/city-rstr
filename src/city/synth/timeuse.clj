(ns city.synth.timeuse
  "Statistics Canada Time Use Survey 2022 PUMF (Open Licence): diaries as
   activity chains, conditioned on person type, to drive the daily module.

   Episode file: fixed-width per the shipped Stata .dct. Main file: person
   attributes (main activity, age group, gender, diary day type, province,
   urban/rural)."
  (:require [clojure.java.io :as io]
            [clojure.string :as str]))

(def dir "data/raw/statcan/timeuse")
(def episode-txt (str dir "/Data_Données/TU_ET_2022_Episode_PUMF.txt"))
(def main-txt (str dir "/Data_Données/TU_ET_2022_Main-Principal_PUMF.txt"))
(def episode-dct (str dir "/Layout_MisEnPages/STATA/TU_ET_2022_Episode_PUMF.dct"))
(def main-dct (str dir "/Layout_MisEnPages/STATA/TU_ET_2022_Main_PUMF.dct"))

(defn- layout
  "Parse a Stata infix dictionary → [[name start end] ...] (1-based inclusive)."
  [dct]
  (->> (str/split-lines (slurp dct))
       (keep #(re-find #"^\s*(?:double|str|long|int|byte)?\s*([A-Z0-9_]+)\s+(\d+)\s*-\s*(\d+)" %))
       (mapv (fn [[_ n a b]] [(keyword n) (Long/parseLong a) (Long/parseLong b)]))))

(defn- read-fixed [txt dct wanted]
  (let [cols (filter #(wanted (first %)) (layout dct))]
    (with-open [r (io/reader txt)]
      (->> (line-seq r)
           (mapv (fn [^String line]
                   (into {} (for [[k a b] cols :when (<= b (count line))]
                              [k (str/trim (subs line (dec a) b))]))))))))

(defn- num [s] (when (and s (re-matches #"-?\d+(\.\d+)?" s)) (if (str/includes? s ".") (Double/parseDouble s) (Long/parseLong s))))

(def activity-classes
  {100 :sleep 125 :personal-care 150 :eating 200 :housework 230 :housework-occasional 260 :shopping
   300 :childcare 350 :adult-care 400 :travel 500 :paid-work 600 :study 700 :socializing 800 :helping
   900 :civic 1000 :sports 1100 :leisure-out 1200 :media 1300 :other})

(def locations
  {3300 :home 3301 :work-or-school 3302 :business 3303 :other-home 3304 :neighbourhood 3305 :outdoors
   3306 :store 3307 :culture 3308 :sports-venue 3309 :restaurant 3310 :worship 3311 :clinic 3312 :elsewhere
   3313 :car-driver 3314 :car-passenger 3315 :walk 3316 :transit 3317 :air 3318 :bike 3319 :motorcycle
   3320 :taxi 3321 :ridehail 3322 :ferry 3323 :travel-other 3399 :travel-ns})

(defn person-type
  "Main-file record → type key used to condition chains."
  [{:keys [MRW_05C AGEGR10 GENDER2]}]
  (let [act (case (num MRW_05C) 1 :worker 2 :student 3 :home 4 :retired :other)
        age (case (num AGEGR10) 1 :a15-24 2 :a25-34 3 :a35-44 4 :a45-54 5 :a55-64 6 :a65-74 7 :a75+ :na)]
    [act age (case (num GENDER2) 1 :men 2 :women :na)]))

(defn load-diaries
  "Weekday diaries of urban respondents in `provinces` (default BC + all, see
   :all?) → {id {:type [act age sex] :weight w :chain [{:act :loc :start :dur}...]}}"
  [& {:keys [provinces urban-only? weekday-only?] :or {provinces #{59} urban-only? true weekday-only? true}}]
  (let [mains (read-fixed main-txt main-dct #{:PUMFID :WGHT_PER :PRV :LUC_RST :MRW_05C :AGEGR10 :GENDER2 :DVTDAY :HSDSIZEC :CHH0017C})
        keep (into {} (for [m mains
                            :when (and (or (nil? provinces) (provinces (num (:PRV m))))
                                       (or (not urban-only?) (= 1 (num (:LUC_RST m))))
                                       (or (not weekday-only?) (= 1 (num (:DVTDAY m)))))]
                        [(:PUMFID m) {:type (person-type m) :weight (num (:WGHT_PER m)) :chain []}]))
        eps (read-fixed episode-txt episode-dct #{:PUMFID :ACTIVITY :LOCATION :STARTMIN :DURATION :INSTANCE})]
    (reduce (fn [acc e]
              (if-let [d (acc (:PUMFID e))]
                (assoc acc (:PUMFID e)
                       (update d :chain conj {:act (activity-classes (num (:ACTIVITY e)) :unknown)
                                              :loc (locations (num (:LOCATION e)) :unknown)
                                              :start (num (:STARTMIN e)) :dur (num (:DURATION e))}))
                acc))
            keep eps)))

(defn chains-by-type
  "Group diaries by person type; chains sorted by start minute."
  [diaries]
  (->> (vals diaries)
       (map #(update % :chain (fn [c] (vec (sort-by :start c)))))
       (group-by :type)))

(defn summary [by-type]
  (for [[t ds] (sort-by (comp - count val) by-type)]
    (let [n (count ds)
          eps (mapcat :chain ds)
          mins-at (fn [loc] (/ (reduce + (map :dur (filter #(= loc (:loc %)) eps))) (double n)))]
      {:type t :diaries n
       :min-at-work (Math/round (mins-at :work-or-school))
       :min-at-store (Math/round (mins-at :store))
       :min-at-restaurant (Math/round (mins-at :restaurant))
       :min-travel (Math/round (/ (reduce + (map :dur (filter #(= :travel (:act %)) eps))) (double n)))
       :restaurant-visit-rate (/ (count (filter #(= :restaurant (:loc %)) eps)) (double n))
       :store-visit-rate (/ (count (filter #(= :store (:loc %)) eps)) (double n))})))
