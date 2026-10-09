#!/usr/bin/env python3
"""Propose how to file incoming TSX/TDX deliveries into per-region directories.

Reads each raw DLR delivery (dims_*.tar.{gz,Z}) the cheap way -- the ANNOTATION/
GEOREF.xml that sits BEFORE the ~1.8 GB image in the archive (~0.05 s), never the
main product XML that sits after it (~17 s). From GEOREF + the product folder name
it derives the scene footprint, centroid, orbit direction and satellite. It then:

  * builds each region dir's footprint by aggregating across all its already-filed
    deliveries (flagging outliers -- a single product far from the region's norm),
  * resolves every incoming scene to exactly ONE region by footprint (+ direction
    to break ties when region boxes overlap),
  * FLAGS anything it cannot place uniquely (matches >1 region, or none).

DRY RUN ONLY: it prints/writes a report and moves nothing. Filing is a separate,
explicitly-confirmed step.
"""
import os
import re
import sys
import json
import glob
import time
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint, Point
from shapely.ops import unary_union

ROOT_DEFAULT = '/Volumes/insar1/ian/Data/TSX'
CACHE_NAME = '.tsxFootprintCache.json'
LOG_NAME = '.tsxMoveLog.jsonl'   # append-only, timestamped record of moves/undos

# Sibling dirs of incoming that are never filing targets even though they may hold
# deliveries. Region dirs are otherwise auto-discovered (any sibling with deliveries).
EXCLUDE_DIRS = {'incoming', 'incoming-ian', 'incoming-leigh', 'incoming-leo',
                'incomingTDX', 'tools', 'EvalIncoming'}

# Regions merged into another over time: {oldDir: canonicalDir}. The old dir's
# filed frames fold into the canonical region's model and the old dir is never a
# filing target. Existing files are NOT moved -- this only affects where incoming
# scenes are proposed to go. Jak absorbed JakInland.
REGION_MERGE = {'JakInland': 'Jak'}

# Matching / outlier thresholds (km unless noted). Tunable via argparse.
OVERLAP_FRAC = 0.20     # min (scene ∩ region)/scene area for the coarse containment fallback
FRAME_KM = 15.0         # a scene within this of a region's existing frame = same frame/track match
NN_FLOOR_KM = 40.0      # a region scene isolated by more than this (and ...) is an outlier
NN_K = 4.0              # ... and more than NN_K x the region's median nearest-neighbour gap

# EPSG:4326 lon/lat -> EPSG:3413 (NSIDC north polar stereographic, Greenland), metres.
_TO_PS = Transformer.from_crs(4326, 3413, always_xy=True)

_DATETIME_RE = re.compile(r'\d{8}T\d{6}')
_MODE_RE = re.compile(r'_(SM|SL|HS|ST|SC|WS)_')


def llToPSkm(lons, lats):
    x, y = _TO_PS.transform(np.asarray(lons), np.asarray(lats))
    return np.asarray(x) / 1000.0, np.asarray(y) / 1000.0


def _decompressCmd(path):
    # gzip -dc handles both gzip (.gz) and legacy LZW compress (.Z).
    return ['gzip', '-dc', path]


