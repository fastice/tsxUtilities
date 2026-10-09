#!/usr/bin/env python3
"""Read a TSX/TDX level-1b product XML and write the GAMMA-style par files
(p<orbit>_<frame>.slc.par.cw and TSX.par) used by the GIT64 tools.

Python replacement for the makecw csh script and the sath.pro IDL routine.
"""
import math
import os
import xml.etree.ElementTree as ET
from datetime import datetime

RMAJ = 6378137.0
RMIN = 6356752.3141
HALF_C = 299792458.0 / 2.0
MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP',
          'OCT', 'NOV', 'DEC']


def parseUTC(timeString):
    ''' Parse a TSX UTC time string (e.g. 2024-06-18T19:58:46.987991Z) '''
    return datetime.strptime(timeString.rstrip('Z'), '%Y-%m-%dT%H:%M:%S.%f')


def secondsOfDay(t):
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond * 1e-6


def readTSXMetadata(xmlFile):
    '''
    Read the fields needed for setup from a level-1b product XML.
    Parameters
    ----------
    xmlFile : str
        Product XML (T?X1_SAR__SSC*.xml).
    Returns
    -------
    dict of metadata. Values copied verbatim into the par file are kept as
    the XML strings.
    '''
    root = ET.parse(xmlFile).getroot()

    def text(path, element=root):
        return element.find(path).text.strip()

    sceneInfo = root.find('productInfo/sceneInfo')
    imageRaster = root.find('productInfo/imageDataInfo/imageRaster')
    orbit = root.find('platform/orbit')
    corners = sceneInfo.findall('sceneCornerCoord') + \
        [sceneInfo.find('sceneCenterCoord')]
    stateVectors = [[text(c, sv) for c in
                     ('posX', 'posY', 'posZ', 'velX', 'velY', 'velZ')]
                    for sv in orbit.findall('stateVec')]
    return {
        'product': os.path.basename(xmlFile),
        'absOrbit': int(text('productInfo/missionInfo/absOrbit')),
        'orbitDirection': text('productInfo/missionInfo/orbitDirection'),
        'lookDirection': text('productInfo/acquisitionInfo/lookDirection'),
        'startTime': parseUTC(text('start/timeUTC', sceneInfo)),
        'prf': text('productSpecific/complexImageInfo/commonPRF'),
        'rangePixels': int(text('numberOfColumns', imageRaster)),
        'azimuthPixels': int(text('numberOfRows', imageRaster)),
        'rowSpacing': float(text('rowSpacing', imageRaster)),
        'firstPixelTime': text('rangeTime/firstPixel', sceneInfo),
        'azimuthSpacing':
            text('productSpecific/complexImageInfo/projectedSpacingAzimuth'),
        'headingAngle': text('headingAngle', sceneInfo),
        'corners': [(text('lat', c), text('lon', c)) for c in corners],
        'firstStateTime':
            parseUTC(text('orbitHeader/firstStateTime/firstStateTimeUTC',
                          orbit)),
        'stateVectorSpacing':
            float(text('orbitHeader/stateVectorTimeSpacing', orbit)),
        'stateVectors': stateVectors,
        'lookAngle': text('platform/referenceData/SARAntennaMechanicalBoresight'),
    }


def satelliteHeight(x, y, z):
    ''' Approximate satellite height above the WGS84 ellipsoid (sath.pro) '''
    e2 = (RMAJ**2 - RMIN**2) / RMAJ**2
    p = math.hypot(x, y)
    lat = math.atan(z / p / (1. - e2))
    n = RMAJ**2 / math.sqrt(RMAJ**2 * math.cos(lat)**2 +
                            RMIN**2 * math.sin(lat)**2)
    return p / math.cos(lat) - n


def selectStateVectors(meta):
    '''
    Return (firstTime, interval, stateVectors) for the par file: every other
    state vector, and for long (>29) lists only the central 9 of those.
    '''
    nState = len(meta['stateVectors'])
    skip = 0
    if nState > 29:
        skip = nState // 2 - 9
        nState = 18
    nKeep = nState // 2
    stateVectors = meta['stateVectors'][skip:skip + 2 * nKeep:2]
    firstTime = secondsOfDay(meta['firstStateTime']) + \
        skip * meta['stateVectorSpacing']
    return firstTime, 2 * meta['stateVectorSpacing'], stateVectors


