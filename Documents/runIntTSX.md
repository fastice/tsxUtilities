# runIntTSX

csh script that forms, flattens, filters and prepares to unwrap a 9×9-look TSX
interferogram for one orbit pair. Part of the `tsxUtilities` package and
installed as a plain script (`runIntTSX`).

## Usage

Run from the first orbit's directory, `<orbit1>_<frame>/`, with the second
orbit's directory alongside it (`../<orbit2>_<frame>/`). The script asks for:

```
orbit 1:
orbit 2:
frame:
Orbit type (Desc=0, Asc=1)
```

Looks are fixed at 9×9 and look direction at right-looking.

## Inputs

- `TSX.par` in the current directory
- `geodat9x9.in` in both orbit directories
- `<orbit>_<frame>.slc.par.cw` and `p<orbit>_<frame>.slc.par.cw` for both orbits
- `/Users/ian/templates/unwrapTemp`

## Steps

1. `coarsereg` on the two `geodat9x9.in` files, then `INTERF_SLC2` to form the
   interferogram.
2. Trim the `.slc.par.cw` length to the interferogram length using `sizepar`,
   unless the interferogram is more than 150 lines short.
3. `convpar` / `getlocc` to set up geodat and the centre look angle.
4. `fctoic` to convert to integer complex, `base_orbit` and `makeparams` for the
   baseline (`P<o1>_<f>.P<o2>_<f>.params`).
5. IDL `reflattencomplex`, then `psfiltw1` to filter.
6. Write `runUnwrap`, for a later unwrap that uses offsets to fix ambiguities.

Needs the GIT64/GAMMA binaries and IDL on the path.
