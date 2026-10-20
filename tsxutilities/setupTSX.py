#!/usr/bin/env python3
"""Set up one extracted TSX/TDX delivery (dims_*) for GIT64 processing: create
<orbit>_<frame>/ beside it with the par files, full-res and 3x3 SLCs, geodats
and multilook power images. Python replacement for the setuptsx csh script.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
from tsxutilities.tsxMetadata import readTSXMetadata, writeCWPar, writeTSXPar
from tsxutilities.convertTSXSLC import convertTSXSLC

LAMBDA = '0.031067'


def findOne(pattern):
    files = glob.glob(pattern)
    if len(files) != 1:
        raise RuntimeError(f'Expected one match for {pattern}, found {files}')
    return files[0]


def findProduct(dimsDir, frame=1):
    '''
    Locate the product in an extracted delivery.
    Returns
    -------
    meta : dict
        Metadata from readTSXMetadata.
    xmlFile, cosFile : str
        Product XML and COSAR image.
    orbitDir : str
        The <orbit>_<frame> directory setupTSX creates beside dimsDir.
    '''
    dimsDir = os.path.abspath(dimsDir)
    productDir = findOne(os.path.join(dimsDir, 'T?X-1.SAR.L1B', 'T?X*'))
    xmlFile = findOne(os.path.join(productDir, 'T?X1*.xml'))
    cosFile = findOne(os.path.join(productDir, 'IMAGEDATA', '*.cos'))
    meta = readTSXMetadata(xmlFile)
    orbitDir = os.path.join(os.path.dirname(dimsDir),
                            f'{meta["absOrbit"]}_{frame}')
    return meta, xmlFile, cosFile, orbitDir


def setupTSX(dimsDir, frame=1, log=None, progress=None):
    '''
    Set up the orbit directory for one extracted delivery.
    Parameters
    ----------
    dimsDir : str
        Extracted delivery (e.g. dims_op_oc_dfd2_695426816_1).
    frame : int, optional
        Frame number. The default is 1.
    log : file, optional
        Where messages and program output go. The default is stdout.
    progress : function, optional
        Called with the fraction of the setup done (0-1).
    Returns
    -------
    orbitDir : str
        The <orbit>_<frame> directory, created beside dimsDir.
    '''
    log = log or sys.stdout
    progress = progress or (lambda fraction: None)
    meta, xmlFile, cosFile, orbitDir = findProduct(dimsDir, frame=frame)
    orbitId = os.path.basename(orbitDir)
    print(f'{os.path.basename(dimsDir)} -> {orbitDir}', file=log, flush=True)
    os.makedirs(orbitDir, exist_ok=True)
    shutil.copy(xmlFile, orbitDir)

    def path(name):
        return os.path.join(orbitDir, name)

    def run(*command):
        command = [str(x) for x in command]
        print('$ ' + ' '.join(command), file=log, flush=True)
        subprocess.run(command, cwd=orbitDir, check=True, stdout=log,
                       stderr=subprocess.STDOUT)

    slcPar = f'p{orbitId}.slc.par.cw'
    slcPar3 = f'p{orbitId}.3x3.slc.par.cw'
    writeCWPar(meta, path(slcPar))
    writeTSXPar(meta, path('TSX.par'))
    #
    # SLCs, full res and 3x3 averaged
    slc = f'{orbitId}.slc'
    convertTSXSLC(cosFile, path(slc), progress=lambda f: progress(0.17 * f))
    convertTSXSLC(cosFile, path(f'{orbitId}.3x3.slc'), dscale=3,
                  progress=lambda f: progress(0.17 + 0.14 * f))
    run('slcscale', slcPar, slcPar3, 3)
    # Old-format par files for getlocc
    run('convpar', slcPar, f'p{orbitId}.slc.par')
    run('convpar', slcPar3, f'p{orbitId}.3x3.slc.par')
    #
    # geodats. Offset (azimuth_offset * prf) is 0 since the par has
    # azimuth_offset 0; squint is 0.
    orbitType = 0 if meta['orbitDirection'] == 'DESCENDING' else 1
    lookDir = -1 if meta['lookDirection'] == 'LEFT' else 1
    for looks, par, geodat in [(3, f'p{orbitId}.slc.par', 'geodat3x3.in'),
                               (9, f'p{orbitId}.slc.par', 'geodat9x9.in'),
                               (3, f'p{orbitId}.3x3.slc.par',
                                'geodat3.3x3.in')]:
        run('getlocc', '-lambda', LAMBDA, looks, looks, 0., 0., par, geodat,
            orbitType, lookDir)
    progress(0.35)
    #
    # multilook power images
    for looks, done in [(3, 0.68), (9, 1.0)]:
        run('multi_SLC', slcPar, f'p{orbitId}.mli.par', slc,
            f'P{orbitId}.{looks}x{looks}.pow', looks, looks)
        progress(done)
    # marker that untarTSXCheck uses to skip this delivery, written last so a
    # failed setup is redone
    open(path(os.path.basename(dimsDir)), 'w').close()
    return orbitDir


def main():
    parser = argparse.ArgumentParser(
        description='\n\n\033[1mSet up an extracted TSX/TDX delivery '
        '(dims_*) for processing\033[0m\n\n')
    parser.add_argument('dimsDir', type=str,
                        help='Extracted delivery directory (dims_*)')
    parser.add_argument('frame', type=int, nargs='?', default=1,
                        help='Frame number [1]')
    args = parser.parse_args()
    setupTSX(args.dimsDir, frame=args.frame)


if __name__ == '__main__':
    main()
