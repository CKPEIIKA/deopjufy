# Cache policy

Caching is process-local, bounded, and deterministic. `deopjufy` creates no
persistent cache directory and performs no hidden network access.

## Cached work

- Detection caches key results by resolved path, size, and modification time.
- Signature and object-inventory caches use the same file identity plus options
  that affect their output.
- OPJ and OPJU parser caches are bounded and include parser limits in their keys.
- `ExtractionSession` memoizes input bytes, OPJU descriptors, decoded regions,
  structural walks, and repeated scans for one command.
- Printable-string regular expressions use a small bounded LRU cache keyed by
  minimum length.

All cached records are discarded when the process exits. A new file size,
modification time, resolved path, or relevant parser option produces a new cache
key.

## Constraints

Inputs are expected to remain unchanged for the duration of a command. The tool
does not attempt to detect adversarial same-size, same-timestamp mutation while a
process is running. Callers that replace an input should update its modification
time or start a new process.

Caches may hold immutable parse results and scan output only. They must not hide
warnings, change output order, persist user content, or affect manifest semantics.
