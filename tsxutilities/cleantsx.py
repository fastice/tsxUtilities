#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct 30 07:44:35 2019

@author: ian
"""
import argparse
import utilities as u
from datetime import datetime
from subprocess import call


def getTrack():
    tracks = u.dols('ls -d track-*')
    if len(tracks) > 1:
        u.myerror('more than one track, manually specify with --track')
    try:
        track = int(tracks[0].split('-')[1])
    except Exception:
        u.myerror(f'Cannot parse track from {tracks[0]}')
    return track


def checkDate(dateString):
    try:
        myDate = datetime.strptime(dateString, "%Y-%m-%d")
    except Exception:
        u.myerror("Invalid date string {dateString} - use YYYY-MM-DD")
    return myDate


def setupCleanTSXArgs():
    ''' Handle command line args'''
    parser = argparse.ArgumentParser(
        description='\n\n\033[1mRun steps to clean tsx, run from region direct'
        ' (e.g., iker) \033[0m\n\n')
    parser.add_argument('--track', type=int, default=-1,
                        help='specify integer track number [*]')
    parser.add_argument('--firstdate', type=str, default='2008-01-31',
                        help='Only show dates >= first date [2008-01-31]')
    parser.add_argument('--lastdate', type=str, default='2100-01-01',
                        help='Only show dates >= first date [2130-01-31]')
    parser.add_argument('--updateVel', action='store_true', default=False,
                        help='Update velocity and velocity_nocull')
    parser.add_argument('--updateTies', action='store_true', default=False,
                        help='Update tiepoints')
    parser.add_argument('--noclean', action='store_true', default=False,
                        help='Skip clean - use to regenerate data if baseline'
                        ' problem encountered')
    parser.add_argument('--sigThresh', type=float, default=3.0,
                        help='Sigma for autoculling')
    parser.add_argument('--region', type=str, default='greenland',
                        help='region (e.g., greenland, taku')
    parser.add_argument('--tieFiles', type=str, default=None,
                        help='.yaml file with seasonal ties')
    args = parser.parse_args()
    #
    track = args.track
    if track <= 0:
        track = getTrack()
    #
    firstdate = checkDate(args.firstdate)
    lastdate = checkDate(args.lastdate)
    flags = {'updateVel': args.updateVel, 'updateTies': args.updateTies,
             'noclean': args.noclean, 'region': args.region,
             'tieFiles': args.tieFiles}
    #
    return track, firstdate, lastdate, args.sigThresh, flags


def checkBaseline(track, firstdate, lastdate):
    #
    command = f'checkbasesol.py --track {track} ' \
        f'--firstdate {firstdate.strftime("%Y-%m-%d")} ' \
        f'--lastdate {lastdate.strftime("%Y-%m-%d")}'
    call(command, shell=True, executable='/bin/csh')
    print(command)
    u.myPrompt('Continue, or abort to fix', abort=True)


def autoClean(track, firstdate, lastdate, sigThresh, region):
    u.pushd(f'track-{track}')
    command = f'autoclean.py -refresh -sigThresh={sigThresh} '\
        f'-region={region} ' \
        f'-firstDate={firstdate.strftime("%Y:%m:%d")} '\
        f'-lastDate={lastdate.strftime("%Y:%m:%d")}'
    print(command)
    call(command, shell=True, executable='/bin/csh')
    u.popd()


def updateVels(track, firstdate, lastdate):
    #
    command = f'makevelnoclean.py -redoculled '\
        f'-firstdate={firstdate.strftime("%Y:%m:%d")}  ' \
        f'-lastdate={lastdate.strftime("%Y:%m:%d")} ' \
        f'-toRun="[\'track-{track}\']" -noprompt'
    print(command)
    call(command, shell=True, executable='/bin/csh')
    #
    command = f'makevelnoclean.py -reset '\
        f'-firstdate={firstdate.strftime("%Y:%m:%d")}  '\
        f'-lastdate={lastdate.strftime("%Y:%m:%d")} -' \
        f'toRun="[\'track-{track}\']" -noprompt'
    print(command)
    call(command, shell=True, executable='/bin/csh')


def updateTies(track, firstdate, lastdate, flags):
    #
    years = ''
    for year in range(firstdate.year,
                      min(lastdate.year, datetime.now().year) + 1):
        years += f' {year}'
    tieFiles = ''
    if flags['tieFiles'] is not None:
        tieFiles = '-tieFiles {flags.tieFiles]'
    command = f'refreshties.py -tiesOnly -noPrompt {tieFiles}' \
        f'-toRun="[\'track-{track}\']" {years}'
    print(command)
    call(command, shell=True, executable='/bin/csh')


def main():
    # get args

    track, firstdate, lastdate, sigThresh, flags = setupCleanTSXArgs()
    print(f'track {track} firstdate {firstdate} lastdate {lastdate}')
    # step one check baseline
    if not flags['updateVel'] and not flags['updateTies']:
        checkBaseline(track, firstdate, lastdate)
    #
    if not flags['updateVel'] and not flags['updateTies'] and \
            not flags['noclean']:
        autoClean(track, firstdate, lastdate, sigThresh, flags['region'])
    #
    if not flags['updateVel'] or flags['updateTies']:
        updateTies(track, firstdate, lastdate, flags)
    #
    if not flags['updateTies'] or flags['updateVel']:
        updateVels(track, firstdate, lastdate)


if __name__ == '__main__':
    main()