def _tarPipe(path, tarArgs):
    """Run `gzip -dc path | tar <tarArgs>` and return tar's stdout bytes."""
    gz = subprocess.Popen(_decompressCmd(path), stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL)
    tar = subprocess.Popen(['tar'] + tarArgs, stdin=gz.stdout,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    gz.stdout.close()
    out, _ = tar.communicate()
    gz.wait()
    return out


def _productFromMemberPath(memberPath):
    """Pull the <PRODUCT> dir name out of a GEOREF member path and split it into
    (satellite, mode, startDatetime). e.g.
    .../TDX1_SAR__SSC______SM_S_SRA_20250619T204238_20250619T204246/ANNOTATION/GEOREF.xml
    """
    prod = ''
    for part in memberPath.split('/'):
        if part.startswith(('TSX1_', 'TDX1_')):
            prod = part
            break
    if not prod:
        return None, None, None, None
    satellite = prod[:4]                         # TSX1 / TDX1
    dts = _DATETIME_RE.findall(prod)
    startDT = dts[0] if dts else None
    m = _MODE_RE.search(prod)
    mode = m.group(1) if m else None
    return satellite, mode, startDT, prod


def parseArchive(path):
    """Fast-path metadata for one delivery archive, or None on failure.

    Returns a dict with satellite, mode, datetime, direction, footprint (bbox in
    lon/lat, centroid in PS km, convex-hull vertices in PS km)."""
    memberPath = _tarPipe(path, ['t', '-f', '-', '--wildcards',
                                 '--occurrence=1', '*/GEOREF.xml']
                          ).decode('ascii', 'replace').strip().splitlines()
    if not memberPath:
        return None
    satellite, mode, startDT, prod = _productFromMemberPath(memberPath[0])

    xml = _tarPipe(path, ['-xO', '-f', '-', '--wildcards',
                          '--occurrence=1', '*/GEOREF.xml'])
    if not xml:
        return None
    lats = np.array(re.findall(rb'<lat>([^<]+)</lat>', xml), dtype=float)
    lons = np.array(re.findall(rb'<lon>([^<]+)</lon>', xml), dtype=float)
    rows = np.array(re.findall(rb'<row>([^<]+)</row>', xml), dtype=float)
    if lats.size < 4 or lats.size != lons.size:
        return None

    # orbit direction: latitude vs azimuth (row) trend. rows may be absent on odd
    # products -- fall back to first-vs-last grid point.
    if rows.size == lats.size:
        direction = 'ASCENDING' if np.cov(rows, lats)[0, 1] >= 0 else 'DESCENDING'
    else:
        direction = 'ASCENDING' if lats[-1] >= lats[0] else 'DESCENDING'

    xkm, ykm = llToPSkm(lons, lats)
    hull = MultiPoint(np.column_stack([xkm, ykm])).convex_hull
    cx, cy = float(hull.centroid.x), float(hull.centroid.y)
    hullXY = [[round(float(x), 3), round(float(y), 3)]
              for x, y in hull.exterior.coords]

    return {
        'satellite': satellite, 'mode': mode, 'datetime': startDT,
        'product': prod, 'direction': direction,
        'bboxLL': [float(lats.min()), float(lats.max()),
                   float(lons.min()), float(lons.max())],
        'centroidPS': [round(cx, 3), round(cy, 3)],  # plain floats (JSON-safe)
        'hullPS': hullXY,
    }


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def loadCache(cachePath):
    if os.path.exists(cachePath):
        try:
            with open(cachePath) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def saveCache(cachePath, cache):
    tmp = cachePath + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cache, f)
    os.replace(tmp, cachePath)


def _logPath(root):
    return os.path.join(root, LOG_NAME)


def appendLog(root, records):
    """Append action records (dicts) to the timestamped JSONL move log."""
    if not records:
        return
    with open(_logPath(root), 'a') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')


def readLog(root):
    recs = []
    p = _logPath(root)
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    return recs


def discoverArchives(root):
    """Return {regionName: [archivePaths]} for every sibling dir of the root that
    holds deliveries (excluding EXCLUDE_DIRS), plus incoming's list separately."""
    regions = {}
    incoming = sorted(glob.glob(os.path.join(root, 'incoming', '*.tar.gz')) +
                      glob.glob(os.path.join(root, 'incoming', '*.tar.Z')))
    for d in sorted(glob.glob(os.path.join(root, '*'))):
        if not os.path.isdir(d):
            continue
        name = os.path.basename(d)
        if name in EXCLUDE_DIRS or name.startswith('incoming'):
            continue
        arts = sorted(glob.glob(os.path.join(d, '*.tar.gz')) +
                      glob.glob(os.path.join(d, '*.tar.Z')))
        if arts:
            regions[name] = arts
    # fold merged regions into their canonical target (e.g. JakInland -> Jak)
    for old, canon in REGION_MERGE.items():
        if old in regions:
            regions.setdefault(canon, []).extend(regions.pop(old))
    return regions, incoming


def incomingArchives(root):
    return sorted(glob.glob(os.path.join(root, 'incoming', '*.tar.gz')) +
                  glob.glob(os.path.join(root, 'incoming', '*.tar.Z')))


