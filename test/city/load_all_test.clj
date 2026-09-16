(ns city.load-all-test
  "Every namespace under src/ compiles from a cold JVM. A namespace nothing in
   the suite requires can otherwise stay broken unnoticed."
  (:require [clojure.java.io :as io]
            [clojure.string :as str]
            [clojure.test :refer [deftest is]]))

(deftest every-namespace-loads
  (doseq [f (file-seq (io/file "src"))
          :let [path (str f)]
          :when (re-find #"\.cljc?$" path)
          :let [ns (-> path (subs 4) (str/replace #"\.cljc?$" "") (str/replace "/" ".") (str/replace "_" "-") symbol)]]
    (is (nil? (try (require ns) nil (catch Throwable t (.getMessage t)))) (str ns))))