def writeCWPar(meta, parFile):
    '''
    Write the p<orbit>_<frame>.slc.par.cw file (formerly makecw).
    Parameters
    ----------
    meta : dict
        Metadata from readTSXMetadata.
    parFile : str
        Output par file.
    Returns
    -------
    None.
    '''
    t = meta['startTime']
    seconds = t.second + t.microsecond * 1e-6
    # altitude from the 6th state vector, as makecw did
    altitude = satelliteHeight(*[float(v) for v in meta['stateVectors'][5][0:3]])
    rangeSpacing = meta['rowSpacing'] * HALF_C
    nearRange = float(meta['firstPixelTime']) * HALF_C
    centerRange = nearRange + (meta['rangePixels'] // 2) * rangeSpacing
    farRange = nearRange + meta['rangePixels'] * rangeSpacing
    firstTime, interval, stateVectors = selectStateVectors(meta)
    #
    lines = [
        f'title: {meta["product"]}',
        f'date:  {t.day} {MONTHS[t.month - 1]} {t.year}',
        f'raw_data_start_time:  {t.hour} {t.minute} {seconds:.6f}',
        'channel/mode:           ',
        'earth_semi_major_axis:        6378137.0000   m',
        'earth_semi_minor_axis:        6356752.3141   m',
        'scene_center_latitude:           0',
        'scene_center_longitude:         0',
        f'platform_altitude:              {altitude:.4f}',
        'terrain_height:                     0.0000   m',
        'sensor_position_vector:           0.000000       0.000000  0.   m     m      m',
        'sensor_velocity_vector:         0.       0.000000       0.000000   m/s   m/s   m/s',
        'sensor_acceleration_vector:       0.000000       0.000000       0.000000   m/s^2 m/s^2 m/s^2',
        f'pulse_repetition_frequency:  {meta["prf"]} Hz',
        'I_bias:                           0.0',
        'Q_bias:                           0.0',
        'I_sigma:                          0.0',
        'Q_sigma:                          0.0',
        'IQ_corr:                          0.0',
        'SNR_range_spectrum:               0.0',
        'DAR_doppler:                      0   ',
        'DAR_snr:                             0.000',
        'doppler_polynomial:   0. 0. 0. 0',
        f'range_pixels:                      {meta["rangePixels"]}',
        f'echo_time_delay:  {meta["firstPixelTime"]} s',
        f'range_pixel_spacing:   {rangeSpacing:.9f} m',
        'receiver_gain:                      0.0000   dB',
        'calibration_gain:                   0.0000   dB',
        'near_range_raw:                0',
        'center_range_raw:              0',
        'far_range_raw:                 0',
        f'near_range_slc:               {nearRange:.4f}',
        f'center_range_slc:             {centerRange:.4f}',
        f'far_range_slc:                {farRange:.4f}',
        'range_resolution:                    0   m',
        'sec_range_migration:                 OFF',
        'azimuth_deskew:                      ON',
        'autofocus_snr:                      0.0000',
        'azimuth_bandwidth_fraction:         0.9000',
        'azimuth_presum_factor:                   1',
        'offset_to_first_echo_to_process:    0   echoes',
        'echoes_to_process:                  0    echoes',
        'range_offset:                            0   samples',
        'range_fft_size:                      0',
        'range_looks:                             1   looks',
        'azimuth_looks:                           1   looks',
        'azimuth_offset:                 0   s',
        f'azimuth_pixel_spacing:  {meta["azimuthSpacing"]}',
        f'azimuth_resolution:  {meta["azimuthSpacing"]}',
        f'azimuth_pixels:                    {meta["azimuthPixels"]}',
        'sensor_latitude:                0',
        'sensor_longitude:               0',
        f'sensor_track_angle:  {meta["headingAngle"]}',
    ]
    lines += [f'map_coordinate_{i} {lat} {lon} 0'
              for i, (lat, lon) in enumerate(meta['corners'], start=1)]
    lines += [f'number_of_state_vectors:  {len(stateVectors)}',
              f'time_of_first_state_vector:  {firstTime:.6f}',
              f'state_vector_interval:  {interval:g}']
    for i, sv in enumerate(stateVectors, start=1):
        lines.append(f'state_vector_position_{i} {" ".join(sv[0:3])}')
        lines.append(f'state_vector_velocity_{i} {" ".join(sv[3:6])}')
    with open(parFile, 'w') as fp:
        fp.write('\n'.join(lines) + '\n')


def writeTSXPar(meta, parFile):
    ''' Write the TSX.par sensor file (formerly the end of makecw) '''
    lines = [
        'title:                         TSX test file',
        'sensor_name:                   TSX',
        'chirp_direction:               UP_CHIRP',
        'receiver_adc_mode:             IQ',
        'sample_type:                   BYTE',
        'receiver_spectrum_type:        NORMAL',
        'SAR_center_frequency:           9.6500000e+09  Hz',
        'chirp_bandwidth:                1.5000e+08  Hz',
        'chirp_duration:                 0   s',
        'ADC_sampling_frequency:         1.65e+08  Hz',
        'file_header_size:               0         bytes',
        'record_length:                  0         bytes',
        'record_header_size:                0         bytes',
        'samples_per_record:              0',
        'antenna_azimuth_3dB_beamwidth:     0.00     degrees',
        'antenna_range_3dB_beamwidth:       0.000     degrees',
        'nominal_antenna_azimuth_angle:    90.0000     degrees',
        f'nominal_antenna_look_angle:       {meta["lookAngle"]}     degrees',
        'nominal_platform_pitch_angle:      0.0000     degrees',
        'antenna_pattern_filename:      none',
    ]
    with open(parFile, 'w') as fp:
        fp.write('\n'.join(lines) + '\n')
