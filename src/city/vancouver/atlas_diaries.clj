(ns city.vancouver.atlas-diaries
  "Export anonymous time-use chains for Vancouver's weekday model and its comparisons."
  (:require [city.synth.timeuse :as timeuse]
            [city.vancouver.shopping :as shopping]
            [city.vancouver.weekday :as weekday]
            [clojure.data.json :as json]))

(defn- export-diary [diary]
  {:weight (:weight diary)
   :episodes (mapv (juxt :start :dur :act :loc) (:chain diary))
   :goods (keep-indexed (fn [i e] (when (= :goods-at-store (shopping/category e)) i)) (:chain diary))})

(defn- outdoor-activity [pools sports-code]
  (vec (for [[age pool] pools
             diary (concat (:fit pool) (:holdout pool))
             :let [bouts (into [] (keep (fn [{:keys [sports-detail loc start dur]}]
                                         (when (and (= sports-code sports-detail) (#{:outdoors :neighbourhood} loc))
                                           [start dur])))
                               (:chain diary))]
             :when (seq bouts)]
         {:age age :weight (:weight diary) :bouts bouts})))

(defn -main [root & [purpose]]
  (let [provinces (when (not= purpose "--outdoor-sports") #{59})
        pools (weekday/split-diaries (timeuse/load-diaries :project-root root :provinces provinces))
        attendance? (= purpose "--attendance")
        income? (= purpose "--income-comparison")
        comparison? (= purpose "--shopping-comparison")]
    (json/write
     (if-let [sports-code ({"--outdoor-exercise" 1001 "--outdoor-sports" 1004 "--outdoor-sports-bc" 1004} purpose)]
       (outdoor-activity pools sports-code)
       (vec (concat
           (for [[age pool] pools
                 split (if (or attendance? income? comparison?) [:fit :holdout] [:fit])
                 diary (get pool split)]
             (cond-> (assoc (export-diary diary) :age age :role (first (:type diary)))
               attendance? (assoc :split split :enrolledAfterHighSchool (:postsecondary-proxy? diary))
               income? (assoc :split split :incomeBand (:income-band diary)
                              :familyIncomeBand (:family-income-band diary)
                              :householdSize (:household-size diary))
               comparison? (assoc :pool (if (= split :fit) "bcFit" "bcHoldout"))))
           (when comparison?
             (for [[_ diary] (sort-by key (timeuse/load-diaries :project-root root
                                           :provinces #{10 11 12 13 24 35 46 47 48}))]
               (assoc (export-diary (update diary :chain #(sort-by :start %))) :pool "otherUrban"))))))
     *out*)))
