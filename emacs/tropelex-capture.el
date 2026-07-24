;;; tropelex-capture.el --- Capture decisions and friction signals for Tropelex -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Tropelex contributors
;; Author: Tropelex
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: tools, project-management, productivity
;; URL: https://github.com/shansimmons-eng/tropelex

;;; Commentary:

;; Capture decisions, friction signals, and session context from Emacs
;; into a Tropelex memory system.
;;
;; Setup:
;;   (require 'tropelex-capture)
;;   (setq tropelex-server-url "http://localhost:8766")
;;   (tropelex-capture-mode 1)  ; global mode - enables all hooks
;;
;; Manual commands:
;;   C-c t c  tropelex-capture-decision   -- capture a decision with context
;;   C-c t r  tropelex-capture-region     -- capture region as decision context
;;   C-c t f  tropelex-friction-scan      -- scan buffer for friction signals
;;   C-c t g  tropelex-capture-commit     -- capture current HEAD commit
;;   C-c t s  tropelex-status             -- check server connectivity
;;   C-c t p  tropelex-set-project        -- override project name
;;
;; Automatic capture (when tropelex-capture-mode is on):
;;   - Compilation errors  -->  friction scan on the compilation buffer
;;   - Rapid saves (5+ in 5s)  -->  logged as a friction/iteration signal
;;   - Git commits via magit  -->  captured as decisions (50+ char messages)
;;
;; Code context (LSP / treesit / which-function):
;;   - Captures include current function name and type when available
;;   - Uses eglot or lsp-mode for symbol info, falls back to treesit/which-function
;;   - Set tropelex-include-code-context to nil to disable

;;; Code:

(require 'json)
(require 'url)
(require 'url-http)

;; ── Customization ──────────────────────────────────────────────────────

(defgroup tropelex-capture nil
  "Capture decisions and friction signals for Tropelex."
  :group 'tools
  :prefix "tropelex-")

(defcustom tropelex-server-url "http://localhost:8766"
  "Base URL of the Tropelex API server (no trailing slash)."
  :type 'string
  :group 'tropelex-capture)

(defcustom tropelex-default-project nil
  "Default project name for capture.
When nil, auto-detects from projectile, vc-root-dir, or the
current directory name."
  :type '(choice (const :tag "Auto-detect" nil) string)
  :group 'tropelex-capture)

(defcustom tropelex-auto-commit-capture t
  "When non-nil, auto-capture decisions from magit commits.
Requires magit to be installed."
  :type 'boolean
  :group 'tropelex-capture)

(defcustom tropelex-commit-as-decision-threshold 50
  "Minimum commit message length to auto-capture as a decision.
Short messages like 'fix typo' are skipped. Set to 0 to capture all."
  :type 'integer
  :group 'tropelex-capture)

(defcustom tropelex-include-code-context t
  "When non-nil, include current function/class context in captures.
Uses LSP (eglot/lsp-mode), treesit, or which-function-mode."
  :type 'boolean
  :group 'tropelex-capture)

(defcustom tropelex-save-debounce-seconds 5
  "Window in seconds for detecting rapid save patterns.
When more than `tropelex-save-threshold' saves happen within
this window, a friction signal is posted."
  :type 'number
  :group 'tropelex-capture)

(defcustom tropelex-save-threshold 5
  "Number of rapid saves within the debounce window to trigger a signal."
  :type 'integer
  :group 'tropelex-capture)

(defcustom tropelex-max-friction-chars 48000
  "Maximum characters sent for a friction scan.
The server accepts up to 50000; this leaves headroom."
  :type 'integer
  :group 'tropelex-capture)

;; ── Internal state ─────────────────────────────────────────────────────

(defvar tropelex--last-save-time 0
  "Epoch time of the last tracked save.")

(defvar tropelex--save-count 0
  "Number of saves in the current debounce window.")

;; ── HTTP client ────────────────────────────────────────────────────────

(defun tropelex--json-encode (obj)
  "Encode OBJ to a JSON string with UTF-8 encoding."
  (encode-coding-string (json-encode obj) 'utf-8))

(defun tropelex--request (method endpoint &optional body)
  "Make a synchronous HTTP request to the Tropelex API.
METHOD is \"GET\" or \"POST\".
ENDPOINT is the path after /api (e.g. \"/health\").
BODY is a JSON-encodable alist, or nil.
Returns the parsed JSON response, or signals an error."
  (let* ((url-request-method method)
         (url-request-extra-headers '(("Content-Type" . "application/json")
                                       ("X-Tropelex-Client" . "emacs")))
         (url-request-data (when body (tropelex--json-encode body)))
         (url (concat tropelex-server-url "/api" endpoint))
         (buffer (condition-case err
                     (url-retrieve-synchronously url 'silent 'inhibit-cookies 10)
                   (error (error "Tropelex: Connection failed - %s"
                                 (error-message-string err))))))
    (unless buffer
      (error "Tropelex: No response from %s" tropelex-server-url))
    (with-current-buffer buffer
      (goto-char (point-min))
      ;; Read HTTP status
      (let ((status-line (buffer-substring-no-properties
                          (point-min) (line-end-position))))
        (re-search-forward "^$" nil t)
        (let* ((json-key-type 'symbol)
               (data (condition-case nil (json-read) (error nil)))
               (detail (when (and data (alist-get 'detail data))
                         (alist-get 'detail data))))
          ;; Check for HTTP errors
          (cond
           ((string-match "HTTP/[0-9.]+ \\([0-9]+\\)" status-line)
            (let ((code (string-to-number (match-string 1 status-line))))
              (cond
               ((>= code 400)
                (error "Tropelex %s %s: %s" method endpoint
                       (or detail (format "HTTP %d" code)))
                )
               (t data))))
           (t data)))))))

(defun tropelex--check-server ()
  "Return t if the Tropelex server is reachable."
  (condition-case nil
      (let ((data (tropelex--request "GET" "/health")))
        (and data (equal (alist-get 'status data) "ok")))
    (error nil)))

;; ── Project detection ──────────────────────────────────────────────────

(defun tropelex--detect-project ()
  "Detect the current project name.
Falls back through: custom setting, projectile, vc-root-dir,
then the current directory basename."
  (or tropelex-default-project
      (and (bound-and-true-p projectile-mode)
           (fboundp 'projectile-project-name)
           (projectile-project-name))
      (when-let* ((root (vc-root-dir))
                  (name (file-name-nondirectory (directory-file-name root))))
        (if (string= name "/") nil name))
      (let ((dir (file-name-nondirectory (directory-file-name default-directory))))
        (unless (string= dir "/") dir))))

(defun tropelex--project-slug (project)
  "Sanitize PROJECT name for use in URLs."
  (replace-regexp-in-string "[^a-zA-Z0-9_-]" "-" (or project "unknown")))

;; ── Code context (LSP / treesit / which-function) ─────────────────────

(defun tropelex--lsp-symbol-info ()
  "Get current symbol info from LSP (eglot or lsp-mode).
Returns an alist with name, kind, type, signature or nil."
  (cond
   ;; eglot (built-in Emacs 29+)
   ((and (bound-and-true-p eglot--managed-mode)
         (fboundp 'eglot--current-server))
    (when-let* ((server (eglot--current-server))
                (text-doc (eglot--TextDocumentIdentifier))
                (pos (eglot--pos-to-lsp-position)))
      (condition-case nil
          (let* ((result (jsonrpc-request server :textDocument/hover
                                         `(:textDocument ,text-doc :position ,pos)
                                         :timeout 0.5))
                 (contents (plist-get result :contents)))
            (when contents
              (let ((raw (if (stringp contents) contents
                           (plist-get contents :value))))
                (when (and raw (stringp raw) (> (length raw) 0))
                  `((kind . "symbol")
                    (detail . ,(substring raw 0 (min 200 (length raw)))))))))
        (error nil))))
   ;; lsp-mode
   ((and (bound-and-true-p lsp-mode)
         (fboundp 'lsp-request))
    (condition-case nil
        (let* ((params (lsp--text-document-position-params))
               (result (lsp-request "textDocument/hover" params))
               (contents (plist-get result :contents)))
          (when contents
            (let ((raw (if (stringp contents) contents
                         (or (plist-get contents :value) ""))))
              (when (> (length raw) 0)
                `((kind . "symbol")
                  (detail . ,(substring raw 0 (min 200 (length raw)))))))))
      (error nil)))))

(defun tropelex--treesit-function-context ()
  "Get current function/class context from treesit (Emacs 29+)."
  (when (and (fboundp 'treesit-parser-create)
             (treesit-parser-create (or (treesit-language-at (point)) major-mode)))
    (let ((node (treesit-node-at (point)))
          (names '()))
      (while node
        (let ((type (treesit-node-type node)))
          (when (member type '("function_definition" "method_definition"
                               "class_definition" "function_declaration"
                               "method_declaration" "class_declaration"
                               "function_item" "impl_item"))
            (when-let* ((name-node (treesit-node-child-by-field-name node "name"))
                        (name (treesit-node-text name-node t)))
              (push (format "%s (%s)" name type) names))))
        (setq node (treesit-node-parent node)))
      (when names
        `((kind . "scope")
          (detail . ,(string-join names " > ")))))))

(defun tropelex--which-function-context ()
  "Get current function name from `which-function-mode'."
  (when (bound-and-true-p which-function-mode)
    (when-let ((fn (which-function)))
      `((kind . "function")
        (detail . ,(if (listp fn) (string-join fn " > ") fn))))))

(defun tropelex--code-context ()
  "Get code context at point using the best available method.
Returns a context string or nil."
  (when tropelex-include-code-context
    (let ((info (or (tropelex--lsp-symbol-info)
                    (tropelex--treesit-function-context)
                    (tropelex--which-function-context))))
      (when info
        (format "Code context: %s (%s)"
                (or (alist-get 'detail info) "unknown")
                (or (alist-get 'kind info) "unknown"))))))

;; ── Decision capture ───────────────────────────────────────────────────

(defun tropelex--post-capture (project decision-text context channel)
  "Post a decision capture to Tropelex.
PROJECT, DECISION-TEXT, CONTEXT, and CHANNEL are strings.
Returns the parsed response alist."
  (tropelex--request
   "POST"
   (format "/memory/%s/slack/capture" (url-hexify-string (tropelex--project-slug project)))
   `((decision_text . ,decision-text)
     (context . ,context)
     (channel . ,channel))))

;;;###autoload
(defun tropelex-capture-decision (decision-text)
  "Capture DECISION-TEXT to the Tropelex memory for the current project.
Context is auto-populated from the current file, project, major mode,
and code context (LSP/treesit/which-function)."
  (interactive "sTropelex decision: ")
  (let* ((project (tropelex--detect-project))
         (file (buffer-file-name))
         (mode (symbol-name major-mode))
         (code-ctx (tropelex--code-context))
         (base-ctx (cond
                    (file (format "From %s in %s (%s)"
                                  (file-name-nondirectory file) project mode))
                    (t (format "From Emacs buffer %s (%s)" (buffer-name) mode))))
         (ctx (if code-ctx
                  (format "%s\n%s" base-ctx code-ctx)
                base-ctx)))
    (condition-case err
        (let ((resp (tropelex--post-capture project decision-text ctx "emacs")))
          (let ((conflicts (alist-get 'conflict_count resp)))
            (if (and conflicts (> conflicts 0))
                (message "Tropelex: Captured (%d conflict%s)"
                         conflicts (if (= conflicts 1) "" "s"))
              (message "Tropelex: Decision captured"))))
      (error (message "%s" (error-message-string err))))))

;;;###autoload
(defun tropelex-capture-region (beg end)
  "Capture the region BEG..END as decision context, then prompt for the decision.
Useful for capturing a code snippet or log output alongside a decision.
Includes code context from LSP/treesit/which-function when available."
  (interactive "r")
  (let* ((project (tropelex--detect-project))
         (file (buffer-file-name))
         (selection (buffer-substring-no-properties beg end))
         (code-ctx (tropelex--code-context))
         (base-ctx (format "Selection from %s:\n%s"
                           (if file (file-name-nondirectory file) (buffer-name))
                           (if (> (length selection) 2000)
                               (concat (substring selection 0 2000) "\n...[truncated]")
                             selection)))
         (ctx (if code-ctx
                  (format "%s\n%s" base-ctx code-ctx)
                base-ctx))
         (decision (read-string "Tropelex decision: ")))
    (when (string-empty-p decision)
      (user-error "Decision text cannot be empty"))
    (condition-case err
        (progn
          (tropelex--post-capture project decision ctx "emacs")
          (message "Tropelex: Decision captured"))
      (error (message "%s" (error-message-string err))))))

;; ── Friction scanning ──────────────────────────────────────────────────

(defun tropelex--post-friction-scan (project transcript)
  "Post a friction scan for PROJECT using TRANSCRIPT.
Returns the parsed response alist."
  (let ((truncated (if (> (length transcript) tropelex-max-friction-chars)
                       (substring transcript 0 tropelex-max-friction-chars)
                     transcript)))
    (tropelex--request
     "POST"
     (format "/memory/%s/friction/scan" (url-hexify-string (tropelex--project-slug project)))
     `((transcript . ,truncated)))))

(defun tropelex--format-friction-report (data)
  "Format a friction scan response DATA into a user-readable summary."
  (let* ((score (or (alist-get 'friction_score data) 0.0))
         (total (or (alist-get 'total_signals data) 0))
         (zones (alist-get 'zones data))
         (zone-count (length zones)))
    (format "Friction: %.0f%% | %d signal%s | %d zone%s"
            (* score 100) total (if (= total 1) "" "s")
            zone-count (if (= zone-count 1) "" "s"))))

;;;###autoload
(defun tropelex-friction-scan ()
  "Scan the current buffer for friction signals.
Sends the buffer content to Tropelex's friction miner and shows
a summary in the minibuffer.  Use with compilation, comint, or
log buffers for best results."
  (interactive)
  (let* ((project (tropelex--detect-project))
         (content (buffer-substring-no-properties (point-min) (point-max))))
    (when (< (length content) 10)
      (user-error "Buffer too short for friction scan"))
    (message "Tropelex: Scanning for friction...")
    (condition-case err
        (let ((data (tropelex--post-friction-scan project content)))
          (message "%s" (tropelex--format-friction-report data)))
      (error (message "%s" (error-message-string err))))))

(defun tropelex--compilation-finished (buffer msg)
  "Hook for `compilation-finish-functions'.
Scans BUFFER for friction when compilation exits with errors.
MSG is the compilation finish message."
  (when (and (stringp msg)
             (string-match-p "exited abnormally\\|error" msg)
             (buffer-live-p buffer))
    (let* ((project (tropelex--detect-project))
           (content (with-current-buffer buffer
                      (buffer-substring-no-properties (point-min) (point-max)))))
      (when (>= (length content) 50)
        ;; Run asynchronously in a timer so compilation-mode is not blocked
        (run-at-time 0.5 nil
                     (lambda ()
                       (condition-case nil
                           (let ((data (tropelex--post-friction-scan project content)))
                             (let ((score (or (alist-get 'friction_score data) 0.0)))
                               (when (> score 0.3)
                                 (message "Tropelex: High friction in compilation (%.0f%%)"
                                          (* score 100)))))
                         (error nil))))))))

;; ── Rapid-save tracking ────────────────────────────────────────────────

(defun tropelex--track-save ()
  "Detect rapid save patterns and post friction signals.
Bound to `after-save-hook' by `tropelex-capture-mode'."
  (let ((now (float-time)))
    ;; If the save is within the debounce window, increment counter
    (if (and tropelex--last-save-time
             (< (- now tropelex--last-save-time) tropelex-save-debounce-seconds))
        (setq tropelex--save-count (1+ tropelex--save-count))
      ;; Outside window - reset
      (setq tropelex--save-count 1))
    (setq tropelex--last-save-time now)
    ;; Fire when threshold reached
    (when (>= tropelex--save-count tropelex-save-threshold)
      (setq tropelex--save-count 0)
      (let* ((project (tropelex--detect-project))
             (file (buffer-file-name))
             (name (if file (file-name-nondirectory file) (buffer-name))))
        (run-at-time 0 nil
                     (lambda ()
                       (condition-case nil
                           (tropelex--post-capture
                            project
                            (format "Friction: rapid iteration in %s" name)
                            (format "%d rapid saves in %ss in %s"
                                    tropelex-save-threshold
                                    tropelex-save-debounce-seconds
                                    name)
                            "emacs")
                         (error nil))))))))

;; ── Status / utility ───────────────────────────────────────────────────

;;;###autoload
(defun tropelex-set-project (project)
  "Override the project name for the current Emacs session."
  (interactive
   (list (read-string "Tropelex project: "
                      (or tropelex-default-project (tropelex--detect-project)))))
  (setq-local tropelex-default-project project)
  (message "Tropelex project set to: %s" project))

;;;###autoload
(defun tropelex-status ()
  "Check connectivity to the Tropelex server and display status."
  (interactive)
  (let ((project (tropelex--detect-project)))
    (message "Project: %s | Server: %s | %s"
             (or project "(none)")
             tropelex-server-url
             (if (tropelex--check-server)
                 "Connected"
               "UNREACHABLE - is the server running?"))))

;; ── Magit integration ──────────────────────────────────────────────────

(defun tropelex--magit-commit-msg ()
  "Get the last commit message via git."
  (string-trim
   (with-output-to-string
     (with-current-buffer standard-output
       (call-process "git" nil t nil "log" "-1" "--format=%s%n%n%b")))))

(defun tropelex--magit-commit-diff ()
  "Get the last commit's diffstat (abbreviated for context)."
  (string-trim
   (with-output-to-string
     (with-current-buffer standard-output
       (call-process "git" nil t nil "diff-tree" "--no-commit-id" "--stat" "HEAD")))))

(defun tropelex--magit-capture-commit ()
  "Capture the last git commit as a Tropelex decision.
Called automatically after magit-commit when `tropelex-auto-commit-capture' is non-nil."
  (let* ((project (tropelex--detect-project))
         (msg (tropelex--magit-commit-msg))
         (diffstat (tropelex--magit-commit-diff))
         (subject (car (split-string msg "\n" t))))
    ;; Skip short/trivial commits
    (when (and project
               (>= (length subject) tropelex-commit-as-decision-threshold))
      (let ((context (format "Git commit:\n%s\n\nDiffstat:\n%s" msg diffstat)))
        (tropelex--post-capture project subject context "magit")))))

;;;###autoload
(defun tropelex-capture-commit ()
  "Manually capture the current HEAD commit as a Tropelex decision."
  (interactive)
  (let* ((project (tropelex--detect-project))
         (msg (tropelex--magit-commit-msg))
         (diffstat (tropelex--magit-commit-diff))
         (subject (car (split-string msg "\n" t))))
    (if (string-empty-p subject)
        (message "Tropelex: No commit found at HEAD")
      (let ((context (format "Git commit:\n%s\n\nDiffstat:\n%s" msg diffstat)))
        (tropelex--post-capture project subject context "magit")
        (message "Tropelex: Captured commit '%s'" (substring subject 0 (min 50 (length subject))))))))

(defun tropelex--magit-post-commit ()
  "Hook function for `magit-post-commit-hook'."
  (when tropelex-auto-commit-capture
    ;; Run async so magit isn't blocked
    (run-at-time 0.5 nil #'tropelex--magit-capture-commit)))

;; ── Minor mode ─────────────────────────────────────────────────────────

;;;###autoload
(define-minor-mode tropelex-capture-mode
  "Global minor mode for capturing data to Tropelex.

When enabled:
  - Tracks save patterns for rapid-iteration friction detection
  - Auto-scans compilation output for friction signals on errors
  - Auto-captures decisions from magit commits (if magit is installed)
  - Provides keybindings under C-c t prefix

\\{tropelex-capture-mode-map}"
  :global t
  :lighter " Tlx"
  :keymap (let ((map (make-sparse-keymap)))
            (define-key map (kbd "C-c t c") #'tropelex-capture-decision)
            (define-key map (kbd "C-c t r") #'tropelex-capture-region)
            (define-key map (kbd "C-c t f") #'tropelex-friction-scan)
            (define-key map (kbd "C-c t s") #'tropelex-status)
            (define-key map (kbd "C-c t p") #'tropelex-set-project)
            (define-key map (kbd "C-c t g") #'tropelex-capture-commit)
            map)
  :group 'tropelex-capture
  (if tropelex-capture-mode
      (progn
        (add-hook 'after-save-hook #'tropelex--track-save)
        (add-hook 'compilation-finish-functions #'tropelex--compilation-finished)
        ;; Magit integration — add hook if magit is available
        (when (fboundp 'magit-commit)
          (add-hook 'magit-post-commit-hook #'tropelex--magit-post-commit))
        (message "Tropelex capture mode enabled"))
    (remove-hook 'after-save-hook #'tropelex--track-save)
    (remove-hook 'compilation-finish-functions #'tropelex--compilation-finished)
    (remove-hook 'magit-post-commit-hook #'tropelex--magit-post-commit)
    (setq tropelex--save-count 0
          tropelex--last-save-time 0)
    (message "Tropelex capture mode disabled")))

(provide 'tropelex-capture)
;;; tropelex-capture.el ends here
