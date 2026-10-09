#!/usr/bin/env python3
"""Untar and set up the most recent TSX/TDX deliveries for a region that have
not been set up yet, file each into its track directory, and write a report
<region>/unpacked.<date-time>. Run from the TSX processing root (the directory
holding the region directories). Python replacement for the untartsxcheck and
fileTDX csh scripts.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime
from tsxutilities.setupTSX import setupTSX

DATA_ROOT = '/Volumes/insar1/ian/Data/TSX'
REPEAT_ORBITS = 167
TDX_TRACK_OFFSET = 30


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
    startTime = datetime.now()
    report = []
    failed = []
    for tarFile in tarFiles:
        dims = os.path.basename(tarFile).split('.')[0]
        if isSetUp(regionDir, dims):
            continue
        print('not unpacked yet', dims)
        dimsDir = os.path.join(regionDir, dims)
        try:
            subprocess.run(['tar', '-xf', tarFile], cwd=regionDir, check=True)
            result = fileOrbitDir(setupTSX(dimsDir))
        except Exception as e:
            result = f'FAILED: {e}'
            failed.append(dims)
        finally:
            shutil.rmtree(dimsDir, ignore_errors=True)
        print(f'{dims} {result}')
        report.append(f'{dims} {result}')
    if report:
        reportFile = os.path.join(
            regionDir, f'unpacked.{startTime.strftime("%Y-%m-%d-%H%M%S")}')
        with open(reportFile, 'w') as fp:
            fp.write('\n'.join(report) + '\n')
        print(f'Report: {reportFile}')
    if failed:
        print(f'{len(failed)} failed: {" ".join(failed)}')
        sys.exit(1)


if __name__ == '__main__':
    main()
