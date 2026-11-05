# Insecure Deserialization / Data Integrity Failures

Trigger terms: insecure deserialization, pickle, yaml.load, unsafe
deserialize, "untrusted plugin/artifact", unsigned update.

## Core principle

Deserializing untrusted data with a format/library that can reconstruct
arbitrary objects or execute code as a side effect of parsing is equivalent
to giving the data's source code-execution rights.

## Do

- Prefer data-only formats (JSON, well-configured YAML-safe-load, protobuf
  with a fixed schema) over formats that support arbitrary object
  reconstruction (Python `pickle`, Java native serialization, PHP
  `unserialize`, Ruby `Marshal`) for anything touching untrusted input.
- If a language's "safe" variant exists (`yaml.safe_load` instead of
  `yaml.load`, PHP with `allowed_classes` restricted), use it explicitly —
  don't rely on a default that may change.
- Verify integrity/authenticity of serialized blobs that must cross a trust
  boundary (e.g. signed/HMAC'd tokens) before deserializing them.
- For software/update integrity: verify signatures before executing
  downloaded artifacts/plugins/updates.

## Don't

- Don't deserialize data from an untrusted source (user upload, external
  API, message queue fed by external parties) using a format capable of
  instantiating arbitrary classes, even "just this once."
- Don't assume a signature check elsewhere in the pipeline means
  deserialization itself is safe to leave unrestricted — defense in depth.

## Detection heuristics for the agent

- Grep for `pickle.loads`/`pickle.load`, `yaml.load` (without
  `Loader=SafeLoader`), Java `ObjectInputStream.readObject`, PHP
  `unserialize(`, Ruby `Marshal.load` applied to data that originates from a
  request, file upload, or external message — not from a trusted, internal-
  only source.

## False-positive patterns

- Deserialization of data the application itself produced and never exposed
  to external modification (e.g. an internal cache blob round-tripped by the
  same process, with no external write path) is lower risk — still worth
  migrating off `pickle`-like formats opportunistically, but not an active
  exploitable vuln if genuinely untouchable by outside input.
