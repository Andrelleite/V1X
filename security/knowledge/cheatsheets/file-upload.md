# File Upload Handling

Trigger terms: unrestricted file upload, path traversal, arbitrary file
write, "upload executes", zip slip.

## Core principle

Treat every uploaded file as hostile: its name, declared content-type, and
contents can all lie. Validate independently of client-supplied metadata,
and never let upload-derived input choose a filesystem path.

## Do

- Generate the stored filename server-side (e.g. a UUID); never use the
  client-supplied filename to build a filesystem path.
- Validate file type by actually inspecting content (magic bytes / a
  content-sniffing library), not just the client-supplied `Content-Type`
  header or file extension.
- Store uploads outside the webroot, or in object storage, so they can't be
  directly executed/served as code even if a malicious file gets through.
- Enforce a maximum file size before and during the upload (not only after
  it's fully buffered in memory).
- If extracting archives, defend against "zip slip" (entries with `../` in
  their path) by validating each extracted path stays within the target
  directory.
- Scan uploads for malware if the app's risk profile warrants it (ticket-
  dependent, not a default requirement for every upload feature).

## Don't

- Don't use the client-supplied filename or extension directly in any
  filesystem path or OS command.
- Don't trust `Content-Type` alone to gate what's accepted.
- Don't serve uploaded files from a path that the web server will execute
  (e.g. a PHP-enabled directory) regardless of extension filtering.

## Detection heuristics for the agent

- Grep upload handlers for use of the raw uploaded filename in `open()`,
  `os.path.join`, file-move/rename calls, or command construction.
- Check archive-extraction code for per-entry path validation.

## False-positive patterns

- An upload feature restricted to authenticated admins uploading to a
  location that is never served back or executed (e.g. a one-time data
  import consumed only by a batch job) carries materially lower risk than a
  public, served upload — calibrate the fix (and the confidence/blast-radius
  note) to the actual exposure, not the generic worst case.
