#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 17 12:34:12 2020

@author: ian
"""

import argparse
# import utilities as u
import os
import releasefunc as release
import glob

currentVersion = '02'
subVersion = '0'


def setupBundleTSXArgs():
    '''
    Handle command line args
    '''
    parser = argparse.ArgumentParser(
        description='\n\n\033[1mAssemble All files for a Release and package'
        ' them \033[0m\n\n')
    parser.add_argument('releaseDir', type=str, nargs=1,
                        help='Name of release dir for this release')
    #
    args = parser.parse_args()
    #

    return args.releaseDir[0]


def getReleaseDirs(releaseDir):
    # *@
    myDirs = sorted(glob.glob(f'*/release/{releaseDir}/*coast*'))
    if len(myDirs) == 0:
        myDirs = sorted(glob.glob(f'*/release/{releaseDir}/Alaska-Taku'))
    hasProducts = []
    for myDir in myDirs:
        # *@
        products = sorted(glob.glob(f'{myDir}/Vel*'))
        if type(products) == list:
            hasProducts.append(myDir)
    return hasProducts


def packageProduct(myProduct, releaseName, append=False):
    print(myProduct)
    # print(releaseName)
    basePath = os.getcwd()
    # print(myProduct)
    boxName = os.path.basename(myProduct)
    pathName = os.path.dirname(myProduct)
    sourceDir = os.path.dirname(pathName)
    nProducts = len(glob.glob(f'{myProduct}/Vel*'))
    if nProducts < 1:
        return 0
    # print(pathName)
    tarFile = f'{basePath}/Releases/{releaseName}/{releaseName}_{boxName}.tar'
    manifestFile =\
        f'{basePath}/Releases/{releaseName}/{releaseName}_{boxName}.manifest'
    # print(boxName, pathName, releaseDir)
    tarFlag = '-cvf'
    if append:
        tarFlag = '-rvf'
    command = \
        f'cd {sourceDir} ; tar {tarFlag} {tarFile} {releaseName}/{boxName} '
    release.runCommand(command)
    #
    release.createManifest(tarFile, manifestFile, releaseName)
    return nProducts


def main():
    # assume for now this greenland only
    # get args
    releasesName = setupBundleTSXArgs()
    fullReleasesDir = release.makeFinalProductDir(releasesName)

    print(f'{fullReleasesDir}')
    myProducts = getReleaseDirs(releasesName)
    #
    i = 0
    nProducts = 0
    boxesUsed = []
    for myProduct in myProducts:
        box = myProduct.split('/')[-1]
        # print(myProduct)
        print('----')
        append = False
        if box in boxesUsed:
            append = True
            print('Repeat box', box)
        nProducts += packageProduct(myProduct, releasesName, append=append)
        boxesUsed.append(box)
        i += 1
    print(f'nReleases {i} with a total of {nProducts} maps')


if __name__ == '__main__':
    main()