def regionsFromCache(cache):
    """Group already-parsed region scenes straight out of the cache (canonical
    names, merges applied) -- so a normal run needs no region-dir scan. A scene
    counts as filed when its cached region label is a real region (not incoming/
    excluded)."""
    groups = {}
    for p, e in cache.items():
        if 'centroidPS' not in e:
            continue
        r = e.get('region')
        if not r or r == 'incoming' or r in EXCLUDE_DIRS:
            continue
        groups.setdefault(REGION_MERGE.get(r, r), []).append(p)
    return groups


def refreshCache(cache, jobs, cachePath, threads, label):
    """jobs: list of (archivePath, regionName). Parse any not already cached with a
    current mtime; update cache in place; checkpoint periodically."""
    todo = []
    for path, region in jobs:
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        ent = cache.get(path)
        # region label is cosmetic (models use the discovered mapping, which may
        # merge dirs) -- don't force a re-parse just because it changed.
        if ent and ent.get('mtime') == mt and 'centroidPS' in ent:
            continue
        todo.append((path, region, mt))
    if not todo:
        print(f'  {label}: all {len(jobs)} cached')
        return 0

    print(f'  {label}: parsing {len(todo)} of {len(jobs)} (threads={threads})')
    done = 0
    failed = 0
    t0 = time.time()

    def _work(item):
        path, region, mt = item
        try:
            meta = parseArchive(path)
        except Exception:
            meta = None
        return path, region, mt, meta

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = [ex.submit(_work, it) for it in todo]
        for fut in as_completed(futs):
            path, region, mt, meta = fut.result()
            done += 1
            if meta is None:
                failed += 1
                cache[path] = {'mtime': mt, 'region': region, 'error': True}
            else:
                meta['mtime'] = mt
                meta['region'] = region
                cache[path] = meta
            if done % 200 == 0:
                saveCache(cachePath, cache)
                rate = done / max(1e-6, time.time() - t0)
                print(f'    {done}/{len(todo)}  ({rate:.1f}/s, {failed} failed)')
    saveCache(cachePath, cache)
    print(f'  {label}: parsed {done} ({failed} failed) in {time.time()-t0:.0f}s')
    return failed


# ---------------------------------------------------------------------------
# region models + matching
# ---------------------------------------------------------------------------
def _hullPoly(entry):
    return MultiPoint(entry['hullPS']).convex_hull


def buildRegionModels(cache, regions):
    """For each region: union footprint (outliers excluded), direction/satellite
    sets, and the list of outlier archives (possible past misfiles)."""
    models = {}
    outliersAll = {}
    for name, paths in regions.items():
        ents = [(p, cache[p]) for p in paths
                if p in cache and 'centroidPS' in cache[p]]
        if not ents:
            continue
        cents = np.array([e['centroidPS'] for _, e in ents])

        # nearest-neighbour gap per scene (isolation) -> outlier if far from ALL
        # others. Robust to multi-frame regions (each frame's scenes sit near
        # their neighbours) unlike a distance-from-centre test.
        outIdx = set()
        if len(ents) >= 3:
            nn = np.full(len(ents), np.inf)
            for i in range(len(ents)):
                d = np.hypot(cents[:, 0] - cents[i, 0], cents[:, 1] - cents[i, 1])
                d[i] = np.inf
                nn[i] = d.min()
            medNN = np.median(nn[np.isfinite(nn)])
            thresh = max(NN_FLOOR_KM, NN_K * medNN)
            outIdx = {i for i in range(len(ents)) if nn[i] > thresh}

        outliers = []
        keptPolys = []
        dirs = set()
        sats = set()
        for i, (p, e) in enumerate(ents):
            if i in outIdx:
                outliers.append((p, e))
                continue
            keptPolys.append(_hullPoly(e))
            if e.get('direction'):
                dirs.add(e['direction'])
            if e.get('satellite'):
                sats.add(e['satellite'])
        if not keptPolys:
            continue
        keptCents = np.array([e['centroidPS'] for i, (p, e) in enumerate(ents)
                              if i not in outIdx])
        models[name] = {
            'union': unary_union(keptPolys),
            'directions': dirs, 'satellites': sats,
            'nScenes': len(keptPolys), 'centroid': np.median(cents, axis=0),
            'centroids': keptCents,
        }
        if outliers:
            outliersAll[name] = outliers
    return models, outliersAll


