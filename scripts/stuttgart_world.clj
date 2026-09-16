;; Build the Stuttgart world's inputs end to end, from aggregates only.
;;
;;   clojure -M scripts/stuttgart_world.clj            ;; everything
;;   clojure -M scripts/stuttgart_world.clj persons    ;; one stage
;;
;; (plain -M, not -M:dev: the :dev alias's :main-opts start an nREPL server)
;;
;; Stages, in order:
;;   receipts  adopt! every raw download (sha256 beside the file)
;;   cache     read the Zensus cells and the Stuttgart areas out of the store
;;             once, into data/derived/stuttgart_{cells,areas_store}.*
;;   persons   synth_stuttgart_persons.edn + stuttgart_cell_centroids.jsonl
;;   firms     data/derived/firms/stuttgart-2025.json (+ per-Stadtteil summary)
;;   commute   stuttgart_commute_shares.edn from the BA Gemeindedaten
;;   validate  synthetic totals vs the resident register, per Stadtbezirk and
;;             per age band
;;
;; `cache` needs a Datahike connection; the rest is files only.
(require '[city.synth.stuttgart :as ss]
         '[city.synth.stuttgart-firms :as sf]
         '[clojure.pprint :refer [pprint]])

(defn- connect! []
  (require 'city.store 'datahike.api)
  (let [conn (deref (resolve 'city.store/conn))]
    (when-not (deref conn)
      (reset! conn ((resolve 'datahike.api/connect) ((resolve 'city.store/config)))))))

(def stages
  {"receipts" (fn [] (pprint (ss/adopt-raw!)))
   "cache" (fn [] (connect!) (pprint (ss/cache-areas!)) (pprint (ss/cache-cells!)))
   "persons" (fn [] (pprint (dissoc (ss/synthesize!) :by-stadtteil :by-stadtbezirk :by-agegrp)))
   "firms" (fn [] (pprint (sf/cache-places!)) (pprint (sf/build!)))
   "commute" (fn [] (pprint (sf/commute-shares!)))
   "validate" (fn [] (pprint (ss/validate (ss/synthesize!))))})

(let [args (seq *command-line-args*)]
  (doseq [s (or args ["receipts" "cache" "persons" "firms" "commute" "validate"])]
    (println "\n====" s)
    (if-let [f (stages s)] (f) (println "unknown stage" s))))
