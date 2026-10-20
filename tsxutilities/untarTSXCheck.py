#!/usr/bin/env python3
"""Untar and set up the most recent TSX/TDX deliveries for a region that have
not been set up yet, file each into its track directory, and write a report
<region>/unpacked.<date-time> and log <region>/unpacked.<date-time>.log. Run
from the TSX processing root (the directory holding the region directories).
Python replacement for the untartsxcheck and fileTDX csh scripts.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from tsxutilities.setupTSX import setupTSX, findProduct

DATA_ROOT = '/Volumes/insar1/ian/Data/TSX'
REPEAT_ORBITS = 167
TDX_TRACK_OFFSET = 30
UNTAR_FRACTION = 0.5   # approximate share of the time spent untarring


class ProgressLine:
    ''' Console line "<label> [.....     ]" with a dot per 5% done '''

    def __init__(self, label, nDots=20):
        self.label = label
        self.nDots = nDots
        self.dots = 0
        self.draw()

    def draw(self, end=''):
        print(f'\r{self.label} [{"." * self.dots:<{self.nDots}}]', end=end,
              flush=True)

    def setLabel(self, label):
        self.label = label
        self.draw()

    def update(self, fraction):
        dots = min(self.nDots, int(fraction * self.nDots))
        if dots > self.dots:
            self.dots = dots
            self.draw()

    def finish(self, message):
        self.draw(end=f' {message}\n')


def untar(tarFile, regionDir, log, progress):
    ''' Extract a .tar.gz into regionDir, reporting the fraction read '''
    size = os.path.getsize(tarFile)
    print(f'$ tar -xzf {tarFile}', file=log, flush=True)
    tar = subprocess.Popen(['tar', '-xzf', '-'], cwd=regionDir,
                           stdin=subprocess.PIPE, stdout=log,
                           stderr=subprocess.STDOUT)
    done = 0
    with open(tarFile, 'rb') as fp:
        while chunk := fp.read(1 << 24):
            tar.stdin.write(chunk)
            done += len(chunk)
            progress(done / size)
    tar.stdin.close()
    if tar.wait() != 0:
        raise RuntimeError(f'tar failed for {tarFile}')


def isSetUp(regionDir, dims):
    ''' True if a <orbit>/<dims> marker exists, filed or not '''
    return len(glob.glob(os.path.join(regionDir, 'track-*', '*', dims)) +
               glob.glob(os.path.join(regionDir, '*', dims))) > 0


def fileOrbitDir(orbitDir):
    '''
    Move <region>/<orbit>_<frame> into <region>/track-<n>, where n is
    orbit % 167, or that plus the TDX offset of 30 if track-<n> does not
    exist (formerly fileTDX).
    Returns
    -------
    str
        Destination relative to the region dir, or why it was not filed.
    '''
    regionDir, orbitId = os.path.split(orbitDir)
    track = int(orbitId.split('_')[0]) % REPEAT_ORBITS
    tdxTrack = track + TDX_TRACK_OFFSET
    if tdxTrack > REPEAT_ORBITS:
        tdxTrack -= REPEAT_ORBITS
    for t in [track, tdxTrack]:
        if os.path.isdir(os.path.join(regionDir, f'track-{t}')):
            destination = f'track-{t}/{orbitId}'
            if os.path.exists(os.path.join(regionDir, destination)):
                return f'{orbitId} NOT FILED: {destination} already exists'
            shutil.move(orbitDir, os.path.join(regionDir, destination))
            return destination
    return f'{orbitId} NOT FILED: no track-{track} or track-{tdxTrack}'


def main():
    parser = argparse.ArgumentParser(
        description='\n\n\033[1mUntar and set up the most recent TSX/TDX '
        'deliveries for a region\033[0m\n\n')
    parser.add_argument('region', type=str,
                        help=f'Region (dir name under both {DATA_ROOT} and '
                        'the current directory)')
    parser.add_argument('nFiles', type=int,
                        help='Number of most recent deliveries to check')
    args = parser.parse_args()
    #
    tarFiles = sorted(glob.glob(os.path.join(DATA_ROOT, args.region, '*.gz')),
                      key=os.path.getmtime, reverse=True)[:args.nFiles]
    regionDir = os.path.abspath(args.region)
    reportFile = os.path.join(
        regionDir, f'unpacked.{datetime.now().strftime("%Y-%m-%d-%H%M%S")}')
    log = None
    report = []
    failed = []
    for tarFile in tarFiles:
        dims = os.path.basename(tarFile).split('.')[0]
        if isSetUp(regionDir, dims):
            continue
        if log is None:
            log = open(f'{reportFile}.log', 'w')
        print(f'==== {dims}', file=log, flush=True)
        dimsDir = os.path.join(regionDir, dims)
        line = ProgressLine(dims)
        try:
            untar(tarFile, regionDir, log,
                  lambda f: line.update(UNTAR_FRACTION * f))
            line.setLabel(f'{dims} -> {findProduct(dimsDir)[3]}')
            orbitDir = setupTSX(
                dimsDir, log=log,
                progress=lambda f: line.update(
                    UNTAR_FRACTION + (1 - UNTAR_FRACTION) * f))
            result = fileOrbitDir(orbitDir)
        except Exception as e:
            traceback.print_exc(file=log)
            result = f'FAILED: {e}'
            failed.append(dims)
        finally:
            shutil.rmtree(dimsDir, ignore_errors=True)
        print(f'{dims} {result}', file=log, flush=True)
        line.finish(result)
        report.append(f'{dims} {result}')
    if report:
        log.close()
        with open(reportFile, 'w') as fp:
            fp.write('\n'.join(report) + '\n')
        print(f'Report: {reportFile}  Log: {reportFile}.log')
    if failed:
        print(f'{len(failed)} failed: {" ".join(failed)}')
        sys.exit(1)


if __name__ == '__main__':
    main()
