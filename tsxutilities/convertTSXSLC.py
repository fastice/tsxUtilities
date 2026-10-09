#!/usr/bin/env python3
"""Convert a TSX COSAR (.cos) SLC to a big-endian complex float SLC, optionally
box-averaged by dscale x dscale. Python replacement for converttsxslc.pro.
"""
import os
import numpy as np


def convertTSXSLC(cosFile, slcFile, dscale=1, linesPerChunk=1200):
    '''
    Convert a single-burst COSAR file to a GAMMA-style SLC (big-endian
    complex64, no header).
    Parameters
    ----------
    cosFile : str
        Input .cos file (big-endian; each range line is an 8-byte line
        header followed by rangeSamples int16 I/Q pairs).
    slcFile : str
        Output SLC file.
    dscale : int, optional
        Average dscale x dscale blocks; trailing lines/samples that do not
        fill a block are dropped. The default is 1 (no averaging).
    linesPerChunk : int, optional
        Lines read per chunk (rounded down to a multiple of dscale).
    Returns
    -------
    (rangeSamples, azimuthLines) of the output.
    '''
    header = np.fromfile(cosFile, dtype='>i4', count=7)
    rangeSamples, azimuthSamples = int(header[2]), int(header[3])
    recordSize, nRecords = int(header[5]), int(header[6])
    if recordSize != 8 + 4 * rangeSamples or \
            os.path.getsize(cosFile) != nRecords * recordSize:
        raise ValueError(f'{cosFile} is not a single-burst COSAR file '
                         f'(record size {recordSize}, records {nRecords})')
    headerRecords = nRecords - azimuthSamples
    lines = np.memmap(cosFile, dtype='>i2', mode='r',
                      offset=headerRecords * recordSize,
                      shape=(azimuthSamples, recordSize // 2))
    #
    nRangeOut = rangeSamples // dscale
    nLinesOut = azimuthSamples // dscale
    chunk = max(1, linesPerChunk // dscale) * dscale
    with open(slcFile, 'wb') as fp:
        for first in range(0, nLinesOut * dscale, chunk):
            last = min(first + chunk, nLinesOut * dscale)
            # drop the 4 int16 (8 byte) line header
            iq = lines[first:last, 4:4 + 2 * nRangeOut * dscale]
            if dscale > 1:
                # float32 average over azimuth then range, which reproduces
                # the IDL rebin output bit for bit
                iq = iq.reshape((last - first) // dscale, dscale, nRangeOut,
                                dscale, 2).astype(np.float32)
                iq = iq.mean(axis=1, dtype=np.float32).mean(axis=2,
                                                            dtype=np.float32)
            iq.astype('>f4').tofile(fp)
    return nRangeOut, nLinesOut
