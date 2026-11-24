(ns city.artifact
  "Content-addressed release files."
  (:require [clojure.java.io :as io])
  (:import [java.io OutputStream]
           [java.nio.file Files StandardCopyOption]
           [java.security DigestInputStream MessageDigest]
           [java.util HexFormat]))

(defn sha256 [^bytes bytes]
  (.formatHex (HexFormat/of) (.digest (MessageDigest/getInstance "SHA-256") bytes)))

(defn sha256-file
  "Stream a file through SHA-256 without loading the payload into heap."
  [file]
  (let [digest (MessageDigest/getInstance "SHA-256")]
    (with-open [in (DigestInputStream. (io/input-stream file) digest)]
      (.transferTo in (OutputStream/nullOutputStream)))
    (.formatHex (HexFormat/of) (.digest digest))))

(defn publish-staged-file!
  "Atomically install a complete file staged on the destination filesystem."
  [source dest]
  (let [staged (io/file source)]
    (.setReadable staged true false)
    (Files/move (.toPath staged) (.toPath (io/file dest))
                (into-array StandardCopyOption [StandardCopyOption/ATOMIC_MOVE StandardCopyOption/REPLACE_EXISTING]))))

(defn publish-file! [file ^bytes bytes]
  (io/make-parents file)
  (let [path (.toPath (io/file file))
        temp (Files/createTempFile (.getParent path) ".publishing-" ".tmp"
                                   (make-array java.nio.file.attribute.FileAttribute 0))]
    (try
      (with-open [out (io/output-stream (.toFile temp))] (.write out bytes))
      (publish-staged-file! (.toFile temp) file)
      (finally (Files/deleteIfExists temp)))))
