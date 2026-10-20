# untarTSXCheck

Untar and set up the most recent TSX/TDX deliveries for a region, file each
one into its track directory, and write a report. Part of the `tsxUtilities`
package; runnable as `untarTSXCheck` or `untarTSXCheck.py`. Replaces the
`untartsxcheck` and `fileTDX` csh scripts.

## Usage

Run from the TSX processing root, the directory that holds the region
directories (e.g. `/Volumes/insar4/ian/TSX`):

```
untarTSXCheck <region> <nFiles>
untarTSXCheck Helheim 10
```

## What it does

1. Takes the `nFiles` most recently modified `*.gz` deliveries in
   `/Volumes/insar1/ian/Data/TSX/<region>/`.
2. Skips any that are already set up, meaning a `<dims name>` marker exists in
   `<region>/track-*/<orbit>_<frame>/` or in `<region>/<orbit>_<frame>/`.
3. For each remaining one, it:
   1. extracts the tar into `<region>/`
   2. runs [`setupTSX`](setupTSX.md) to create `<region>/<orbit>_1/`
   3. moves that directory into its track directory (see below)
   4. deletes the extracted `dims_*` directory
4. Writes `<region>/unpacked.<YYYY-MM-DD-HHMMSS>`, timestamped with the start
   of the run, listing each delivery and where it went. No report is written
   if nothing new was found.

## Console and log

The console shows one line per delivery, with a dot for each 5% done and the
filing result at the end:

```
dims_op_oc_dfd2_700073014_2 -> /Volumes/insar4/ian/TSX/Helheim/90131_1 [..........          ]
dims_op_oc_dfd2_700073014_2 -> /Volumes/insar4/ian/TSX/Helheim/90131_1 [....................] track-148/90131_1
```

The untar and SLC conversion steps report progress as they run. The dots
for each `multi_SLC` step arrive all at once when it finishes.

Everything else (each command run, its output, and the traceback for a
failure) goes to `<region>/unpacked.<YYYY-MM-DD-HHMMSS>.log`, next to the
report.

## Filing into track directories

The track is `orbit % 167`. If `<region>/track-<n>` does not exist, it tries
`orbit % 167 + 30` (wrapping past 167), the offset for TDX orbit numbers. The
first that exists is used.

An orbit directory is left in `<region>/` and reported as `NOT FILED` when
neither track directory exists, or when `track-<n>/<orbit>_<frame>` already
exists. It is never overwritten.

## Report

One line per delivery processed:

```
dims_op_oc_dfd2_700073014_2 track-148/90131_1
dims_op_oc_dfd2_700073014_1 track-148/89964_1
dims_op_oc_dfd2_700071234_1 90001_1 NOT FILED: no track-155 or track-18
dims_op_oc_dfd2_700075678_1 FAILED: <error>
```

A delivery that fails is reported, its extracted directory is still removed,
and the run continues. The exit status is 1 if any failed. Because the marker
is only written on success, a failed delivery is retried on the next run.
