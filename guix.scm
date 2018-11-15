;;; git-to-jira-links --- Adding git commits referencing JIRA issues as links to the issues
;;; 
;;; Copyright © 2018 Arne Babenhauserheide <arne.babenhauserheide@disy.net>
;;;
;;; Licensed under the Apache License, Version 2.0 (the "License");
;;; you may not use this file except in compliance with the License.
;;; You may obtain a copy of the License at
;;; 
;;;     http://www.apache.org/licenses/LICENSE-2.0
;;; 
;;; Unless required by applicable law or agreed to in writing, software
;;; distributed under the License is distributed on an "AS IS" BASIS,
;;; WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
;;; See the License for the specific language governing permissions and
;;; limitations under the License.
;;; 
;;; use this file to get all dependencies via guix environment -l guix.scm

(use-modules
 (gnu packages python)
 (gnu packages version-control)
 (gnu packages gnupg)
 (guix build-system python)
 (guix gexp)
 (guix git-download)
 ((guix licenses) #:prefix license: #:select (asl2.0))
 (guix packages)
)

(define %source-dir (dirname (current-filename)))

(define-public git-to-jira-links
  (package
    (name "git-to-jira-links")
    (version "0.1")
    (source (local-file %source-dir
                        #:recursive? #t
                        #:select? (git-predicate %source-dir)))
    (build-system python-build-system)
    (native-inputs
     `(("python-dulwich" ,python-dulwich)
       ("git" ,git)
       ("python-gpg" ,python-gpg)))
    (home-page "https://github.com/DisyInformationssysteme/git-to-jira-links")
    (synopsis "Adding git commits referencing JIRA issues as links to the issues")
    (description "Adding git commits referencing JIRA issues as links to the issues.")
    ;; Can be used with either license.
    (license license:asl2.0)))

;; return the defined package for guix environment
git-to-jira-links
