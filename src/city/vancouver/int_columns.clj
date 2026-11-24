(ns city.vancouver.int-columns
  (:require [clojure.java.io :as io])
  (:import [java.nio ByteBuffer ByteOrder]
           [java.nio.file Files]))

(defn read-ints [dir id]
  (let [bytes (Files/readAllBytes (.toPath (io/file dir (str (name id) ".i32"))))
        data (int-array (quot (alength bytes) 4))]
    (.get (.asIntBuffer (.order (ByteBuffer/wrap bytes) ByteOrder/LITTLE_ENDIAN)) data)
    data))

(defn write-ints [file ^ints data]
  (let [buf (.order (ByteBuffer/allocate (* 4 (alength data))) ByteOrder/LITTLE_ENDIAN)]
    (.put (.asIntBuffer buf) data)
    (with-open [out (io/output-stream file)] (.write out (.array buf)))))
