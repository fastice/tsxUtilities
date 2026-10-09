# cleantsx

Run the clean-up steps for one TSX track: baseline check, autoclean, tiepoint
refresh, and velocity regeneration. Part of the `tsxUtilities` package; runnable
as `cleantsx` or `cleantsx.py`.

Run it from a **region directory** (e.g. `iker`) that contains `track-<n>`
directories. Each step shells out to an existing tool under `/bin/csh`.

## Steps

| Step | Command run | When |
|---|---|---|
| 1. Baseline check | `checkbasesol.py --track N --firstdate --lastdate`, then a continue/abort prompt | default run only |
| 2. Autoclean | `autoclean.py -refresh -sigThresh -region -firstDate -lastDate` inside `track-N` | default run, unless `--noclean` |
| 3. Tiepoints | `refreshties.py -tiesOnly -noPrompt -toRun="['track-N']" <years>` | default run, or `--updateTies` |
| 4. Velocities | `makevelnoclean.py -redoculled ...` then `makevelnoclean.py -reset ...` | default run, or `--updateVel` |

With `--updateVel` alone only step 4 runs; with `--updateTies` alone only step 3
runs.

## Usage

```
cd iker
cleantsx                                   # all steps for the only track-* here
cleantsx --track 133 --firstdate 2024-01-01
cleantsx --updateVel                       # regenerate velocities only
cleantsx --noclean                         # skip autoclean (e.g. after fixing a baseline)
```

### Arguments

| Flag | Default | Meaning |
|---|---|---|
| `--track` | auto | track number; if omitted, there must be exactly one `track-*` dir |
| `--firstdate` | 2008-01-31 | first date, `YYYY-MM-DD` |
| `--lastdate` | 2100-01-01 | last date, `YYYY-MM-DD` |
| `--updateVel` | off | only update `velocity` and `velocity_nocull` |
| `--updateTies` | off | only update tiepoints |
| `--noclean` | off | skip autoclean |
| `--sigThresh` | 3.0 | sigma threshold for autoculling |
| `--region` | greenland | region passed to autoclean (e.g. `greenland`, `taku`) |
| `--tieFiles` | — | `.yaml` file with seasonal ties |

Depends on the local `utilities` package.