def resolveScene(entry, models, filedIndex):
    """Return (status, regions, note). status in {duplicate, unique, ambiguous,
    unmatched}.

    A scene whose exact acquisition (satellite + start datetime) is already filed
    in some region is a re-download -> 'duplicate' (never proposed for a move).

    Otherwise the primary discriminator is the nearest already-filed scene. A repeat-pass TSX/TDX scene
    sits ~0 km from its own region's existing frame, so the region holding the
    closest filed scene wins -- this cleanly separates spatially-overlapping /
    nested regions (e.g. Jak vs JakInland) that a footprint-union test cannot.
    Falls back to footprint containment (+ direction) for a genuinely new frame
    that no region has seen before."""
    key = (entry.get('satellite'), entry.get('datetime'))
    if key in filedIndex:
        regs = sorted(filedIndex[key])
        return 'duplicate', regs, f'same acquisition already filed in {", ".join(regs)}'

    cx, cy = entry['centroidPS']
    # per-region distance to the nearest filed scene
    dmin = {}
    for name, m in models.items():
        c = m['centroids']
        dmin[name] = float(np.min(np.hypot(c[:, 0] - cx, c[:, 1] - cy)))
    near = sorted([n for n, d in dmin.items() if d <= FRAME_KM], key=lambda n: dmin[n])
    if len(near) == 1:
        return 'unique', near, f'matches {near[0]} frame {dmin[near[0]]:.1f} km'
    if len(near) > 1:
        # >1 region holds this frame. The region that OWNS it (many scenes at this
        # footprint) wins over a stray duplicate elsewhere (e.g. FarNW27's 159 vs
        # nwExtra's 2). Only a genuine near-tie stays ambiguous.
        cnt = {}
        for n in near:
            c = models[n]['centroids']
            cnt[n] = int(np.count_nonzero(np.hypot(c[:, 0] - cx, c[:, 1] - cy) <= FRAME_KM))
        ranked = sorted(near, key=lambda n: -cnt[n])
        top, second = ranked[0], ranked[1]
        if cnt[top] >= 3 * cnt[second] and cnt[top] >= cnt[second] + 3:
            return 'unique', [top], (f'owns frame ({top} {cnt[top]} scenes vs '
                                     f'{second} {cnt[second]})')
        info = ', '.join(f'{n}:{cnt[n]}' for n in ranked)
        return 'ambiguous', ranked, f'frame present in >1 region, no clear owner ({info})'

    # No existing frame nearby: coarse footprint containment for a new frame.
    pt = Point(cx, cy)
    scenePoly = _hullPoly(entry)
    sceneArea = scenePoly.area or 1.0
    cands = []
    for name, m in models.items():
        u = m['union']
        if u.contains(pt) or (u.intersects(scenePoly)
                              and scenePoly.intersection(u).area / sceneArea >= OVERLAP_FRAC):
            cands.append(name)
    if len(cands) == 1:
        return 'unique', cands, f'new frame in {cands[0]} footprint (nearest {dmin[cands[0]]:.0f} km)'
    if len(cands) == 0:
        best = min(dmin, key=dmin.get)
        return 'unmatched', [], (f'no region footprint contains/overlaps it; '
                                 f'nearest region {best} {dmin[best]:.0f} km')
    d = entry.get('direction')
    narrowed = [n for n in cands if d in models[n]['directions']]
    if len(narrowed) == 1:
        return 'unique', narrowed, f'new frame in {narrowed[0]} (tie broken by direction={d})'
    return 'ambiguous', cands, f'overlaps regions {cands}; direction={d} did not disambiguate'


