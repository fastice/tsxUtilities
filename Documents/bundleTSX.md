# bundleTSX

Package a TSX velocity release into per-box tar files with NSIDC manifests. Part
of the `tsxUtilities` package; runnable as `bundleTSX` or `bundleTSX.py`.

## What it does

Run from the directory that holds the region directories. For release
`<releaseDir>` it:

1. Creates `Releases/<releaseDir>/`.
2. Finds product boxes matching `*/release/<releaseDir>/*coast*`. If there are
   none it falls back to `*/release/<releaseDir>/Alaska-Taku`.
3. For each box with at least one `Vel*` product, tars `<releaseDir>/<box>` from
   that region's `release` dir into
   `Releases/<releaseDir>/<releaseDir>_<box>.tar`. A box name seen again from
   another region is appended (`tar -r`) to the same tar.
4. Writes `Releases/<releaseDir>/<releaseDir>_<box>.manifest` (size and MD5)
   using `releasefunc.createManifest`.

It ends by printing the number of boxes and total products.

## Usage

```
bundleTSX <releaseDir>
```

Depends on the local `releasefunc` package.
