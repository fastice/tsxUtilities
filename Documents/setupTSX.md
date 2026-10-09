# setupTSX

Set up one extracted TerraSAR-X / TanDEM-X delivery (`dims_*`) for GIT64
processing. Part of the `tsxUtilities` package; runnable as `setupTSX` or
`setupTSX.py`. [`untarTSXCheck`](untarTSXCheck.md) calls it for each new
delivery.

It replaces the `setuptsx` csh script, the `makecw` csh script and the
`converttsxslc.pro` / `sath.pro` IDL routines. The XML is parsed directly
instead of with grep/awk, and no IDL is needed. The compiled tools
`slcscale`, `convpar`, `getlocc` and `multi_SLC` must be on the path.

## Usage

```
setupTSX <dimsDir> [frame]      # frame defaults to 1
```

## What it does

For `dimsDir/T?X-1.SAR.L1B/T?X*/` (exactly one product, one `.xml` and one
`IMAGEDATA/*.cos`; anything else is an error), it creates
`<orbit>_<frame>/` beside `dimsDir` and writes:

| File | How |
|---|---|
| `T?X1_SAR*.xml` | copy of the product XML |
| `p<id>.slc.par.cw`, `TSX.par` | from the XML (`tsxMetadata.py`, formerly `makecw`) |
| `<id>.slc` | COSAR → big-endian complex float (`convertTSXSLC.py`) |
| `<id>.3x3.slc` | same, 3×3 box-averaged |
| `p<id>.3x3.slc.par.cw` | `slcscale` |
| `p<id>.slc.par`, `p<id>.3x3.slc.par` | `convpar` |
| `geodat3x3.in`, `geodat9x9.in`, `geodat3.3x3.in` | `getlocc -lambda 0.031067` |
| `P<id>.3x3.pow`, `P<id>.9x9.pow`, `p<id>.mli.par` | `multi_SLC` |
| `<dims name>` | empty marker, written last |

Orbit direction comes from `orbitDirection` and look direction from
`acquisitionInfo/lookDirection`.

### par file contents

- Start time is `sceneInfo/start/timeUTC`. Slant ranges are computed from
  `rangeTime/firstPixel` and the image `rowSpacing`. Center range is
  `near + (nr // 2) * spacing`.
- Platform altitude is computed from the 6th state vector (`satelliteHeight`,
  formerly `sath.pro`).
- Every other state vector is written. When there are more than 29, only 9
  are kept, centered on the middle of the list. The first state-vector time
  is shifted by the number skipped × the state-vector spacing.
- PRF, azimuth spacing, heading, corner coordinates and state vectors are
  copied verbatim from the XML.

## Differences from the csh/IDL version

Checked on `dims_op_oc_dfd2_695426816_1` (Helheim, orbit 77606):

- `.slc`, `.3x3.slc`, `TSX.par` and both `.pow` images are byte-identical.
- In the par files, computed values now keep full precision. The old chain
  rounded them in awk and IDL single precision:

  | Value | Old | New |
  |---|---|---|
  | start time (s) | 46.988 | 46.987991 |
  | platform altitude (m) | 521234.23 | 521234.1199 |
  | range pixel spacing (m) | 0.909404 | 0.909403534 |
  | near / center / far range (m) | 626739. / 637265. / 647790. | 626739.2264 / 637264.6629 / 647790.0994 |

  Geodat corner positions move by under 0.5 m as a result.
- The marker file is written after setup succeeds rather than before, so a
  failed setup is retried by the next `untarTSXCheck`.
- When the state-vector count is odd, the old script wrote one more state
  vector than its `number_of_state_vectors` header said. The new one writes
  exactly the header count.