# ---------------------------------------------------------------------------
def formatReport(root, regions, incoming, cache, models, outliersAll, results):
    L = []
    L.append(f'TSX filing dry-run report  ({time.strftime("%Y-%m-%d %H:%M:%S")})')
    L.append(f'root: {root}')
    L.append(f'regions discovered: {len(regions)}  '
             f'(modelled: {len(models)})')
    L.append(f'incoming archives: {len(incoming)}')
    L.append('')
    L.append('=== region models (scenes, directions, satellites) ===')
    for name in sorted(models):
        m = models[name]
        L.append(f'  {name:14s} n={m["nScenes"]:4d}  dir={sorted(m["directions"])}  '
                 f'sat={sorted(m["satellites"])}')
    L.append('')

    prop = [r for r in results if r[1] == 'unique']
    amb = [r for r in results if r[1] == 'ambiguous']
    un = [r for r in results if r[1] == 'unmatched']
    dup = [r for r in results if r[1] == 'duplicate']

    L.append(f'=== PROPOSED FILINGS ({len(prop)}) ===')
    for path, _, regs, note, e in sorted(prop, key=lambda r: r[2][0]):
        b = os.path.basename(path)
        c = e.get('bboxLL', [0, 0, 0, 0])
        L.append(f'  {b:42s} {e.get("satellite","?")} {e.get("datetime","?")} '
                 f'{e.get("direction","?")[:4]:4s} '
                 f'ctr~({(c[0]+c[1])/2:.2f},{(c[2]+c[3])/2:.2f})  ->  {regs[0]}'
                 + (f'   [{note}]' if note else ''))
    L.append('')
    L.append(f'=== FLAGGED: AMBIGUOUS ({len(amb)}) -- needs manual placement ===')
    for path, _, regs, note, e in amb:
        L.append(f'  {os.path.basename(path):42s} {e.get("direction","?")[:4]:4s} '
                 f'{note}')
    L.append('')
    L.append(f'=== FLAGGED: UNMATCHED ({len(un)}) -- no region / new region ===')
    for path, _, regs, note, e in un:
        c = e.get('bboxLL', [0, 0, 0, 0])
        L.append(f'  {os.path.basename(path):42s} '
                 f'ctr~({(c[0]+c[1])/2:.2f},{(c[2]+c[3])/2:.2f})  {note}')
    L.append('')
    L.append(f'=== ALREADY FILED / DUPLICATE ({len(dup)}) -- same acquisition in a '
             f'region; not moved ===')
    for path, _, regs, note, e in dup:
        L.append(f'  {os.path.basename(path):42s} {e.get("satellite","?")} '
                 f'{e.get("datetime","?")}  {note}')
    L.append('')
    nOut = sum(len(v) for v in outliersAll.values())
    L.append(f'=== FLAGGED: REGION OUTLIERS ({nOut}) -- possible past misfiles ===')
    for name in sorted(outliersAll):
        for path, e in outliersAll[name]:
            c = e.get('bboxLL', [0, 0, 0, 0])
            L.append(f'  {name:14s} {os.path.basename(path):42s} '
                     f'ctr~({(c[0]+c[1])/2:.2f},{(c[2]+c[3])/2:.2f})')
    L.append('')
    L.append('=== SUMMARY ===')
    L.append(f'  incoming total : {len(incoming)}')
    L.append(f'  proposed       : {len(prop)}')
    L.append(f'  duplicate      : {len(dup)}  (already filed; not moved)')
    L.append(f'  ambiguous      : {len(amb)}')
    L.append(f'  unmatched      : {len(un)}')
    L.append(f'  accounted for  : {len(prop)+len(dup)+len(amb)+len(un)} '
             f'(== incoming: {len(prop)+len(dup)+len(amb)+len(un) == len(incoming)})')
    L.append(f'  region outliers: {nOut}')
    L.append('')
    L.append('NOTHING MOVED. Review, then confirm filing as a separate step.')
    return '\n'.join(L)


