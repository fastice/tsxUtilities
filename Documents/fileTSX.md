# fileTSX

File incoming **TerraSAR-X / TanDEM-X DLR deliveries** (`dims_*.tar.gz` /
`dims_*.tar.Z`) into per-region directories. Part of the `tsxUtilities` package;
runnable as `fileTSX` or `fileTSX.py`.

By default it is a **dry run**: it reports where each incoming delivery would go
and moves nothing. Filing happens only with `-apply`.

## Directory layout

```
<root>/                      default /Volumes/insar1/ian/Data/TSX
    incoming/                new deliveries land here
    <region>/                e.g. Jak, Helheim, FarNW27 -- filed deliveries
    .tsxFootprintCache.json  parsed footprint cache
    .tsxMoveLog.jsonl        append-only log of -apply moves and -undo restores
```

Any sibling of `incoming` that holds deliveries is a region, except
`incoming*`, `tools` and `EvalIncoming`. `JakInland` is folded into `Jak`
(`REGION_MERGE`). Its existing files are not moved, but it is never proposed as
a target.

## How it reads a delivery

Each archive is read the fast way: only `ANNOTATION/GEOREF.xml`, which sits
before the ~1.8 GB image in the tar (about 0.05 s, compared with ~17 s for the
main product XML after it). From GEOREF and the product folder name it gets the
satellite (`TSX1`/`TDX1`), mode, start time, orbit direction, and footprint
(convex hull in EPSG:3413 km). Results are cached by path and mtime, so each
archive is parsed only once.

## How a scene is resolved

For each incoming scene, in order:

1. **duplicate** — the same acquisition (satellite + start time) is already
   filed in a region. Never moved.
2. **unique (frame match)** — exactly one region has a filed scene within
   `FRAME_KM` (15 km) of this scene's centroid. If several regions do, the one
   that owns the frame wins (≥3× as many and ≥3 more scenes at that spot);
   otherwise it is **ambiguous**.
3. **unique (new frame)** — no nearby frame anywhere: the scene centroid falls
   inside, or ≥ `-overlapFrac` of its area overlaps, exactly one region's
   footprint. Ties are broken by orbit direction.
4. **unmatched** — no region footprint contains or overlaps it (a new region,
   or a parse failure).

Only **unique** scenes are ever moved.

The report also flags **region outliers**: filed scenes whose nearest
neighbour in the same region is more than `max(nnFloorKm, nnK × median
neighbour gap)` away. These are possible past misfiles and are left out of the
region's footprint model.

## Usage

```
fileTSX -initialize          # first time, or after region dirs change: parse all filed deliveries
fileTSX                      # dry run: parse incoming, write report
fileTSX -apply               # dry run, then prompt and move the unique scenes
fileTSX -undo Jak            # move logged -apply moves for Jak back to incoming
fileTSX -undo all
```

The report is printed and written to `<root>/incoming/_fileTSX_report.txt`
(or `-report PATH`).

### Arguments

| Flag | Default | Meaning |
|---|---|---|
| `-root` | `/Volumes/insar1/ian/Data/TSX` | TSX root directory |
| `-threads` | 12 | parallel archive-parse threads |
| `-report` | `<root>/incoming/_fileTSX_report.txt` | report path |
| `-initialize` | off | rescan every region dir and parse its deliveries into the cache; normal runs read only `incoming` |
| `-apply` | off | after the report, move uniquely-resolved scenes into their region dir |
| `-yes` | off | skip the confirmation prompt for `-apply` / `-undo` |
| `-undo REGION\|all` | — | undo active `-apply` moves recorded in the move log, then exit |
| `-overlapFrac` | 0.20 | min scene ∩ region / scene area for the new-frame fallback |
| `-nnFloorKm` | 40 | outlier floor distance (km) |
| `-nnK` | 4.0 | outlier multiple of the region's median neighbour gap |
| `-limitRegion` | 0 | debug: cap archives parsed per region with `-initialize` |

## Safety

- An existing destination file is never overwritten; it is skipped and reported.
- Ambiguous, unmatched and duplicate scenes stay in `incoming`.
- Every move and undo is appended to `.tsxMoveLog.jsonl` with a timestamp.
  `-undo` restores only moves whose last logged action is still a move, and
  skips any whose `incoming` path is already occupied.
