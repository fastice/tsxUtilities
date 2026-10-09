# TSX Utilities

Utilities for filing, processing and releasing TerraSAR-X / TanDEM-X data.

## Installation

```bash
pip install git+https://github.com/fastice/tsxUtilities.git@main
```

`bundleTSX` needs the local `releasefunc` package and `cleantsx` needs the local
`utilities` package.

## Programs

Each Python program is installed with and without the `.py` suffix (e.g.
`fileTSX` and `fileTSX.py`).

**fileTSX** proposes where each incoming DLR delivery (`dims_*.tar.gz`) should be
filed, by matching its GEOREF footprint against the deliveries already in each
region directory. It flags ambiguous, unmatched, duplicate and outlier scenes,
moves only the uniquely-resolved ones with `-apply`, and can undo logged moves.
[Documentation](Documents/fileTSX.md)

**untarTSXCheck** untars the most recent deliveries for a region that have not
been set up yet, runs setupTSX on each, files the result into its
`track-<n>` directory, and writes a report `<region>/unpacked.<date-time>`.
[Documentation](Documents/untarTSXCheck.md)

**setupTSX** sets up one extracted delivery for GIT64 processing: par files,
full-res and 3x3 SLCs, geodats and multilook power images. It replaces the
setuptsx/makecw scripts and the converttsxslc/sath IDL code.
[Documentation](Documents/setupTSX.md)

**cleantsx** runs the clean-up chain for one track from a region directory:
baseline check, autoclean, tiepoint refresh and velocity regeneration.
[Documentation](Documents/cleantsx.md)

**bundleTSX** packages a TSX velocity release into per-box tar files with NSIDC
manifests. [Documentation](Documents/bundleTSX.md)

**runIntTSX** (csh) forms, flattens and filters a 9×9-look interferogram for one
orbit pair and writes the `runUnwrap` script. [Documentation](Documents/runIntTSX.md)

## For Further Information

Please address questions to ![](https://github.com/fastice/GrIMPTools/blob/main/Email.png).