def applyMoves(root, results, cache, cachePath, assumeYes):
    """Move ONLY the uniquely-resolved incoming scenes into their region dir.
    Ambiguous/unmatched scenes are never touched; an existing destination is
    never overwritten (skipped + reported). Prompts unless assumeYes."""
    import shutil
    plan, skip = [], []
    for path, status, regs, note, e in results:
        if status != 'unique':
            continue
        dest = os.path.join(root, regs[0], os.path.basename(path))
        (skip if os.path.exists(dest) else plan).append((path, dest, regs[0]))

    print(f'\n--- APPLY ---  {len(plan)} to move, {len(skip)} skipped (dest exists)')
    for src, dest, region in skip:
        print(f'  SKIP (exists): {os.path.basename(src)} -> {region}/')
    if not plan:
        print('apply: nothing to move.')
        return
    if not assumeYes:
        try:
            resp = input(f'Move {len(plan)} uniquely-resolved files into their '
                         f'region dirs? [y/N] ').strip().lower()
        except EOFError:
            resp = ''
        if resp not in ('y', 'yes'):
            print('apply: aborted (nothing moved).')
            return

    ts = time.strftime('%Y-%m-%dT%H:%M:%S')
    moved = 0
    logRecs = []
    for src, dest, region in plan:
        ent = cache.get(src, {})
        try:
            shutil.move(src, dest)
            moved += 1
            if src in cache:                     # keep the cache valid post-move
                e2 = cache.pop(src)
                e2['region'] = region
                cache[dest] = e2
            logRecs.append({'ts': ts, 'action': 'move', 'region': region,
                            'src': src, 'dest': dest,
                            'satellite': ent.get('satellite'),
                            'datetime': ent.get('datetime')})
        except Exception as ex:
            print(f'  FAILED {os.path.basename(src)} -> {region}/: {ex}')
    appendLog(root, logRecs)
    saveCache(cachePath, cache)
    print(f'apply: moved {moved} of {len(plan)} ({len(skip)} skipped). '
          f'Ambiguous/unmatched/duplicate left in incoming.')
    print(f'  logged to {_logPath(root)}')


def undoMoves(root, which, cache, cachePath, assumeYes):
    """Undo prior -apply moves recorded in the log, for one region or 'all'.
    Moves each still-active file back from its region dir to incoming. A move is
    'active' if the log's last action for that destination is a move (not a
    later undo)."""
    import shutil
    recs = readLog(root)
    if not recs:
        print(f'undo: no move log at {_logPath(root)}')
        return
    lastAction = {}
    moves = {}
    for r in recs:
        d = r.get('dest')
        if not d:
            continue
        lastAction[d] = r.get('action')
        if r.get('action') == 'move':
            moves[d] = r
    active = [r for d, r in moves.items() if lastAction.get(d) == 'move']
    if which != 'all':
        active = [r for r in active if r.get('region') == which]
    if not active:
        print(f'undo: nothing active to undo for {which!r}')
        return

    plan, skip = [], []
    for r in active:
        src, dest = r['src'], r['dest']
        if not os.path.exists(dest):
            skip.append((r, 'file not at region dir (moved/removed)'))
        elif os.path.exists(src):
            skip.append((r, 'incoming path already occupied'))
        else:
            plan.append(r)

    print(f'\n--- UNDO ({which}) ---  {len(plan)} to restore to incoming, '
          f'{len(skip)} skipped')
    for r, why in skip:
        print(f'  SKIP {os.path.basename(r["dest"])} <- {r.get("region")}/: {why}')
    if not plan:
        return
    if not assumeYes:
        try:
            resp = input(f'Move {len(plan)} files back to incoming? [y/N] ').strip().lower()
        except EOFError:
            resp = ''
        if resp not in ('y', 'yes'):
            print('undo: aborted (nothing moved).')
            return

    ts = time.strftime('%Y-%m-%dT%H:%M:%S')
    undone = 0
    logRecs = []
    for r in plan:
        src, dest, region = r['src'], r['dest'], r.get('region')
        try:
            shutil.move(dest, src)
            undone += 1
            if dest in cache:
                e2 = cache.pop(dest)
                e2['region'] = 'incoming'
                cache[src] = e2
            logRecs.append({'ts': ts, 'action': 'undo', 'region': region,
                            'src': src, 'dest': dest})
        except Exception as ex:
            print(f'  FAILED {os.path.basename(dest)}: {ex}')
    appendLog(root, logRecs)
    saveCache(cachePath, cache)
    print(f'undo: restored {undone} of {len(plan)} to incoming.')


def main():
    global OVERLAP_FRAC, NN_FLOOR_KM, NN_K
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-root', default=ROOT_DEFAULT, help=f'TSX root [{ROOT_DEFAULT}]')
    ap.add_argument('-threads', type=int, default=12, help='parse threads [12]')
    ap.add_argument('-report', default=None,
                    help='write report to this path [default: <root>/incoming/_fileTSX_report.txt]')
    ap.add_argument('-overlapFrac', type=float, default=OVERLAP_FRAC)
    ap.add_argument('-nnFloorKm', type=float, default=NN_FLOOR_KM)
    ap.add_argument('-nnK', type=float, default=NN_K)
    ap.add_argument('-initialize', action='store_true',
                    help='(re)scan ALL region dirs and parse their deliveries to '
                         'build/update the cached region models. Run once at setup '
                         'and whenever region data changes. Normal runs skip this '
                         'and only read incoming')
    ap.add_argument('-apply', action='store_true',
                    help='after reporting, MOVE the uniquely-resolved scenes into '
                         'their region dir (ambiguous/unmatched stay in incoming; '
                         'existing destinations are never overwritten). Prompts unless -yes')
    ap.add_argument('-yes', action='store_true',
                    help='with -apply/-undo, skip the confirmation prompt')
    ap.add_argument('-undo', metavar='REGION|all', default=None,
                    help='undo prior -apply moves (from the move log): move files '
                         'back from REGION (or "all") to incoming, then exit. '
                         'Does not re-scan archives')
    ap.add_argument('-limitRegion', type=int, default=0,
                    help='debug: cap archives parsed per region')
    args = ap.parse_args()
    OVERLAP_FRAC, NN_FLOOR_KM, NN_K = args.overlapFrac, args.nnFloorKm, args.nnK

    root = args.root
    cachePath = os.path.join(root, CACHE_NAME)
    cache = loadCache(cachePath)

    if args.undo:
        undoMoves(root, args.undo, cache, cachePath, args.yes)
        return

    # Region models come from the cache (built once via -initialize). A normal
    # run only reads incoming.
    if args.initialize:
        print('Initialize: scanning region dirs ...')
        regions, _ = discoverArchives(root)
        print(f'  {len(regions)} region dirs: ' + ', '.join(sorted(regions)))
        regionJobs = []
        for name, paths in regions.items():
            ps = paths[:args.limitRegion] if args.limitRegion else paths
            regionJobs += [(p, name) for p in ps]
        refreshCache(cache, regionJobs, cachePath, args.threads, 'regions')

    incoming = incomingArchives(root)
    incomingJobs = [(p, 'incoming') for p in incoming]
    print(f'Incoming: {len(incoming)} archives')
    refreshCache(cache, incomingJobs, cachePath, args.threads, 'incoming')

    print('Building region models from cache ...')
    regions = regionsFromCache(cache)
    if not regions:
        print('  no region models in cache -- run once with -initialize first.')
        return
    models, outliersAll = buildRegionModels(cache, regions)

    # index of already-filed acquisitions (satellite, datetime) -> region set,
    # so a re-downloaded incoming scene is recognised as an existing file.
    filedIndex = {}
    for name, paths in regions.items():
        for p in paths:
            e = cache.get(p)
            if e and e.get('satellite') and e.get('datetime'):
                filedIndex.setdefault((e['satellite'], e['datetime']), set()).add(name)

    print('Resolving incoming scenes ...')
    results = []
    for p, _ in incomingJobs:
        e = cache.get(p)
        if not e or 'centroidPS' not in e:
            results.append((p, 'unmatched', [], 'metadata parse failed', e or {}))
            continue
        status, regs, note = resolveScene(e, models, filedIndex)
        results.append((p, status, regs, note, e))

    report = formatReport(root, regions, incoming, cache, models, outliersAll, results)
    print()
    print(report)

    reportPath = args.report or os.path.join(root, 'incoming', '_fileTSX_report.txt')
    try:
        with open(reportPath, 'w') as f:
            f.write(report + '\n')
        print(f'\n(report written to {reportPath})')
    except Exception as ex:
        print(f'\n(could not write report to {reportPath}: {ex})')

    if args.apply:
        applyMoves(root, results, cache, cachePath, args.yes)
    else:
        print('\n(dry run -- nothing moved. Re-run with -apply to file the '
              'uniquely-resolved scenes.)')


if __name__ == '__main__':
    main()
