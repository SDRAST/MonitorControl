# -*- coding: utf-8 -*-
"""
dss_server.py

Provides class DSSServer, a configuration based master server for DSN antennae.

If this is run as a standalone program then the appropriate environment should
be activated.

On crux pipenv is the environment manager.  /home/ops/dss-monitor-control has
the correct environment.

On host kuiper, conda is the environment manager:

  $ source activate DSSserver

Examples
========
  $ python dss_server2.py --help
  usage: dss_server2.py [-h] [--verbose] [--simulated] [--flask] [--flaskio]

  Fire up DSS control server.

  optional arguments:
    -h, --help       show this help message and exit
    --verbose, -v    In verbose mode, the log level is DEBUG
    --simulated, -s  In simulated mode, DSS Server won't attempt to connect to
                     antenna hardware server.
    --flask, -f      Run server as flask server
    --flaskio, -fio  Run server as flask io server

Note that the Flask interface does not support callbacks in the server, that is,
all callback handler trying to use a callback method to return data will fail.

Example of session to test the server::
  (DSSserver) kuiper@kuiper:~$ python
  >>> hardware = {"Antenna": False,"Receiver": False,"Backend": False,"FrontEnd": False}
  >>> from MonitorControl.Configurations  import station_configuration
  >>> observatory, equipment = station_configuration('WBDC2_K2',hardware=hardware)
  >>> from MonitorControl.apps.server.dss_server2 import DSSServer
  >>> server = DSSServer(observatory, equipment)
  >>> server.observatory
  Observatory "Canberra"

  >>> server.equipment
  {'FE_selector': None,                   'FrontEnd': K_4ch "K",
   'Telescope': None,                     'Antenna': DSN_Antenna "DSS-43",
   'Receiver': WBDC2 "WBDC-2",            'Rx_selector': None,
   'Backend': SAOspec "SAO spectrometer", 'sampling_clock': None,
   'IF_switch': IFswitch "Patch Panel"}

  >>> server.info
  {'project': {'name': 'TAMS', 'source_dir': '/usr/local/projects/TAMS/Observations'},
   'sources': {},
   'verifiers': {},
   'info_save_dir': '/usr/local/RA_data/status/DSSServer',
   'point': {'current_source': None},
   'tsys_calibration': {'date': None,
                        'el': None,
                        'running': False,
                        'data_dir': '/usr/local/RA_data/tsys_calibration_data',
                        'tsys_factors': [ 999883083.3775496, 421958318.055633,
                                         1374067124.697352,  705797017.1087824]},
   'tip': {'running': False, 'data_dir': '/usr/local/RA_data/tipping_data'},
   'boresight': {'running': False,
                 'data_dir': '/usr/local/RA_data/boresight_data',
                 'offset_xel': 0.0,
                 'offset_el': 0.0}}

  >>> server._get_observer_info_dict()
  {'lat': -35:24:14.3,  'elevation': 688.867,    'epoch': 2000/1/1 12:00:00,
   'lon': -211:01:11.8, 'date': 2019/2/2 21:28:07}

  >>> server.get_projects()
  [u'FREGGS', u'UV_Ceti', u'ISM_RRL', u'67P', u'AUTO_PSR']
  >>> server.get_activities()
  ['AUT1', 'BMP0', 'EGG0',
   'PSR0', 'PSR1', 'PSR2', 'PSR3', 'PSR4', 'PSR5', 'PSR6',
   'RRL0',
   'UVC0']
  >>> server.get_equipment()
  {'Backend': SAOspec "SAO spectrometer", 'FrontEnd': K_4ch "K",
   'IF_switch': IFswitch "Patch Panel",   'Antenna': DSN_Antenna "DSS-43",
   'Receiver': WBDC2 "WBDC-2"}

Notes
=====
The Flask client can make two sorts of calls on the server, with arguments and
without.  If no arguments are given, then the server method should have a normal
``return``.  If the client passes arguments, then the method should have a
decorator ``@async_method`` and should return data to the client with callbacks
with names like this:

  servermethod.cb(data)

A decorated method can still have a normal ``return`` for when it is called
from within the server program itself.
"""


import astropy
import astropy.io.fits as pyfits
import astropy.units as u
import calendar
import copy
import pickle as pickle
import datetime
import dateutil
import ephem
import logging
import h5py
import importlib
import json
import math
import numpy as np
import os
import Pyro5
import queue
import random
import threading
import time
import socket
import signal
import six

from Pyro5.serializers import SerializerBase

mpl_logger = logging.getLogger('matplotlib')
mpl_logger.setLevel(logging.WARNING)
module_logger = logging.getLogger(__name__)

import Astronomy as A
from Astronomy.Ephem import SerializableBody
from Astronomy.redshift import V_LSR
import Data_Reduction.boresights.boresight_manager as BSM
import Data_Reduction.boresights.analyzer as BSA
from Data_Reduction.FITS.DSNFITS import FITSfile
from DatesTimes import UnixTime_to_datetime
from MonitorControl import ActionThread, MonitorControlError
from MonitorControl.DSS_server_cfg import tams_config # not really TAMS
from MonitorControl.Configurations  import station_configuration
from MonitorControl.Configurations.GDSCC.WVSR  import station_configuration as std_configuration
import MonitorControl.Configurations.projects as projcfg # project configuration
from MonitorControl.Receivers.DSN import DSN_rx
from Physics.Radiation.Lines.recomb_lines import recomb_freq
from Radio_Astronomy.bands import frequency_to_band
from support import hdf5_util
from support.async_method import async_method
from support.logs import setup_logging
from support.pyro.pyro5_server import Pyro5Server
from support.pyro.socket_error import register_socket_error
from support.test import auto_test
from support.text import make_title

from local_dirs import data_dir, proj_conf_path, projects_dir

# this is needed so it looks like a package even when it is run as a program
if __name__ == "__main__" and __package__ is None:
    __package__ = "MonitorControl"

__all__ = ["DSSServer"]

def nowgmt():
  return time.time()+ time.altzone

def logtime():
  return datetime.datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
  
register_socket_error()

# temporary; need to construct from project, dss, and band
configs = {
  '67P':       {'67P0': 'WBDC2_K2'},
  'AUTO_PSR':  {'PSR0': 'WVSR14L',
                'PSR1': 'WVSR14L',
                'PSR2': 'WVSR14L',
                'PSR3': 'WVSR14L',
                'PSR4': 'WVSR14S',
                'PSR5': 'WVSR14L',
                'PSR6': 'WVSR14L'
               },
  'FREGGS':    {'EGG0': 'WVSR14X'},
  'ISM_RRL':   {'RRL0': 'WBDC2_K2'},
  'TAMS':      {'TMS0': 'WBDC2_K2'},
  'UV_Ceti':   {'UVC0': 'WVSR14L'}
}

# defaults
obsmode = 'LINEBPSW'
veldef = 'RADI-OBS'
equinox = 2000
restfreq = 22235.120 # H2O maser, MHz

@Pyro5.api.expose
class DSSServer(Pyro5Server):
    """
    Server that integrates functionality from a DSS station's hardware configuration.
    Many calibration and observing routines rely on integrating monitor and control
    data from various hardware subsystems in an antenna. For example, boresight,
    or pointing, involves changing antenna position offsets while reading
    power meter data.

    Attributes by Category:
      Program Data and Parameters:
        activity:          sub-class of project which defines the configuration
        boresight_manager: (BoresightManager) post processing manager object
                           for retrieving old boresight results.
        configs:           a list of all known hardware configurations
        fe_signals
        #specQueue
        specHandler
        info:              (dict) dictionary containing information about current
                           status of different long running calibration and
                           observation methods, as well as sources, and verifiers.
        last_rec
        last_scan
        log_n_avg
        lock
        logger
        n_scans:           (int) number of scans in current sequence
        rx_signals
      Observing parameters:
        bandwidth
        beams
        el_offset
        elevation
        humidity
        location
        observatory:      (MonitorControl.Observatory) Observatory instance
        obsfreq
        obsmode
        pols
        pressure
        record_int_time
        restfreq
        SB
        signal_end
        styles
        telescope
        temperature
        winddirection
        windspeed
        xel_offset
      Source Information:
        activity
        azimuth
        dec
        ordered
        RA
        source
      Data:
        bintabHDU
        dims
        filename
        gallery
        hdulist
        HDUs
        fitsfile
        polcodes
        scans
      Equipment:
        equipment:         (dict) dictionary describing antenna/station hardware
        frontend
        receiver
        patchpanel
        backend
        roachnames
        num_chan


    Methods:
      Start-up and shut-down methods:
          __init__(...)
        set_info(path, val)
        get_info(path=None)
        save_info()
        load_info()
        close()
      Hardware control:
        configure(import_path, *args, **kwargs)
        hdwr(hdwr, method_name, *args, **kwargs)
        list_hdwr()
      Source management:
        load_sources(loader="json")
        get_sources(source_names=None, when=None, filter_fn=None, formatter=None)
        report_source_info(name_or_dict, units="degrees")
        is_within(name_or_dict, bounds, axis="el")
        _get_source_from_str_or_dict(name_or_dict, **kwargs)
        _get_src_info_dict(src_dict)
        _add_src_info_to_file(f_obj, src_dict)

      Observatory details:
        _get_observer_info_dict()

      Antenna control:
        point(name_or_dict)

      Data acquisition}:
        get_tsys(timestamp=False): return list of Tsys obtained from HP power meters
        single_scan(feed, scan_time=60.0, integration_time=5.0): returns a single
          spectrum
        two_beam_nod(cycles=1, scan_time=60.0, integration_time=None): starts a
          sequence of spectral scans in beam and position switching mode
        single_beam_nodding(cycles=1, time_per_scan=60.0, integration_time=5.0,
          power_meter_monitor_interval=2.0, antenna_monitor_interval=2.0): starts
          a position switching sequence

      Calibration:
        scanning_boresight(el_previous_offset, xel_previous_offset,
          limit=99.0, sample_rate=0.3, rate=3.0, settle_time=10.0,
          src_name_or_dict=None,two_direction=True, additional_offsets=None,
          channel=0, attrs=None)
        stepping_boresight(el_previous_offset, xel_previous_offset,
          n_points=9, integration_time=2, settle_time=10.0, two_direction=True,
          src_name_or_dict=None, additional_offsets=None, channel=0, attrs=None)
        get_boresight_analyzer_object(file_path)
        get_most_recent_boresight_analyzer_object()
        process_minical_calib(cal_data, Tlna=25, Tf=1, Fghz=20, TcorrNDcoupling=0)
        tsys_calibration(settle_time=10.0, pm_integration_time=5.0)
        stop_tsys_calibration()
        tip()

      File management:
        _create_calibration_file_path(...):
        _create_calibration_file_obj(...):
        get_boresight_file_paths(...):

      Miscellaneous:
        server_time(): returns current time

    Pyro5Server Initialization Arguments(**kwargs):
      cls:        a class whose methods and attribute the server accesses by
                  instantiating an object.
      obj:        an object whose methods and attributes the server accesses.
      cls_args:
      cls_kwargs:
      name:       optional; defaults to class name
      logger:     optional logger; defaults to Pyro5Server logger
      kwargs:     EventEmitter keyword arguments
    """
    fillcolors = {
      "antenna":            "#FF4136",
      "calibrator":         "#B10DC9",
      "catalog-priority-1": "#001F3F",
      "catalog-priority-2": "#0074D9",
      "catalog-priority-3": "#7FDBFF",
      "catalog-priority-4": "#39CCCC",
      "catalog-priority-5": "#94D6E7",
      "catalog-priority-6": "#52B552",
      "catalog-priority-7": "#A5DE94",
      "catalog-priority-8": "#E78CC6",
      "catalog-priority-9": "#D66321",
      "catalog-priority-15":  "#CE84C6",
      "catalog-attention":    "#FFD7B5",
      "catalog-done":         "#F7FFCE",
      "catalog-far":          "#E0E0E0",
      "catalog-intermediate": "#A1A1A1",
      "catalog-near":         "#404040",
      "known-HII":            "#FFFF10",
      "known-line-source":    "#D6EF39",
      "known-maser":          "#FF851B"
    }
    order = [
      "antenna", "calibrator",
      "catalog-priority-1", "catalog-priority-2", "catalog-priority-3",
      "catalog-priority-4", "catalog-priority-5", "catalog-priority-6",
      "catalog-priority-7", "catalog-priority-8", "catalog-priority-9",
      "catalog-priority-15",
      "catalog-attention", "catalog-done",
      "catalog-far", "catalog-intermediate", "catalog-near",
      "known-HII", "known-line-source", "known-maser"]
      
    def __init__(self, context,        # required
                       project="TAMS",
                       import_path=None,
                       config_args=None,
                       config_kwargs=None,
                       boresight_manager_file_paths=None,
                       boresight_manager_kwargs=None,
                       **kwargs):
        """
        initialize a DSSServer

        Args:
            observatory: see class documentation
            equipment: see class documentation
            import_path: (str) a path whose corresponding module
                has a station_configuration function
            config_args: (tuple/list) passed to station_configuration
            config_kwargs: (dict) passed to station_configuration
            boresight_manager_file_paths: t.b.d.
        """
        super(DSSServer, self).__init__(obj=self, **kwargs)

        # a valid project must be provided
        if project not in projcfg.get_projects():
          self.logger.error("__init__: %s not recognized", project)
          raise RuntimeError("%s is invalid projecty" % project)
        self.logger.debug("__init__: project is %s", project)
        self.project = project
        self.project_dir = projects_dir + self.project + "/"
        self.project_conf_path = proj_conf_path + self.project + "/"
        self.status_dir = self.project_dir+ "Status/"+ self.__class__.__name__ + "/"
        # get a dict with context names and paths to their configurations
        self.configs = self.get_configs()
        self.logger.debug("__init__: configurations: %s", self.configs)
        # allow for non-standard configurations; needed even without hardware
        # this creates attributes:
        #    observatory
        #    equipment
        self._config_hw(context,
                        import_path=import_path,
                        config_args=config_args,
                        config_kwargs=config_kwargs)
        # initialize a boresight manager
        self._config_bore(boresight_manager_file_paths=boresight_manager_file_paths,
                          boresight_manager_kwargs=boresight_manager_kwargs)
        self._init_info()
        self.activity = None
        # categories present in the current set of sources in the correct order
        self.ordered = []
        # gallery of spectra by scan and record
        self.gallery = {}
        # convenient attributes
        self.telescope = self.equipment['Antenna']
        self.frontend = self.equipment['FrontEnd']
        self.receiver = self.equipment['Receiver']
        self.patchpanel = self.equipment['IF_switch']
        self.backend = self.equipment['Backend']
        self.logger.debug("__init__: backend is %s", self.backend)
        self.roachnames = self.backend.roachnames
        # initialize a FITS file
        self.initialize_FITS()
        # keep track of scans received
        self.scans = [] # don't confuse with self.backend.scans
        # telescope location
        self.logger.debug("__init__: empty scans file created")
        longitude = -self.telescope.long*180/math.pi # east logitude
        latitude = self.telescope.lat*180/math.pi
        height = self.telescope.elevation
        self.location = astropy.coordinates.EarthLocation(lon=longitude,
                                                          lat=latitude,
                                                          height=height)
        self.logger.debug("__init__: telescope location defined")
        # signal properties
        self.get_signals()
        # observing mode
        self.obsmode = obsmode
        self.restfreq = restfreq
        # JSON file on client host
        #self.last_spectra_file = "/var/tmp/last_spectrum.json"
        #self.backend.init_disk_monitors()
        #self.backend.observer.start() <<<<<<<<<<<<<< not working; maybe not needed
        #self.specQueue = queue.Queue()
        self.specHandler = ActionThread(self, self.integr_done,
                                        name="specHandler")
        #self.specHandler = threading.Thread(target=self.integr_done,
        #                                    name="specHandler")
        self.specHandler.daemon = True
        self.specHandler.start()
        self.logger.debug("__init__: done")

    def initialize_FITS(self):
        """
        initialize a FITS file
        """
        self.fitsfile = FITSfile(self.telescope)
        # initialize a list of extensions; the first is the primary
        self.HDUs = [self.fitsfile.prihdu] # FITS extensions
        # initialize a SDFITS binary table
        # default to SAO configuration
        # 32768 ch, one position, two pols, 60 integrations, 2 beams
        self.dims = [32768,1,1,2,50,2]
        self.bintabHDU = self.init_binary_table()
        self.logger.debug("initialize_FITS: empty binary table received")
        self.HDUs.append(self.bintabHDU)
        self.hdulist = pyfits.HDUList(self.HDUs)
        self.logger.debug("initialize_FITS: HDU list created")
        self.filename = "/var/tmp/test-"+str(time.time())+".fits"

    def init_binary_table(self, numscans=100, observer="Horiuchi"):
        """
        Here 'observer' is used in the TAMS sense -- a person.  Elsewhere
        'observer' is used in the ephem sense -- a location.
        """
        self.fitsfile.exthead = self.fitsfile.make_basic_header()
        # start the extension header
        self.fitsfile.exthead['projid']   = self.info['project']['name']
        self.fitsfile.exthead['observer'] = observer
        self.fitsfile.exthead['FRONTEND'] = self.equipment['FrontEnd'].name
        self.fitsfile.exthead['RECEIVER'] = self.equipment['Receiver'].name
        # convenient names
        nchan  = self.dims[0]
        nlong  = self.dims[1]
        nlat   = self.dims[2]
        npols  = self.dims[3]
        nrecs  = self.dims[4]
        nbeams = self.dims[5]
        # adjust for X frontend and receiver
        self.logger.info("make_SAO_table: receiver is %s",
                         self.equipment['Receiver'])
        if type(self.equipment['Receiver']) == DSN_rx:
          nbeams = 1
          self.logger.debug("init_binary_table: DSN receivers have one beam")
        else:
          self.logger.debug("init_binary_table: receiver has %d beams", nbeams)

        # add the site data
        self.fitsfile.add_site_data(self.fitsfile.exthead)

        # make the basic columns that are always needed
        self.fitsfile.make_basic_columns()

        # add the backend data
        freqs = self.backend.freqs
        num_chan = len(freqs)
        self.fitsfile.exthead['FREQRES'] = freqs[-1]/(num_chan-1)
        self.fitsfile.exthead['BANDWIDt'] = num_chan*self.fitsfile.exthead['FREQRES']
        self.fitsfile.get_hardware_metadata(self.backend)

        # add multi-dimensioned metadata
        self.fitsfile.add_time_dependent_columns(nrecs)

        # beam offsets
        self.fitsfile.make_offset_columns(numrecs=nrecs)

        # column for TSYS, one value for each IF
        if nbeams == 1:
          tsys_dim = "(1,1,1,2,"+str(nrecs)+")"
          unit = "count"
        else:
          tsys_dim = "(1,1,1,2,"+str(nrecs)+",2)"
          unit = "K"
        self.logger.debug("init_binary_table: TSYS dim is %s", tsys_dim)
        self.fitsfile.columns.add_col(pyfits.Column(name='TSYS',
                                      format=str(2*nrecs*2)+'D',
                                      dim=tsys_dim,
                                      unit=unit))

        # Add columns describing the data matrix
        #   Note that refpix defaults to 0
        axis = 1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                      self.fitsfile.columns, axis,
                                      nchan, 'FREQ-OBS', 'D', unit='Hz',
                                      comment="channel frequency in telescope frame")

        axis +=1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                      self.fitsfile.columns, axis,
                                      nlong, 'RA---GLS', 'D', unit='deg',
                                      comment="RA J2000.0")
        axis +=1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                      self.fitsfile.columns, axis,
                                      nlat, 'DEC--GLS','D', unit='deg',
                                      comment="decl. J2000")
        #   Stokes axis
        #     get the polarizations from the spectrometer input signals
        axis+=1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                     self.fitsfile.columns, axis,
                                     npols, 'STOKES',  'I',
                                     comment="polarization code: -8 ... 4")
        #   time axis
        axis+=1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                     self.fitsfile.columns, axis,
                                     nrecs, 'TIME', 'E', unit='s',
                                     comment='Python time.time() value')
        #   Beam axis
        if nbeams > 1:
          axis+=1; self.fitsfile.make_data_axis(self.fitsfile.exthead,
                                      self.fitsfile.columns, axis,
                                      nbeams, 'BEAM',    'I',
                                      comment="beam 1 or 2")

        # Make the DATA column
        fmt_multiplier = self.fitsfile.exthead['MAXIS1']*self.fitsfile.exthead['MAXIS2']* \
                         self.fitsfile.exthead['MAXIS3']*self.fitsfile.exthead['MAXIS4']* \
                         self.fitsfile.exthead['MAXIS5']
        if nbeams > 1:
           fmt_multiplier *= self.fitsfile.exthead['MAXIS6']
        self.logger.debug("init_binary_table: format multiplier = %d", fmt_multiplier)
        dimsval = "("+str(self.fitsfile.exthead['MAXIS1'])+"," \
                     +str(self.fitsfile.exthead['MAXIS2'])+"," \
                     +str(self.fitsfile.exthead['MAXIS3'])+"," \
                     +str(self.fitsfile.exthead['MAXIS4'])+"," \
                     +str(self.fitsfile.exthead['MAXIS5'])+")"
        if nbeams > 1:
          dimsval = dimsval[:-1] + ","+str(self.fitsfile.exthead['MAXIS6'])+")"
        self.logger.debug("init_binary_table: computed scan shape: %s", dimsval)
        data_format = str(fmt_multiplier)+"E"
        self.logger.debug("init_binary_table: data_format = %s", data_format)
        self.fitsfile.columns.add_col(pyfits.Column(name='DATA', format=data_format,
                             dim=dimsval))
        self.logger.debug("init_binary_table: table columns created")
        # create the table extension
        FITSrec = pyfits.FITS_rec.from_columns(self.fitsfile.columns, nrows=numscans)
        self.logger.debug("init_binary_table: FITS record built")
        tabhdu = pyfits.BinTableHDU(data=FITSrec, header=self.fitsfile.exthead,
                                name="SINGLE DISH")
        self.logger.debug("init__binary_table: empty table created")
        # empty table
        return tabhdu

    def save_FITS(self):
        """
        Save FITS HDU list to file

        The HDU structure used by this server is a pyfits.HDUList() structure
        made up from a list with a pyfits.BinTableHDU and a pyfits.PrimaryHDU()

        This creates a new HDU list structure from the attributes for only the
        rows with data.  The file name is not changed so another call to this
        will overwrite the previous contents, but presumably with more rows.
        """
        self.logger.debug("save_FITS: copying primary HDU...")
        savePriHDU = self.fitsfile.prihdu
        lastRow = np.unique(self.bintabHDU.data[:]['SCAN'])[-1]
        self.logger.debug("save_FITS: bintable has %d rows; making new table", lastRow)
        t0 = time.time()
        saveRec = pyfits.FITS_rec.from_columns(self.fitsfile.columns, nrows=max(lastRow,1))
        for row in range(1,lastRow):
          saveRec[row] = self.bintabHDU.data[row]
        saveBinTab = pyfits.BinTableHDU(data=saveRec,
                                        header=self.fitsfile.exthead,
                                        name="SINGLE DISH")
        saveHDUs = [savePriHDU, saveBinTab]
        hdulist = pyfits.HDUList(saveHDUs)
        self.logger.debug(
            "save_FITS: Took {:.3f} seconds to copy FITS data".format(
                time.time() - t0))
        t0 = time.time()
        hdulist.writeto(self.filename, overwrite=True)
        del savePriHDU
        del saveRec
        del saveBinTab
        del saveHDUs
        del hdulist
        self.logger.debug("save_FITS: wrote FITS to %s in %s s", self.filename, time.time()-t0)
        #self.save_FITS.cb({"status": "saved to %s" % self.filename})

    def _config_hw(self, context,
                       import_path=None,
                       config_args=None,
                       config_kwargs=None):
        """
        Get the equipment details for the given code
        """
        self.logger.debug("_config_hw: for %s", context)
        self.logger.debug("_config_hw: config args: %s", config_args)
        # get the hardware configuration
        if context in self.configs:
          # the usual way to get the configuration, accepting the defaults
          self.logger.debug("_config_hw: standard configuration")
          observatory, equipment = station_configuration(context, **config_args)
        else:
          # if not a standard configuration, infer from context name like PSR014L
          self.logger.debug("_config_hw: non-standard configuration")
          activity = context[:4]
          project = self.activitys_project(activity)
          dss = int(context[4:6])
          band = context[7]
          now = time.gmtime()
          timestr = "02d02d" % (now.tm_hour, now.tm_min)
          observatory, equipment = std_configuration(None, project, dss,
                                       now.tm_year, now.tm_yday, timestr, band)

        # initialize the equipment confoguration
        if import_path is not None:
            # non-standard path to the configuration file
            if config_args is None:
                # over-riding positional configuration arguments
                config_args = ()
            if config_kwargs is None:
                # over-riding keyword configuration arguments
                config_kwargs = {}
            self.configure(import_path, *config_args, **config_kwargs)
        else:
            self.observatory = observatory
            self.equipment = equipment
        self.logger.debug("_config_hw: observatory is %s", observatory)
        for item in list(equipment.keys()):
          self.logger.debug("_config_hw: %s is %s", item, equipment[item])

    def _config_bore(self, boresight_manager_file_paths = None,
                           boresight_manager_kwargs = None):
        """
        initialize the boresight manager
        """
        if boresight_manager_file_paths is None:
            # use default location of boresight files
            file_paths, boresight_manager_file_paths = \
                BSM.BoresightManager.detect_file_paths()
        if boresight_manager_kwargs is None:
            # overriding boresight manager keyword arguments
            boresight_manager_kwargs = {}
        self.boresight_manager = BSM.BoresightManager(
            boresight_manager_file_paths,
            **boresight_manager_kwargs
        )

    def _init_info(self):
        """
        initialize program parameters to defaults
        """
        tsys_cal_dir = data_dir + "tsys_cals/"
        self.info = {
            "info_save_dir": self.status_dir,
            "point": {
                "current_source": None
            },
            "boresight": {
                "running": False,
                "data_dir": tams_config.boresight_data_dir,
                "offset_el": 0.0,
                "offset_xel": 0.0
            },
            "tsys_calibration": {
                "running": False,
                'tsys_factors': [
                    999883083.3775496,
                    421958318.055633,
                    1374067124.697352,
                    705797017.1087824
                ],
                "data_dir": tsys_cal_dir,
                "date": None,
                "el": None
            },
            "tip": {
                "running": False,
                "data_dir": tams_config.tipping_data_dir,
            },
            "project": {
                "name": self.project,
                "source_dir": self.project_conf_path,
            },
            "sources": {},
            "verifiers": {},
            "calibrators": {}
        }
        self.logger.debug("_init_info({}): _info: {}".format(logtime(),self.info))

    def init_info(self, activity='TMS0'):
      """
      """
      self.project = self.get_activitys_project(activity)
      self._init_info()

    # ------------------ Start-up and shut-down methods -----------------------

    @async_method
    def set_info(self, path, val):
        """
        Set some path within ``_info`` attribute in a thread safe manner

        Examples:

            >>> server.set_info(["project", "name"],"TAMS")
            >>> server.set_info(["tip","running"],False)

        Args:
            path (list): "path", inside info property to value we want to set.
            val (obj): desired value.

        """
        self.logger.debug("set_info: called with path: {}, val: {}".format(path, val))
        with self.lock:
            info_copy = self.info
            sub_path = self.info[path[0]]
            self.logger.debug("set_info: subpath: {}".format(sub_path))
            for p in path[1:-1]:
                sub_path = sub_path[p]
                self.logger.debug("set_info: subpath: {}".format(sub_path))
            sub_path[path[-1]] = val
            self.set_info.cb() # no response to client

    @auto_test()
    @async_method
    def get_info(self, path=None):
        """
        Get some path in ``_info`` attribute in thread safe attribute
        If no path is provided, return entire ``_info`` attribute

        Examples:

            >>> server.get_info(["boresight","running"])
            False
            >>> server.get_info(["point","current_source"])
            "0521-365"

        Args:
            path (list/None): Get some value from ``_info``, or some value from a
                subdictionary of ``_info``.

        Returns:
            obj: Either value of dictionary/subditionary, or subdictionary itself.
        """
        self.logger.debug("get_info: path: {}".format(path))
        with self.lock:
            if path is None:
                self.get_info.cb(self.info) # send client the entire info dict
                return self.info
            sub_path = self.info[path[0]]
            for p in path[1:]:
                sub_path = sub_path[p]
            self.get_info.cb(sub_path) # send client the requested data
            return sub_path

    @auto_test()
    def save_info(self):
        """
        Dump internal _info attribute to a file.
        """
        # info file should go with others, not where the file was loaded from
        # if not os.path.exists(self.info["info_save_dir"]):
        #    os.makedirs(self.info["info_save_dir"])
        # self.logger.debug(
        #    "save_info: info_save_dir: {}".format(self.info["info_save_dir"]))
        timestamp = datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss")
        save_file_name = "info_{}.json".format(timestamp)
        self.info["info_save_dir"] = self.project_dir + "Status/" \
                                     + self.__class__.__name__ + "/"
        save_file_path = os.path.join(self.info["info_save_dir"], save_file_name)
        self.logger.info("save_info: Saving file {}".format(save_file_path))
        t0 = time.time()
        with open(save_file_path, "w") as f:
            json.dump(self.info, f)
        self.logger.debug(
            "save_info({}): Took {:.3f} seconds to dump info".format(logtime(),
                time.time() - t0))


    @auto_test()
    def load_info(self):
        """
        Load in _info attribute from most recently dumped settings file.
        
        This assumes a file name like "info_2020-269-22h39m15s.json"
        
        Attribute ``info`` contains parameters for an ongoing observing activity
        so ``DSSServer`` can start with the same software configuration as the
        previous time.
        
        The location of the info files is specified in the file w
        """
        save_file_dir = self.info["info_save_dir"]
        self.logger.debug(
            "load_info: Looking in {} for status files".format(save_file_dir))
        try:
          statusfiles = os.listdir(save_file_dir)
        except FileNotFoundError:
          self.logger.warning("load_info: directory not found; using defaults")
          os.makedirs(self.info["info_save_dir"])
          self.logger.info("load_info: creates %s", save_file_dir)
          return
        self.logger.debug("load_info: found %s", statusfiles)
        file_paths = []
        file_datetime_objs = []
        for f_name in statusfiles:
            if ".json" in f_name:
                try:
                    datetime_str = os.path.splitext(f_name)[0].split("_")[1]
                    datetime_obj = datetime.datetime.strptime(datetime_str, "%Y-%j-%Hh%Mm%Ss")
                    file_datetime_objs.append(datetime_obj)
                    file_paths.append(os.path.join(save_file_dir, f_name))
                except Exception as err:
                    self.logger.debug("load_info: Can't parse file name {}".format(f_name))
        if len(file_paths) > 0:
            # now order the files
            ordered_dt_objs, ordered_paths = list(zip(*sorted(zip(file_datetime_objs, file_paths))))
            # now get most recent path!
            most_recent_path = ordered_paths[-1]
            self.logger.info("load_info: Using file {} to set info".format(most_recent_path))
            # now load it into memory and set _info attribute
            t0 = time.time()
            with open(most_recent_path, "r") as f:
                # info_new = Trackable(json.load(f))
                info_new = json.load(f)
            self.info = info_new
            self.logger.debug(
                       "load_info({}): Took {:.3f} seconds to load info".format(
                          logtime(), time.time() - t0))
        else:
            self.logger.info("load_info: Couldn't find any files with which to set info")

    def close(self):
        self.logger.warning("%s closed", self)
        self.save_FITS()
        try:
          self.equipment["Antenna"].stop_recording()
        except AttributeError:
          self.logger.info("close: no Antenna defined")
        try:
          self.equipment["FrontEnd"].stop_recording()
        except AttributeError:
          self.logger.info("close: no FrontEnd defined")
        try:
          self.equipment["Receiver"].stop_recording()
        except AttributeError:
          self.logger.info("close: no Receiver defined")
        try:
          self.equipment["Backend"].stop_recording()
        except AttributeError:
          self.logger.info("close: no Backend defined")
        try:
          super(DSSServer, self).close()
        except AttributeError:
          self.logger.info("close: daemon no longer exists")

    # ---------------------- Hardware Control ---------------------------------

    def configure(self, import_path, *args, **kwargs):
        """
        Reconfigure DSS server with new hardware configuration. Sets
        ``equipment`` and ``observatory`` attributes.

        Examples:

            >>> server.configure(
                    "MonitorControl.Configurations.CDSCC.WBDC2_K2",
                    hardware={
                        "Antenna":True,
                        "Receiver":False,
                        "FrontEnd":True,
                        "Spectrometer":False
                    })

        Args:
            import_path (str): a path whose corresponding module
                has a station_configuration function
            args (tuple/list): passed to station_configuration
            kwargs (dict): passed to station_configuration
        """
        module = importlib.import_module(import_path)
        if not hasattr(module, "station_configuration"):
            msg = "imported module {} has no station_configuration callable".format(module)
            self.logger.error(msg)
            raise RuntimeError(msg)
        station_configuration = module.station_configuration
        observatory, equipment = station_configuration(*args, **kwargs)
        self.observatory = observatory
        self.equipment = equipment

    @Pyro5.api.oneway
    @async_method
    def hdwr(self, hdwr, method_name, *args, **kwargs):
        """
        Call some arbitrary method from the station's equipment.


        Examples:

        Call Antenna "get" method:

        .. code-block::python

            >>> server.hdwr("Antenna","get","AzimuthAngle")
            {"AzimuthAngle": 354.56}

        Call FrontEnd "read_PMs" and "read_temp" methods:

        .. code-block::python

            >>> server.hdwr("FrontEnd", "read_PMs")
            [(1, '2018-05-03 12:39:34', 65.14),(2, '2018-05-03 12:39:34', 66.14),
             (3, '2018-05-03 12:39:34', 70.56),(4, '2018-05-03 12:39:34', 67.47)]
            >>> server.hdwr("FrontEnd", "read_temp")
            [43.1, 54.6, 38.2, 47.3]

        Args:
            hdwr (string): the name of the hardware in self.equipment
            method_name (string): The name of the method to call
            *args: To be passed to hdwr.method_name
            **kwargs: To be passed to hdwr.method_name

        Returns:
            results of hdwr, if not interacting with server remotely.
        """
        self.logger.debug("hdwr({}): {} method '{}' called".format(
                                                  logtime(), hdwr, method_name))
        if hdwr not in self.equipment:
            raise MonitorControlError([], "Couldn't find {} in equipment".format(hdwr))
        elif self.equipment[hdwr].hardware == False:
          result = self.emulate(hdwr, method_name)
        else:
          hdwr_obj = self.equipment[hdwr]
          self.logger.debug("hdwr: hardware is %s", hdwr_obj)
          try:
              method = getattr(hdwr_obj, method_name)
              self.logger.debug("hdwr(%s): calling method %s", logtime(),method)
              if callable(method):
                self.logger.debug("hdwr: with args: {}".format(args))
                self.logger.debug("hdwr: and kwargs: {}".format(kwargs))
                result = method(*args, **kwargs)
              else:
                result = method # accessing an attribute
              self.logger.debug("hdwr: result: %s", result)
          except AttributeError as err:
            raise MonitorControlError([],
                     "Couldn't find method {} for {}".format(method_name, hdwr))
        try:
          self.parse_result(result)
        except Exception as details:
          raise MonitorControlError([], "parsing {} failed".format(result))
        self.hdwr.cb(result) # send client the result
        return result

    def emulate(self, hdwr, method_name):
        """
        This will help the client that uses the 'hdwr' command, but does not
        emulate server commands called by this program.  That requires
        emulation in the equipment server itself.
        """
        self.logger.debug("emulate: called %s method %s", hdwr, method_name)
        if hdwr == "Backend":
          if method_name == "roachnames":
            return ['sao64k-1', 'sao64k-2', 'sao64k-3', 'sao64k-4']
        elif hdwr == "FrontEnd":
          if method_name == "read_PMs":
            # this is ad hoc based on the calibration values stored on disk
            return [(1, 1.8e-08*(1+random.normalvariate(1,0.002))), 
                    (2, 2.0e-08*(1+random.normalvariate(1,0.002))), 
                    (3, 3.8e-08*(1+random.normalvariate(1,0.002))), 
                    (4, 3.0e-08*(1+random.normalvariate(1,0.002)))]
        else:
          self.logger.debug("emulate: not coded for %s.%s()", hdwr, method_name)

    def get_antenna_angles(self):
        self.hdwr("Antenna", "get", "AzimuthAngle",
                                    "ElevationAngle",
                                    "ElevationPositionOffset",
                                    "CrossElevationPositionOffset")

    def get_weather(self):
        self.hdwr("Antenna", "get", "temperature",
                                    "pressure",
                                    "windspeed",
                                    "winddirection",
                                    "humidity")

    def parse_result(self, result):
      if type(result) == dict:
        if 'AzimuthAngle' in result:
          self.azimuth = float(result['AzimuthAngle'])

        if "ElevationAngle" in result:
          self.elevation = float(result["ElevationAngle"])

        if 'CrossElevationPositionOffset' in result:
          self.xel_offset = float(result['CrossElevationPositionOffset'])

        if 'ElevationPositionOffset' in result:
          self.el_offset = float(result['ElevationPositionOffset'])

        if 'temperature' in result:
          self.temperature = float(result['temperature'])

        if 'pressure' in result:
          self.pressure = float(result['pressure'])

        if 'humidity' in result:
          self.humidity = float(result['humidity'])

        if 'windspeed' in result:
          self.windspeed = float(result['windspeed'])

        if 'winddirection' in result:
          self.winddirection = float(result['winddirection'])
      else:
        self.logger.info('parse_result: %s', result)

    @auto_test()
    def list_hdwr(self):
        """List available hardware, or the keys of ``equipment`` attribute"""
        self.logger.debug("list_hdwr: Called.")
        hdwr = list(self.equipment.keys()) # force use of list in Python3
        return hdwr


    # ------------------------- Source Management -----------------------------

    @async_method
    def load_sources(self, loader="json"):
        """
        Load sources and verifiers into memory
        Must call this before calling ``get_sources``, or another method that uses
        sources.

        This is now obsolete
        """
        sources, verifiers, calibrators = self.get_sources_and_verifiers("TAMS")

        self.info["sources"].update(sources)
        self.info["verifiers"].update(verifiers)
        #send requested info to client
        self.load_sources.cb({"sources": sources, "verifiers": verifiers})

    def get_sources_and_verifiers(self, project_or_activity):
        """
        returns contents of 'calibrators', 'sources', and 'verifiers' files
        """
        # try activities first
        projects = self.get_projects()
        project = self.info['project']['name']
        if project_or_activity == project:
          # its a project
          path = proj_conf_path + project + "/"
        elif project_or_activity in projects[project_or_activity]:
          # it's a project activity
          path = proj_conf_path + project_or_activity+"/"
        else:
          self.logger.error(
                  "get_sources_and_verifiers: activity or project %s not found",
                  project_or_activity)
          return None
        self.logger.debug("get_sources_and_verifiers(%s): path is %s",
                                                                logtime(), path)
        with open(path+"sources.json", "r") as f:
            sources = json.load(f)
        with open(path+"verifiers.json", "r") as f:
            verifiers = json.load(f)
        with open(proj_conf_path+"calibrators.json", "r") as f:
            calibrators = json.load(f)
        return sources, verifiers, calibrators

    @Pyro5.api.oneway
    def get_source_names(self, project_or_activity):
        """
        returns names of sources in catalogs
        """
        if "sources" in self.info   and len(self.info['sources']) and \
           "verifiers" in self.info and len(self.info['verifiers']) and \
           "calibrators" in self.info and len(self.info['calibrators']):
          # if the info items exist and are not empty
          sources = self.info["sources"]
          verifiers = self.info["verifiers"]
          calibrators = self.info["calibrators"]
        else:
          sources, verifiers, calibrators = self.get_sources_and_verifiers(
                                                           project_or_activity)
          #self.info["sources"].update(sources)
          #self.info["verifiers"].update(verifiers)
          self.info["sources"] = sources
          self.info["verifiers"] = verifiers
          self.info["calibrators"] = calibrators

        sourcenames = list(sources.keys()) + \
                      list(verifiers.keys()) + \
                      list(calibrators.keys())
        sourcenames.sort()
        self.logger.debug("get_source_names: returns %d names\n",
                                                               len(sourcenames))
        self.get_source_names.cb(sourcenames)
        return sourcenames

    @Pyro5.api.oneway
    def get_sources_data(self, activity_or_project, source_names=None, when=None,
                               filter_fn=None, formatter=None):
        """
        Gives the same response as 'get_sources' but can handle other projects.

        This does not require 'load_sources'.  It will take care of that if
        sources have not yet been loaded
        """

        def get_source(name):
            """
            Converts Python dict to Javascript object

            It also determines keys missing from the Python dict and adds those.
            The program requires the "category" item and the expected ones are:
            'catalog sources' (research targets), 'known sources' (similar to
            research targets), and (pointing) 'calibrators'.
            """
            # from either 'sources' or 'verifiers', figure out the category
            if name in self.info["sources"]:
              # an item in "sources" should have a key "category"
              if "category" in self.info["sources"][name]:
                if len(self.info["sources"][name]["category"]) > 1:
                  # we ignore sources with "done" in category
                  if self.info["sources"][name]["category"][1] == "done":
                    self.logger.info("get_sources_data.get_source: this source is done")
                    return None
              else:
                # create a category item.
                if "priority" in self.info["sources"][name]:
                  # turn the priority item in a category item
                  self.info["sources"][name]["category"] = ["catalog",
                     "priority " + str(self.info["sources"][name]["priority"])]
                else:
                  # if no priority, maybe it's a known source:
                  if 'N' in self.info["sources"][name]:
                    self.info["sources"][name]["category"] = ['known HII']
                  elif 'linefreq' in self.info["sources"][name]:
                    self.info["sources"][name]["category"] = [
                                                           'known line source']
                  elif 'flux' in self.info["sources"][name]:
                    # this should be in verifiers
                    self.logger.error(
                        "get_sources_data.get_source: %s should be a verifier",
                        name)
                  else:
                    self.info["sources"][name]["category"] = ["catalog",
                                                            "priority 9"]
              #self.logger.debug(
              #         "get_sources_data.get_source: source %s category is %s",
              #                    name, self.info["sources"][name]["category"])
              # This is to get the name into the info for this source
              if "name" in self.info["sources"][name]:
                pass
              else:
                self.info["sources"][name]["name"] = name
              # needed for key and label
              this_source = self.info["sources"][name]
            elif name in self.info["verifiers"]:
              # This is to get the name into the info for this source
              if "name" in self.info["verifiers"][name]:
                pass
              else:
                self.info["verifiers"][name]['name'] = name
              # create a verifier category if necessary
              if "category" in self.info["verifiers"][name]:
                # this is TAMS: take it
                pass
              # see if it is a line source
              elif 'N' in self.info["verifiers"][name]:
                self.info["verifiers"][name]["category"] = ['known HII']
              elif "linefreq" in self.info["verifiers"][name]:
                self.info["verifiers"][name]["category"] = ['known line source']
              elif "flux" in self.info["verifiers"][name]:
                # assume any other source with a flux is a calibrator
                self.info["verifiers"][name]["category"] = ["calibrator"]
                # make flux a dict if necessary
                if type(self.info["verifiers"][name]["flux"]) == dict:
                  # this is a dict -- OK
                  pass
                else:
                  # assume the flux is a number
                  if "linefreq" in self.info["verifiers"][name]:
                    freq = self.info["verifiers"][name]["linefreq"]/1000. # GHz
                  elif "freq" in self.info["verifiers"][name]:
                    freq = self.info["verifiers"][name]["freq"]/1000.     # GHz
                  elif "N" in self.info["verifiers"][name]:
                    freq = recomb_freq(self.info["verifiers"][name]['N'],1,1,'H')
                  else:
                    freq = self.equipment['FrontEnd']['frequency']
                  band = frequency_to_band(freq)
                  flux = self.info["verifiers"][name]["flux"]
                  self.info["verifiers"][name]["flux"] = {band: flux}
              else:
                # no category and no flux
                return None
              #self.logger.debug("get_sources_data.get_source: verifier %s category is %s",
              #                  name, self.info["verifiers"][name]["category"])
              # needed for key and label
              this_source = self.info["verifiers"][name]
            elif name in self.info["calibrators"]:
              # We should not need to check for "category" since the
              # calibrators file was created that way.  Also, we don't need
              # to verify that "calibrator" in is "category" or that it has
              # a flux.
              # What we do need is a frequency to get the right flux
              freq = self.equipment['FrontEnd']['frequency']
              band = frequency_to_band(freq)
              flux = self.info["calibrators"][name]["flux"]
              self.info["calibrators"][name]["flux"] = {band: flux}
              this_source = self.info["calibrators"][name]
            else:
              # not in any source list
              return None
            return this_source # ---------------------------- end of get_source

        def make_plot_symbol_style(sourcedata):
            """
            creates a key and a label for each source category

            The key is a hyphen-joined string derived from
            ['catalog', 'priority X']
            """
            if sourcedata == None:
              self.logger.warning("get_sources_data.make_plot_symbol_style: no data for this source")
              return None
            if "category" in sourcedata:
              pass
            else:
              self.logger.debug(
                 "get_sources_data.make_plot_symbol_style: %s has no category key",
                 sourcedata['name'])
              return None

            # styles key
            # first replace space with hyphens in each list item
            newlist = []
            for item in sourcedata["category"]:
              newlist.append(item.replace(" ","-"))
            # join the list items with a hyphen
            sourcedata['key'] = "-".join(newlist)

            # label for styles parameter 'class'
            if len(sourcedata["category"]) == 1: # e.g.'calibrators','known masers'
              label = make_title(sourcedata["category"][0])+"s"
            elif len(sourcedata["category"]) == 2: # e.g.['catalog','priority 1']
              if sourcedata["category"][0] == "catalog":
                label = make_title(sourcedata["category"][1])
              else:                             # e.g. ['known', 'HII']
                label = make_title(sourcedata["category"][1])+"s"
            else:
              label = " ".join(sourcedata["category"]) # weird unexpected case
            sourcedata['label'] = label
            #self.logger.debug("make_plot_symbol_style: key: %s, label: %s",
            #                  sourcedata['key'],sourcedata['label'])

            # styles parameter 'opacity'
            sourcedata['opacity'] = 0.8

            # styles parameter 'r'
            def radius():
              freq = self.equipment['FrontEnd']['frequency']
              band = frequency_to_band(freq)
              try:
                flux = float(sourcedata['flux'][band])
              except KeyError:
                flux = 0.
              return flux+3.
            if sourcedata['key'] == "calibrator":
              sourcedata['r'] = radius()
            else:
              sourcedata['r'] = 8

            # styles parameter 'fill'
            sourcedata['fill'] = DSSServer.fillcolors[sourcedata['key']]
            return sourcedata # ---------------- end of make_plot_symbol_style

        if filter_fn is None:
            # include all sources
            def filter_fn(src_dict):
                """
                If specified, 'filter_fn' returns True only for the sources to
                be included.  This defaults them all to True
                """
                return True

        # get source data from 'self.info' or from files if necessary.
        sources, verifiers, calibrators = self.get_sources_and_verifiers(
                                                           activity_or_project)
        #self.logger.debug("get_sources_data: sources: %s", sources.keys())
        #self.logger.debug("get_sources_data: verifiers: %s", verifiers.keys())

        # get a list of source names so 'get_source' can process each source
        if source_names is None:
          source_names = self.get_source_names(activity_or_project)
        elif source_names == "verifiers":
          source_names = list(self.info["verifiers"].keys())
        elif source_names == "sources":
          source_names = list(self.info["sources"].keys())
        self.logger.debug("get_sources_data(%s): for %s", 
                                                        logtime(), source_names)

        # set time or default to now; this is the time used for the sky plot
        if when is None:
            when = ephem.now()
        if hasattr(when, "format"):
            when = datetime.datetime.strptime(when, formatter)

        # convert single source name to a list
        if not isinstance(source_names, list):
            source_names = [source_names]


        # continue to process as in get_sources
        self.equipment["Antenna"].date = when
        self.logger.debug(
                      "get_sources_data.get_sources: reformatting Antenna's date to {}".format(when))

        # returns {"lat":..., "long":..., "elev":..., "epoch":..., "date":...}
        observer_info = self._get_observer_info_dict()

        # make a Javascript compatible object
        sources = {}
        order = []
        for source_name in source_names:
            source_info = make_plot_symbol_style(get_source(source_name))
            #self.logger.debug("get_sources_data: %s info: %s", source_name, source_info)
            if source_info is not None:
                # extends ephem.FixedBody with methods to_dict() and from_dict()
                b = SerializableBody()
                try:
                  b._ra = source_info["ra"]
                except KeyError:
                  b._ra = source_info["RA"]
                b._dec = source_info["dec"]
                b.name = source_name
                b.info = {key: source_info[key]
                            for key in source_info if key not in ["RA", "ra", "dec"]}
                b.observer_info = observer_info
                # enables computation of topocentric data like 'az' and 'el'
                b.compute(self.equipment["Antenna"])
                source = b.to_dict()
                #self.logger.debug("get_sources_data: source is %s", source)
                # apply filter function if specified
                if filter_fn(source):
                    sources[source_name] = source
            else:
                self.logger.error(
                    "get_sources_data: No data for source {}".format(source_name))
        now = ephem.now()
        self.logger.debug(
            "get_sources_data: setting Antenna's date to {}".format(now))
        self.equipment["Antenna"].date = now # reset time to compute new data

        def get_ordered_categories(sources):
          ordered = []
          styles = {}
          for key in DSSServer.order:
            # check if the key is used in any source
            for name in list(sources.keys()):
              if sources[name]['info']['key'] == key:
                # do we already have this key?
                if key in ordered:
                  # next sources
                  break
                else:
                  ordered.append(key)
                  styles[key] = {}
                  styles[key]['class']   = sources[name]['info']['category']
                  styles[key]['fill']    = sources[name]['info']['fill']
                  styles[key]['opacity'] = sources[name]['info']['opacity']
                  styles[key]['r']       = sources[name]['info']['r']
                  styles[key]['display'] = sources[name]['info']['label']
          return ordered, styles

        self.ordered, self.styles = get_ordered_categories(sources)
        self.get_sources_data.cb(sources) # send client the dict 'sources'

        if len(sources) == 1:
            return sources[list(sources.keys())[0]]
        else:
            return sources
        return

    @async_method
    def get_styles(self):
      self.get_styles.cb(self.styles)
      return self.styles

    @async_method
    def get_ordered(self):
      self.get_ordered.cb(self.ordered)
      return self.ordered

    @async_method
    def get_sources(self, source_names=None, when=None, filter_fn=None,
                    formatter=None):
        """
        Get information about sources or verifiers, including current az/el.

        Examples:

            >>> server.get_sources() # get all sources and verifiers
            >>> server.get_sources("verifiers") # get all verifiers
            >>> server.get_sources("sources") # get all non-verfier sources
            >>> server.get_sources("0521-365") # get information about source
                                               # 0521-365 specifically.

            >>> now = datetime.datetime.utcnow()
            >>> server.get_sources(when = now + datetime.timedelta(minutes = 5))
                                # calculate source positions 5 minutes from now

            >>> server.get_sources(when = "2018-05-03 12:39:34",
                                   formatter = "%Y-%m-%d %H:%M:%S")
                                   # provide formatter if when is a string

        We can use ``filter_fn`` to select specific sources.

        .. code-block::python

            from MonitorControl.apps.clients.cli.filter_fn import find_up
            from MonitorControl.apps.clients.cli.filter_fn import find_bright
            # only return sources about elevation 18.
            server.get_sources(filter_fn=find_up(el_thresh=18.0))
            # get only verifiers whose K-band flux is about 5 Jy.
            server.get_sources(filter_fn=find_bright(thresh=5.0))

        Args:
            source_names (list/str, optional): A list of the names of sources
                for which to get az/el information
            when (datetime.datetime/ephem.Date/str, optional): A date time
                object, ephem date, or string that indicates when we should
                calculate source coordinates. Defaults to now. If string, must
                follow formatter
            filter_fn (callable, optional): function used to filter out sources
            formatter (str, optional): Used with datetime.datetime.strptime to
                form datetime object when `when` is string.

        Returns:
            dict: dictionary whose keys are source names, and values are dictionaries
                with source descriptions.

        """
        #self.logger.debug("get_sources: entered with source names: {}".format(source_names))
        if formatter is None: formatter = "%Y-%j-%Hh%Mm%Ss"

        # the first part can be replaced with get_source_names()
        if source_names is None:
            source_names = list(self.info["sources"].keys()) + \
                           list(self.info["verifiers"].keys()) + \
                           list(self.info["calibrators"].keys())
        elif source_names == "verifiers":
            source_names = list(self.info["verifiers"].keys())
        elif source_names == "sources":
            source_names = list(self.info["sources"].keys())
        elif source_names == "calibrators":
            source_names = list(self.info["calibrators"].keys())
        #self.logger.debug("get_sources: source names: {}".format(source_names))

        # set time or default to now
        if when is None:
            when = ephem.now()
        if hasattr(when, "format"):
            when = datetime.datetime.strptime(when, formatter)

        # convert a single source to list of one item
        if not isinstance(source_names, list):
            source_names = [source_names]

        if filter_fn is None:
            # include all sources
            def filter_fn(src_dict):
                return True
        #self.logger.debug("get_sources: after filter, source names: {}".format(source_names))

        def get_source(name):
            """
            Find the source in whatever catalog it exists
            """
            if name in self.info["sources"]:
                return self.info["sources"][name]
            elif name in self.info["verifiers"]:
                return self.info["verifiers"][name]
            elif name in self.info["calibrators"]:
                return self.info["calibrators"][name]
            else:
                return None

        # Not clear what the logic is here.  I guess it depends on what
        # attribute 'date' is.
        current_when = self.equipment["Antenna"].date
        self.logger.debug(
                "get_sources: Antenna's current date: {}".format(current_when))
        # Anyway, 'current_when' is not used.
        self.equipment["Antenna"].date = when
        #self.logger.debug(
        #              "get_sources: reformatting Antenna's date to {}".format(when))

        # returns {"lat":..., "long":..., "elev":..., "epoch":..., "date":...}
        observer_info = self._get_observer_info_dict()

        sources = {}
        for source_name in source_names:
            source_info = get_source(source_name)
            if source_info is not None:
                # extends ephem.FixedBody with methods to_dict() and from_dict()
                b = SerializableBody()
                b._ra = source_info["ra"]
                b._dec = source_info["dec"]
                b.name = source_name
                b.info = {key: source_info[key]
                            for key in source_info if key not in ["ra", "dec"]}
                b.observer_info = observer_info
                # enables computation of topocentric data like 'az' and 'el'
                b.compute(self.equipment["Antenna"])
                source = b.to_dict()
                if filter_fn(source):
                    sources[source_name] = source
            else:
                self.logger.error(
                    "get_sources: Couldn't find source {}".format(source_name))
        now = ephem.now()
        self.logger.debug(
            "get_sources: setting Antenna's date to {}".format(now))
        self.equipment["Antenna"].date = now # reset time to compute new data
        self.get_sources.cb(sources) # send client the dict 'sources'
        if len(sources) == 1:
            return sources[list(sources.keys())[0]]
        else:
            return sources

    def report_source_info(self, name_or_dict, units="degrees"):
        """
        Create a descriptive string about a given source.

        Examples:

            >>> server.report_source_info("0521-365")
            ["0521-365: az el: 221.960453 -0.494930",
            "0521-365: ra dec: 80.893983 -36.447495",
            "0521-365: J2000 ra dec: 80.741603 -36.458570"]

        Args:
            name_or_dict (str/dict): The name of a source or verifier
                or a dictionary containing its calculated position
            units (str, optional): units in which to report source coordinates.
        Returns:
            str: description of source
        """
        if units.lower() == "degrees" or units.lower() == "deg":
            convert = 180./np.pi
        elif units.lower() == "radians" or units.lower() == "rad":
            convert = 1.0

        if hasattr(name_or_dict, "keys") and hasattr(name_or_dict, "__iter__"):
            src_name = name_or_dict["name"]
        else:
            src_name = name_or_dict

        src_info0 = self.get_sources(source_names=src_name)
        src_info1 = self.get_sources(source_names=src_name,
            when=datetime.datetime.utcnow()+datetime.timedelta(minutes=5))

        if src_info1["el"] > src_info0["el"]:
            rising = "rising"
        else:
            rising = "setting"

        self.logger.debug(
            "report_source_info: {}, {}".format(src_name, src_info0))
        lines = []
        if "info" in src_info0:
            lines.append(
                "{}: extra info: {}".format(src_name, src_info0["info"]))
        lines.append(
            "{}: az el: {:.6f} {:.6f}".format(
                src_name, src_info0["az"]*convert, src_info0["el"]*convert))
        lines.append(
            "{}: ra dec: {:.6f} {:.6f}".format(
                src_name, src_info0["ra"]*convert, src_info0["dec"]*convert))
        lines.append(
            "{}: J2000 ra dec: {:.6f} {:.6f}".format(
                src_name, src_info0["_ra"]*convert, src_info0["_dec"]*convert))
        lines.append(
            "{}: {}".format(src_name, rising))
        return lines

    def is_within(self, name_or_dict, bounds, axis="el"):
        """
        Determine whether a source is within certain coordinate bounds.

        Examples:

        Determine if a given source is in DSS-43's sensitivity sweet spot,
        between 40 and 60 degrees elevation.

        .. code-block::python

            >>> server.is_within("0521-365",(40,60))
            False
            >>> server.is_within("g1107264_302906s", (0, 90), axis="az")
            True

        Args:
            name_or_dict (str/dict): A str corresponding to a source's name,
                or a dictionary containing the sources information.
            bounds (list/tuple): The bounds within which we're looking.
            axis (str, optional): "el" or "az" ("el").
        Returns:
            bool: True if in between bounds, False otherwise
        """
        convert = 180./np.pi
        src = self._get_source_from_str_or_dict(name_or_dict)
        axis_val = src[axis.lower()]*convert
        if axis_val >= bounds[0] and axis_val <= bounds[1]:
            return True
        return False

    def _get_source_from_str_or_dict(self, name_or_dict, **kwargs):
        """
        Given either a name or a dict, get a dictionary corresponding to the
        source.

        Args:
            name_or_dict (str/dict): a name of a source, or a dictionary
                representation of the source.
        Returns:
            dict: a dictionary corresponding to the requested source.
        """
        if isinstance(name_or_dict, six.string_types):
            src_dict = self.get_sources(source_names=name_or_dict, **kwargs)
        elif isinstance(name_or_dict, dict):
            src_dict = name_or_dict
        else:
            raise TypeError(
                "Can't recognize argument name_or_dict of type {}".format(
                    type(name_or_dict)))
        return src_dict

    def _get_src_info_dict(self, src_dict):
        self.logger.debug(
            "_get_src_info_dict: src_dict: {}".format(src_dict))
        src_obj = SerializableBody.from_dict(src_dict)
        self.logger.debug(
            ("_get_src_info_dict: "
             "adding source info for source {} to file").format(src_obj.name))
        observer = src_obj.get_observer()
        observer.date = ephem.now()
        src_obj.compute(observer)
        src_info = {
            "name": src_obj.name,
            "ra_J2000": src_obj._ra,
            "dec_J2000": src_obj._dec,
            "az": src_obj.az,
            "el": src_obj.alt
        }
        if "flux" in src_obj.info:
            src_info['flux'] = src_obj.info["flux"]['K']
        return src_info

    def _add_src_info_to_file(self, f_obj, src_dict):
        """
        Given some source dictionary, add it's information to the attrs of an
        HDF5 file object or group.

        Args:
            f_obj (h5py.File/h5py.Group): HDF5 file object or group
            src_dict (dict): a dictionary that can be turned into a
                SerializableBody.
        """
        src_info = self._get_src_info_dict(src_dict)
        for attr in src_info:
            f_obj[attr] = src_info[attr]


    # ------------------------- Observatory Details ---------------------------

    @auto_test()
    def _get_observer_info_dict(self):
        """
        Get a dictionary with current observer information.
        """
        observer_info = {
            "lat": self.equipment["Antenna"].lat,
            "lon": self.equipment["Antenna"].lon,
            "elevation": self.equipment["Antenna"].elevation,
            "epoch": self.equipment["Antenna"].epoch,
            "date": self.equipment["Antenna"].date
        }
        return observer_info


    # ------------------------- Antenna Control -------------------------------

    def point(self, name_or_dict):
        """
        Go to source
        
        Given some source or verifier name or dict, send command to antenna to
        point. This will not wait for the antenna to be on point, however.
        This will not point to the source if the source is not currently up.

        Args:
            name_or_dict (str/dict): Either a source name or a dictionary
        Returns:
            str: result of Antenna.point_radec command
        """
        convert = 180./ np.pi
        src = self._get_source_from_str_or_dict(name_or_dict)
        name = src["name"]
        report = self.report_source_info(src)
        for line in report:
            self.logger.info("point: {}".format(line))

        if float(src["el"])*convert < 10.0:
            msg = ("point: {} is currently not up. "
                   "Not pointing. Current az el: {} {}").format(
                       name,
                       float(src["az"])*convert,
                       float(src["el"])*convert)

            self.logger.error(msg)
            raise MonitorControlError([], msg)
        self.info["point"]["current_source"] = src
        resp = self.hdwr("Antenna", "point_radec", src["_ra"], src["_dec"])
        self.logger.debug("point: resp from Antenna: {}".format(resp))
        return resp


    # ------------------------------ Calibration ------------------------------

    def _create_calibration_file_path(self, base_dir, prefix,
                                      file_type="hdf5"):
        """
        create full path for a calibration file
        """
        self.logger.debug(
            "_create_calibration_file_path: base_dir: {}, prefix: {}".format(
                base_dir, prefix
            )
        )
        timestamp = datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss")
        doy, year = datetime.datetime.utcnow().strftime("%j,%Y").split(",")
        calib_dir = os.path.join(base_dir, year, doy)
        f_name = "{}_{}.{}".format(prefix, timestamp, file_type)
        f_path = f_name
        if not os.path.exists(calib_dir):
            try:
                os.makedirs(calib_dir)
                f_path = os.path.join(calib_dir, f_name)
            except Exception as err:
                self.logger.error(
                    ("_create_calibration_file_path: "
                     "Couldn't create calibration directory {}").format(
                        calib_dir))
                pass
        else:
            f_path = os.path.join(calib_dir, f_name)
        return f_path

    def _create_calibration_file_obj(self, base_dir, prefix,
                                           file_cls=h5py.File):
        """
        Create a calibration file object. This could be minical, boresight, or
        tipping.

        Will create a file object whose path is as follows:

        .. code-block:none

            base_dir/<year>/<doy>/prefix_<timestamp>.hdf5


        Args:
            base_dir (str): Base directory where data files are stored. Will
                store data file in base_dir/<year>/<doy> subdirectory.
            prefix (str):
            file_cls (type, optional):
        """
        f_path = self._create_calibration_file_path(base_dir, prefix)
        self.logger.debug("_create_calibration_file_obj: path is %s",
                          f_path)
        f_obj = file_cls(f_path, "w")
        return f_obj, f_path

    @Pyro5.api.oneway
    @async_method
    def scanning_boresight(self,
                           el_previous_offset,
                           xel_previous_offset,
                           limit=99.0,
                           sample_rate=0.3,
                           rate=3.0,
                           settle_time=10.0,
                           src_name_or_dict=None,
                           two_direction=True,
                           additional_offsets=None,
                           channel=0,
                           attrs=None):
        """
        Scanning boresight. Instead of choosing a predetermined set of points
        and stopping at each point, this sets an initial point, and moves
        continuously at rate ``rate`` to a final point, collecting system
        temperature data along the way.

        Scanning boresight is not yet ready to be used to accurately calculate
        position offsets. It can be used in situations where initial offsets
        are not well known, and then improved upon with stepping boresight.

        Args:
            el_previous_offset (float): Previous position offset in EL
            xel_previous_offset (float): Previous position offset in xEL
            limit (float, optional): How far on either side of initial axis
                point to start and finish. For example, if initial offset in
                elevation is 10, and limit is 50, boresight will send antenna
                to -40, and end up at +60 mdeg in elevation offset.
            sample_rate (float, optional): How often to attempt to get system
                temperature data (0.3)
            rate (float, optional): Offset rate. This is how fast antenna
                will continuously change offset between initial and ending
                point (3.0)
            settle_time (float, optional): Amount of time to settle after
                setting initial offsets
            src_name_or_dict (str/dict, optional): A string or dictionary
                corresponding to a source whose information we want to store
                with HDF5 results file.
            two_direction (bool, optional): Whether or not to run boresight
                in both directions in both axis. Setting this to True
                results in potentially more accurate offset calculations,
                at the cost of doubling execution time.
            additional_offsets (dict, optional): Additional offsets to set
                before starting boresight. This is necessary because this
                implementation clears offsets before starting scan.
            channels (int, optional): Which tsys channel to use to calculate
                offsets. Defaults to 0.
            attrs (dict, optional): Additional meta data to add to HDF5 file.
        Returns:
            tuple:
                tsys: tsys data from each power meter for each axis, in each
                    direction, along with offset data, time offsets between
                    tsys data and offsets, and corrected offset measurements.
                fits: fits from pol1 data for each axis, in each direction
        """
        if additional_offsets is None:
            additional_offsets = {}
        if attrs is None:
            attrs = {}
        attrs.update(additional_offsets) # we want to include any information
        # about additional offsets in attrs dict
        self.logger.debug("scanning_boresights: attrs: %s", attrs)

        # this is the order of the scans
        order = ["EL", "XEL"]
        # these are the commands to the NMC to get the offsets now in use
        total_offset_params = {
            "EL": "ElevationManualOffset",
            "XEL": "CrossElevationManualOffset"
        }
        # these are the commands to the NMC to get the currrent rate offsets
        accum_offset_params = {
            "EL": "ElevationAccumulatedRateOffset",
            "XEL": "CrossElevationAccumulatedRateOffset"
        }
        # this is the command to get the time for the axis angles
        timestamp_param = "AxisAngleTime"

        def timestamp_formatter(t):
            return datetime.datetime.fromtimestamp(float(t))

        # parameters describing scan on one axis
        single_axis_dict = {
            "offset": [],
            "tsys": [],
            "time_offset": [],
            "offset_corrected": [],
            "offset_before": [],
            "offset_after": []
        }

        # these values are passed as arguments in the call to scanning_boresight()
        initial_offsets = {
            "EL": float(el_previous_offset),   #  elevation offset now in use
            "XEL": float(xel_previous_offset)
        }

        def get_total_offset(axis):
            # ask the NMC/APC for current manual offsets
            get_info = self.hdwr(
                "Antenna",
                "get",
                total_offset_params[axis], # see above for definition
                timestamp_param
            )
            self.logger.debug("scanning_boresight.get_total_offset: %s offsets: %s",
                              axis, total_offset_params[axis])
            # convert result from deg to mdeg
            return (timestamp_formatter(get_info[timestamp_param]),
                    float(get_info[total_offset_params[axis]]))
             # 1000*float(get_info[total_offset_params[axis]]))

        def get_accum_offset(axis):
            # ask NMC/APC for current rate offsets
            get_info = self.hdwr(
                "Antenna",
                "get",
                accum_offset_params[axis],
                timestamp_param)
            self.logger.debug("scanning_boresight.get_accum_offsets: %s offsets: %s",
                              axis, accum_offset_params[axis])
            # convert deg to mdeg
            return (
                datetime.datetime.strptime(
                    get_info[timestamp_param],
                    timestamp_formatter),
                    float(get_info[accum_offset_params[axis]])
             # 1000*float(get_info[accum_offset_params[axis]])"integration_time"
            )
        # scanning boresight begins - notify clieny
        self.scanning_boresight.cb({"status": "running", "done": False}) # first status report

        boresight_base_data_dir = ""
        with self.lock:
            self.info["boresight"]["running"] = True
            boresight_base_data_dir = self.info["boresight"]["data_dir"]

        prefix = "scanning_two_direction_boresight_results"
        if not two_direction:
            prefix = "scanning_one_direction_boresight_results"

        # initialize a BoresightFileAnalyzer object
        file_path = self._create_calibration_file_path(
            boresight_base_data_dir, prefix)
        analyzer_obj = BSA.BoresightFileAnalyzer(
            file_path=file_path,
            boresight_type="scanning"
        )
        analyzer_obj.meta_data.update({
            "rate": rate,
            "sample_rate": sample_rate,
            "limit": limit,
            "initial_el": el_previous_offset,
            "initial_xel": xel_previous_offset
        })
        if src_name_or_dict is not None:
            src_dict = self._get_source_from_str_or_dict(src_name_or_dict)
            src_info = self._get_src_info_dict(src_dict)
            analyzer_obj.meta_data.update(src_info)
        analyzer_obj.meta_data.update(attrs)

        # clear position and rate offsets
        self.logger.debug(("scanning_boresight: "
                           "clearing offsets, clearing rates"))
        self.hdwr("Antenna", "clr_offsets")
        self.hdwr("Antenna", "clr_rates")
        self.logger.debug(
            ("scanning_boresight: "
             "setting offset in el to {}, offset in xel to {}").format(
                el_previous_offset, xel_previous_offset)
        )
        # the initial offset is the offset passed in as argument,
        # probably from the previous boresight
        self.hdwr("Antenna", "set_offset_one_axis", "EL", el_previous_offset)
        self.hdwr("Antenna", "set_offset_one_axis", "XEL", xel_previous_offset)
        if additional_offsets: # TBHK added this test 2019-06-07
          self.logger.debug("scanning_boresight: setting additional offsets")
          for offset_axis in additional_offsets:
            offset_value = additional_offsets[offset_axis]
            offset_axis_up = offset_axis.upper()
            self.logger.debug(
                "scanning_boresight: setting offset in {} to {}".format(
                    offset_axis_up, offset_value))
            self.hdwr(
                "Antenna", "set_offset_one_axis", offset_axis_up, offset_value)
        if additional_offsets:
          if len(additional_offsets) > 0:
            time.sleep(settle_time)

        # scanning boresight parameters
        self.logger.info(
            "scanning_boresight: Initial offsets: {:.4f}, {:.4f}".format(
                el_previous_offset, xel_previous_offset))
        self.logger.info(
            "scanning_boresight: limit {}".format(limit)) # millidegrees
        self.logger.info(
            "scanning_boresight: settle time {}".format(settle_time))
        self.logger.info(
            "scanning_boresight: offset rate {}".format(rate))
        self.logger.info(
            "scanning_boresight: sampling rate {}".format(sample_rate))

        scan_dir_map = {
            "1": "right",
            "-1": "left"
        }

        def cond(scan_dir, total_offset, limit, previous_offset):
            # while within the scan range
            # these angles are in millideg
            if scan_dir > 0:
                return total_offset < scan_dir*(limit + previous_offset)
            elif scan_dir < 0:
                return total_offset > scan_dir*(limit + previous_offset)

        def scan_and_collect(axis, scan_dir):
            """
            perform the boresight

            Args:
              axis (str):     'EL' or 'XEL'
              scan_dir (int): positive or negative
            """
            # convert scan_dir to str
            scan_dir_str = scan_dir_map[str(scan_dir)]
            # initial offset passed in to 'scanning_boresight'
            previous_offset = initial_offsets[axis]
            # make a real copy of the scan parameters
            tsys_data = {
                scan_dir_str: copy.deepcopy(single_axis_dict)
            }
            self.logger.debug("scanning_boresight: scan direction is %d", scan_dir)
            self.logger.debug("scanning_boresight: limit is %s", limit)
            self.logger.debug("scanning_boresight: previous_offset is %s", previous_offset)
            first_offset = -scan_dir*(limit - previous_offset)
            self.logger.debug(
                "scanning_boresight: Setting offset in {} to {}".format(
                    axis, first_offset))
            # move the antenna to the scan starting position
            #   negative offset for positive scan direction
            self.hdwr(
                "Antenna",
                "set_offset_one_axis",
                axis,
                first_offset
            )
            time.sleep(settle_time)

            # set the scan rate
            msg = "Setting rate offset in {} to {}".format(axis, scan_dir*rate)
            self.logger.debug("scanning_boresight: {}".format(msg))
            self.scanning_boresight.cb({"status": msg})
            self.hdwr("Antenna", "set_rate", axis, scan_dir*rate)

            # get the pointing offset converted from deg to mdeg
            timestamp, total_current_offset = get_total_offset(axis)
            self.logger.debug(
                "scanning_boresight: current total offset: {}".format(
                    total_current_offset))
            interval = 10 # number of steps between status reports to client
            current_interval = 0 # interval counter
            while cond(scan_dir, total_current_offset, limit, previous_offset):
                # while within the scan range
                timestamp_before, total_offset_before = get_total_offset(axis)
                total_current_offset = total_offset_before
                try:
                    tsys_timestamp, cur_tsys = self.get_tsys(timestamp=True)
                except Exception as err:
                    self.logger.error(
                        ("scanning_boresight.scan_and_collect: "
                         "Failed to get tsys data: {}").format(err))
                    continue
                time.sleep(sample_rate)

                # get the pointing offset converted from deg to mdeg
                timestamp_after, total_offset_after = get_total_offset(axis)
                cur_ave_offset = (total_offset_before +
                                  total_offset_after)/2.0

                # originally the test was "== 0" which would invoke the status
                # report callback every tenth step.
                # changed from == to != by TBHK 2019-06-06
                # now it reports every step
                if current_interval % interval != 0:
                    msg = ("axis: {}, current PO: {}, "
                           "current tsys: {}").format(
                                axis, cur_ave_offset, cur_tsys
                            )
                    self.scanning_boresight.cb(
                        {"status": msg,
                         "done": False,
                         "axis": axis,
                         "offset": cur_ave_offset,
                         "tsys": cur_tsys}
                    )
                    self.logger.debug("scanning_boresight: {}".format(msg))
                current_interval += 1
                # build up lists of offsets and system temperatures
                tsys_data[scan_dir_str]["offset"].append(cur_ave_offset)
                tsys_data[scan_dir_str]["tsys"].append(cur_tsys)

            # stop the scan
            self.hdwr("Antenna", "set_rate", axis, 0.0)
            msg = "scanning finished"
            self.scanning_boresight.cb(
                        {"status": msg,
                         "done": False,
                         "axis": axis}
                    )
            return tsys_data

        scan_directions = [1]
        if two_direction:
            scan_directions = [1, -1]

        scan_dir_map = {
            str(key): scan_dir_map[str(key)] for key in scan_directions
        }


        for axis in order:  # for each axis
            # collect and analyze the data
            for scan_dir in scan_directions:  #for each scan direction
                scan_dir_str = scan_dir_map[str(scan_dir)]
                tsys_data_scan_dir = scan_and_collect(axis, scan_dir)
                analyzer_obj.data[axis.lower()][scan_dir_str] = \
                    BSA.SingleAxisBoresightDataAnalyzer(
                        tsys_data_scan_dir[scan_dir_str]["offset"],
                        tsys_data_scan_dir[scan_dir_str]["tsys"],
                        axis=axis.lower(),
                        direction=scan_dir_str
                    )
                self.hdwr("Antenna", "clr_rates")
                msg = "scanning {} finished".format(scan_dir)
                self.scanning_boresight.cb(
                        {"status": msg,
                         "done": False,
                         "axis": axis}
                    )

            offsets = []
            amplitudes = []
            axis_lower = axis.lower()
            for scan_dir in scan_directions:
                s = scan_dir_map[str(scan_dir)]
                if analyzer_obj.data[axis_lower][s] is None:
                    self.logger.debug(
                        "scanning_boresight: no data for axis {}, direction {}".format(axis, s))
                    continue
                self.logger.debug("scanning_boresight: calculating offsets for axis {}, direction {}".format(axis, s))
                analyzer_obj.data[axis_lower][s].calculate_offsets()
                channel = str(channel)
                fit = analyzer_obj.data[axis_lower][s].channels[channel].fit.copy()
                if fit["score"][0]:
                    msg = "fit accepted"
                    self.logger.debug("scanning_boresight: "+msg)

                    offsets.append(fit["offset"])
                    amplitudes.append(fit["amplitude"])
                else:
                    msg = "fit rejected"
                    self.logger.error(
                        ("scanning_boresight: "
                         "boresight fits rejected. "
                         "Falling back to initial offset"))
                    offsets.append(initial_offsets[axis])
                    amplitudes.append(0)
                self.scanning_boresight.cb(
                        {"status": msg,
                         "done": False,
                         "axis": axis}
                    )

            ave_offset = sum(offsets)/len(offsets)
            ave_amplitude = sum(amplitudes)/len(amplitudes)
            self.logger.info(
                "scanning_boresight: Average offset for axis {}: {}".format(
                    axis, ave_offset))
            self.logger.info(
                "scanning_boresight: Average amplitude for axis {}: {}".format(
                    axis, ave_amplitude))
            self.hdwr("Antenna", "set_offset_one_axis", axis, ave_offset)
            self.info["boresight"]["offset_{}".format(axis.lower())] = \
                ave_offset
            time.sleep(settle_time)

        analyzer_obj.dump()
        # finished one axis

        with self.lock:
            self.info["boresight"]["running"] = False

        self.scanning_boresight.cb({
            "done": True,
            "status": "done",
            "analyzer_obj": analyzer_obj.to_dict()
        })
        return analyzer_obj

    @Pyro5.api.oneway
    @async_method
    def stepping_boresight(self,
                           el_previous_offset,
                           xel_previous_offset,
                           n_points=9,
                           integration_time=2,
                           settle_time=10.0,
                           two_direction=True,
                           src_name_or_dict=None,
                           additional_offsets=None,
                           channel=0,
                           attrs=None):
        """
        Perform stepping boresight over specified number of points.
        Stepping boresight moves to each offset in a list of position offsets,
        stops, takes system temperature readings, and then proceeds to the next
        point. Use stepping boresight for accurately calculating position
        offsets.

        Calculates settle time based on difference between current offset and
        previously set offset.

        Args:
            el_previous_offset (float): Previous elevation offset
            xel_previous_offset (float): Previous cross elevation offset
            n_points (int, optional): The number of points to use.
                Defaults to 9.
            integration_time (int, optional): The amount of time for which to
                integration power meter readings at each boresight step.
                Defaults to 2 (seconds).
            settle_time (float, optional): Maximum time to settle between
                position offsets.
            src_name_or_dict (str/dict, optional): A string or dictionary
                corresponding to a source whose information we want to store
                with HDF5 results file.
            two_direction (bool, optional): Whether or not to run boresight
                in both directions in both axis. Setting this to True results
                in potentially more accurate offset calculations, at the cost
                of doubling execution time.
            channels (int, optional): Which tsys channel to use to calculate
                offsets. Defaults to 0.
            attrs (dict, optional): Additional meta data to add to HDF5 file.
            additional_offsets (dict, optional): Additional offset information
                to add to HDF5 file.
        Returns:
            tuple:
                tsys: tsys data from each power meter for each axis, in each
                    direction, along with offset data, time offsets between
                    tsys data and offsets, and corrected offset measurements.
                fits: fits from pol1 data for each axis, in each direction
        """
        def calc_settle_time(delta_offset):
            """
            Calculate amount of time needed for antenna to properly settle after
            setting offset. For large changes in offset, this increases.

                            10 sec if delta_offset > 40 mdeg
            settle_time =   linear function between upper and lower limits if 5 < delta_offset < 40
                            2 sec if delta_offset < 5 mdeg
            """
            max_settle_time = settle_time
            min_settle_time = 3.0
            max_delta_offset = 40
            min_delta_offset = 5

            if delta_offset > max_delta_offset:
                return max_settle_time
            elif delta_offset < min_delta_offset:
                return min_settle_time
            else:
                m = (max_settle_time - min_settle_time) / (max_delta_offset - min_delta_offset)
                return m*(delta_offset - min_delta_offset) + min_settle_time

        def calc_bs_points(n_points=9, fwhm=None):
            """
            Calculate the points to use for the boresight movement across the
            sky.

            Args:
                fwhm (float): full width half max. A characteristic of the
                    antenna at a given frequency.
                n_points (int): The number of points for which to calculate
                    boresight.
            Returns:
                list: the boresight points.
            """
            # We compute this for scan length of 2*5*fwhm so that we are enough offsource in both el and xel
            if fwhm is None:
                fwhm = self.hdwr("Antenna", "k_band_fwhm")
            if n_points < 6 and n_points > 15:
                self.logger.error(
                    ("stepping_boresight.calc_bs_points: "
                     "Boresight for {} points not supported").format(n_points))
                return
            else:
                self.logger.info(
                    ("stepping_boresight.calc_bs_points: "
                     "Calculating {} boresight points").format(n_points))
                points = [-5]
                points.extend(np.linspace(-1.5, 1.5, n_points - 2).tolist())
                points.append(5)

                points_scaled = [i*fwhm for i in points]
                self.logger.debug(
                    "stepping_boresight.calc_bs_points: Calculated points: {}".format(points))
                self.logger.debug(
                    "stepping_boresight.calc_bs_points: Calculated scaled points: {}".format(
                        points_scaled))
                return points, points_scaled

        def set_offset(axis, deg_val):
            """Shortcut function for setting offset at a specific axis"""
            return self.hdwr("Antenna", "set_offset_one_axis", axis, deg_val)

        def integrate_tsys(integration_time=2.0, wait_time=0.2):
            """Integrate system temperate for a given amount of time"""
            tsys_data = []
            t0 = time.time()
            t = t0
            while (t - t0) < integration_time:
                try:
                    tsys = self.get_tsys()
                except Exception as err:
                    self.logger.error(
                        ("stepping_boresight.integrate_tsys: "
                         "Failed to get tsys: {}").format(err))
                    continue
                tsys_data.append(tsys)
                time.sleep(wait_time)
                t = time.time()
            integration = np.mean(tsys_data, axis=0).tolist()
            return integration

        def integrate_tsys_along_offset_path(axis, locs,
                                             integrate_tsys_args=None,
                                             integrate_tsys_kwargs=None):
            """
            Given a set of points, iteratively change antenna position offset,
            and collect system temperature data.
            """
            if integrate_tsys_args is None:
                integrate_tsys_args = ()
            if integrate_tsys_kwargs is None:
                integrate_tsys_kwargs = {}
            integration_data = []
            self.logger.debug(
                ("stepping_boresight.integrate_tsys_along_offset_path: "
                 "Offset axis: {}, Offset points: {}").format(axis, locs))
            for i in range(len(locs)):
                offset = locs[i]
                if i == 0:
                    delta_offset = abs(offset)
                else:
                    delta_offset = abs(offset - locs[i-1])
                settle_time_i = calc_settle_time(delta_offset)
                self.logger.debug(
                    ("stepping_boresight.integrate_tsys_along_offset_path: "
                     "Calculated settle time: {}").format(settle_time_i))
                set_offset(axis, offset)
                time.sleep(settle_time_i)
                integration = integrate_tsys(
                    *integrate_tsys_args,
                    **integrate_tsys_kwargs)
                self.logger.debug(
                    ("stepping_boresight.integrate_tsys_along_offset_path: "
                     "integration at offset {}: {}").format(
                        offset, integration))
                integration_data.append(integration)
            self.logger.debug(
                "integrate_tsys_along_offset_path: final data: {}".format(
                    integration_data))
            return integration_data

        if additional_offsets is None:
            additional_offsets = {}
        if attrs is None:
            attrs = {}
        attrs.update(additional_offsets)

        with self.lock:
            self.info["boresight"]["running"] = True
            boresight_base_data_dir = self.info["boresight"]["data_dir"]
        scan_directions = [1]
        prefix = "stepping_one_direction_boresight_results"
        if two_direction:
            scan_directions = [1, -1]
            prefix = "stepping_two_direction_boresight_results"

        file_path = self._create_calibration_file_path(
            boresight_base_data_dir, prefix)

        analyzer_obj = BSA.BoresightFileAnalyzer(
            file_path=file_path,
            boresight_type="stepping"
        )

        scan_dir_map = {
            "1": "right",
            "-1": "left"
        }

        integration_time = float(integration_time)

        initial_offsets = {
            "EL": float(el_previous_offset),
            "XEL": float(xel_previous_offset)
        }

        self.logger.info(
            ("stepping_boresight: "
             "Using el {} and xel {} as previous offsets").format(
                initial_offsets['EL'], initial_offsets['XEL']))
        self.logger.info(
            ("stepping_boresight: Power meter integration time: {}").format(
                integration_time))
        self.logger.info(
            "stepping_boresight: Using {} boresight points".format(n_points))
        self.logger.info(
            "stepping_boresight: Settle time {}".format(settle_time))
        self.logger.info(
            "stepping_boresight: src_name_or_dict: {}".format(
                src_name_or_dict))
        _, points = calc_bs_points(n_points=n_points)
        self.logger.debug("stepping_boresight: Using points: {}".format(
            points))

        analyzer_obj.meta_data.update({
            "n_points": n_points,
            "integration_time": integration_time,
            "initial_el": el_previous_offset,
            "initial_xel": xel_previous_offset
        })
        if src_name_or_dict is not None:
            src_dict = self._get_source_from_str_or_dict(src_name_or_dict)
            src_info = self._get_src_info_dict(src_dict)
            analyzer_obj.meta_data.update(src_info)
        analyzer_obj.meta_data.update(attrs)

        self.hdwr(
            "Antenna", "set_offset_one_axis", "EL", initial_offsets["EL"]
        )
        self.hdwr(
            "Antenna", "set_offset_one_axis", "XEL", initial_offsets["XEL"]
        )
        self.logger.debug("stepping_boresight: setting additional offsets")
        for offset_axis in additional_offsets:
            offset_value = additional_offsets[offset_axis]
            offset_axis_up = offset_axis.upper()
            self.logger.debug(
                "stepping_boresight: setting offset in {} to {}".format(
                    offset_axis_up, offset_value))
            self.hdwr(
                "Antenna", "set_offset_one_axis", offset_axis_up, offset_value)
        time.sleep(settle_time)

        integrate_tsys_kwargs = {"integration_time": integration_time}
        scan_dir_map = {str(key): scan_dir_map[str(key)]
                        for key in scan_directions}  # this is updated to reflect single or two direction boresight
        for axis in ['EL', 'XEL']:
            axis_lower = axis.lower()
            for scan_dir in scan_directions:
                scan_dir_str = scan_dir_map[str(scan_dir)]
                axis_points = [scan_dir*(i + initial_offsets[axis]) for i in points]
                self.logger.info(
                    ("boresight: "
                     "Boresight points for given routine in {}: {}").format(
                        axis, axis_points))
                avg_tsys = integrate_tsys_along_offset_path(
                    axis,
                    axis_points,
                    integrate_tsys_kwargs=integrate_tsys_kwargs
                )
                if not avg_tsys and not self._boresight_info['running']:
                    msg = "Boresight Cancelled"
                    self.logger.info("stepping_boresight: {}".format(msg))
                    self.stepping_boresight.cb({'status': msg, "done":True})
                    return
                analyzer_obj.data[axis_lower][scan_dir_str] = \
                    BSA.SingleAxisBoresightDataAnalyzer(
                        axis_points,
                        avg_tsys,
                        axis=axis_lower,
                        direction=scan_dir_str
                    )

            offsets = []
            amplitudes = []
            for scan_dir in scan_directions:
                s = scan_dir_map[str(scan_dir)]
                if analyzer_obj.data[axis_lower][s] is None:
                    self.logger.debug(
                        "stepping_boresight: no data for axis {}, direction {}".format(axis, s))
                    continue
                self.logger.debug("stepping_boresight: calculating offsets for axis {}, direction {}".format(axis, s))
                analyzer_obj.data[axis_lower][s].calculate_offsets()
                channel = str(channel)
                fit = analyzer_obj.data[axis_lower][s].channels[channel].fit.copy()
                if fit["score"][0]:
                    self.logger.debug("stepping_boresight: fit accepted")
                    offsets.append(fit["offset"])
                    amplitudes.append(fit["amplitude"])
                else:
                    self.logger.error(
                        ("stepping_boresight: "
                         "boresight fits rejected. "
                         "Falling back to initial offset"))
                    offsets.append(initial_offsets[axis])
                    amplitudes.append(0)

            ave_offset = sum(offsets)/len(offsets)
            ave_amplitude = sum(amplitudes)/len(amplitudes)
            self.logger.info("stepping_boresight: Average offset for axis {}: {:.3f} mdeg".format(axis, ave_offset))
            self.logger.info("stepping_boresight: Average amplitude for axis {}: {:.3f} K".format(axis, ave_amplitude))
            self.hdwr("Antenna", "set_offset_one_axis", axis, ave_offset)
            self.info["boresight"]["offset_{}".format(axis.lower())] = ave_offset

        analyzer_obj.dump()

        with self.lock:
            self.info["boresight"]["running"] = False

        self.stepping_boresight.cb({
            "done": True,
            "status": "done",
            "analyzer_obj": analyzer_obj.to_dict()
        })
        return analyzer_obj

    @async_method
    def get_boresight_file_paths(self, **kwargs):
        """
        Call the BoresightManager.detect_file_paths static method.

        Examples:

        .. code-block::python

            >>> server.get_boresight_file_paths(year="2018",doy="102")
            {"2018":{"102"}}

        Args:
            **kwargs: passed to BoresightManager.detect_file_paths

        Returns:
            dict:
        """
        file_paths, flattened = BSM.BoresightManager.detect_file_paths(**kwargs)
        self.get_boresight_file_paths.cb(
            file_paths
        )
        return file_paths

    def get_boresight_analyzer_object(self, file_path):
        """
        Get a file analyzer object from the manager attribute.

        Examples:

        .. code-block::python

            >>> server.get_boresight_analyzer_object(
                "2018/102/scanning_one_direction_boresight_results_102-07h21m42s.hdf5")
            {}

        Args:
            file_path (str): path to the desired boresight file.
        Returns:
            dict: dictionary representation of file analyzer object.
        """
        self.logger.debug("get_boresight_analyzer_object: called")
        file_name = os.path.basename(file_path)
        if file_name not in self.boresight_manager:
            self.logger.debug(("get_boresight_analyzer_object: "
                               "adding {}").format(file_name))
            self.boresight_manager.add_analyzer_object(file_path)
        try:
            obj = self.boresight_manager[file_name]
            obj_dict = obj.to_dict()
        except KeyError as err:
            self.logger.error(
                ("get_boresight_analyzer_object: "
                 "Couldn't create object from file {}").format(file_name))
            obj_dict = None
        return obj_dict

    @async_method
    def get_most_recent_boresight_analyzer_object(self):
        """
        Get the most recent boresight results.

        Examples:

        .. code-block::python

            >>> server.get_most_recent_boresight_analyzer_object()
            {}

        Returns:
            dict: dictionary representation of file analyzer object.
        """
        self.logger.debug("get_most_recent_boresight_analyzer_object: called")
        file_paths, flattened = BSM.BoresightManager.detect_file_paths()
        dt_objs = []
        for file_path in flattened:
            file_name = os.path.basename(file_path)
            dt_str = os.path.splitext(file_name)[0].split("_")[-1]
            if len(dt_str.split("-")) == 2:
                dt_str = "2017-"+dt_str
            try:
                dt_obj = datetime.datetime.strptime(dt_str, "%Y-%j-%Hh%Mm%Ss")
            except ValueError as err:
                dt_obj = datetime.datetime.strptime(dt_str, "%Y-%j-%H:%M:%S")
            dt_objs.append((dt_obj, file_name, file_path))

        dt_objs.sort()
        while len(dt_objs) > 0:
            _, most_recent_name, most_recent_path = dt_objs.pop()
            if most_recent_name not in self.boresight_manager:
                self.boresight_manager.add_analyzer_object(most_recent_path)

            try:
                obj_dict = self.boresight_manager[most_recent_name].to_dict()
                break
            except KeyError as err:
                continue

        self.get_most_recent_boresight_analyzer_object.cb(
            obj_dict
        )
        return obj_dict

    @staticmethod
    def process_minical_calib(cal_data,
                              Tlna=25,
                              Tf=1,
                              Fghz=20,
                              TcorrNDcoupling=0):
        """
        Process minical calibration data.
        Args:
            cal_data (dict): The result of self.minical
        Returns:
            list:
                gains (list of lists): power meter gains
                Tlinear (list of lists): Linear fit paramters
                Tquadratic (list of lists): Quadratic fit parameter
                Tnd (list of floats): Noise diode temperature
                NonLin (list of floats): Non linear component
        """
        def gain_cal(Tlna, Tf, R1, R2, R3, R4, R5, Tp, Fghz, TP4corr):
            """
            Computes minical parameters from minical data

            This uses the Stelreid/Klein calibration algorithm
            Stelzried and Klein, Proc. IEEE, 82, 776 (1994) to
            compute B, BC and CC, as well as Tnd.
            The true gain is B ( BC*R + B*CC*R^2 )

            Args:
                Tlna (float): the LNA noise temperature
                Tf (float): follow-on amplifier noise temperature contribution
                R1 (float): reading with power meter input zeroed
                R2 (float): reading with LNA connected to antenna
                R3 (float): reading with LNA connected to antenna, noise diode on
                R4 (float): reading with LNA connected to ambient load
                R5 (float): reading on ambient load, noise diode on
                Tp (np.ndarray): physical temperature of ambient load (deg K)
                Fghz (float): frequency in GHz
                TP4corr (float): correction to T4 due to VSWR at the ambient load
            Returns:
                tuple:
                      B - linear or mean gain
                      BC - linear component of second order gain
                      CC - quadratic component of second order gain
                      Tnd - noise diode temperature (K)
            """
            # correction from Rayleigh-Jeans approx. to Planck
            Tc = -0.024 * Fghz
            # system temperature on the load
            T4P = Tp + Tlna + Tf + Tc + TP4corr
            # This is the gain, assuming the system is linear:
            # 	T = B * ( R - R1 )
            B = T4P * 1.0/(R4 - R1)
            T2 = B * (R2 - R1)  # linear system temperature on sky
            T3 = B * (R3 - R1)  # linear system temperature on sky with noise diode
            T5 = B * (R5 - R1)  # linear system temperature in load with noise diode
            M = T5*T5 - T4P*T4P - T3*T3 + T2*T2
            N = T5 - T4P - T3 + T2
            CC = N / (N * T4P - M)
            BC = 1.0 - CC * T4P
            Tnd = BC * (T3 - T2) + CC * (T3 * T3 - T2 * T2)
            return B, BC, CC, Tnd

        R1 = np.array(cal_data['zero'])
        # deal with pesk underflow reading of 9e40
        if (R1 > 1e-7).any():
          module_logger.warning("process_minical_calib.gain_cal: has underflows; set to 0")
          R1 = np.where(R1 > 1.e-7, 0, R1)
        R2 = np.array(cal_data['sky'])
        R3 = np.array(cal_data['sky+ND'])
        R4 = np.array(cal_data['load'])
        R5 = np.array(cal_data['load+ND'])
        load = np.array(cal_data['Tload'])
        # pm_mode = cal_data['mode']
        # if pm_mode == "dBm":
        #     convert dBm to W
            # R2 = math.pow(10.0, R2 / 10.0) / 1000.0
            # R3 = math.pow(10.0, R3 / 10.0) / 1000.0
            # R4 = math.pow(10.0, R4 / 10.0) / 1000.0
            # R5 = math.pow(10.0, R5 / 10.0) / 1000.0
        gains = gain_cal(Tlna, Tf, R1, R2, R3, R4, R5,
                         load, Fghz, TcorrNDcoupling)
        module_logger.debug("process_minical_calib: gain_cal returned B, BC, CC, Tnd: {}".format(gains))
        B = gains[0]  # linear gain
        if np.any(B == 0):
            module_logger.debug("process_minical_calib: process_minical result for gain: {}".format(B))
            # raise "minical failed"
        BC = gains[1]  # linear term of polynomial gain
        CC = gains[2]  # quadratic term of polynomial gain
        # equivalent temperature of noise diode
        Tnd = gains[3]
        T2 = B * (R2 - R1) # sky, linear gain
        if np.any(T2 == 0):
            module_logger.debug("process_minical_calib: process_minical result for sky: {}".format(T2))
            # raise "minical failed"
        T3 = B * (R3 - R1)  # sky + ND
        T4 = B * (R4 - R1)  # load
        T5 = B * (R5 - R1)  # load + ND
        Tlinear = [T2, T3, T4, T5]
        module_logger.info("process_minical_calib: Tlinear: {}".format(Tlinear))
        T2C = BC * T2 + CC * T2 * T2
        T3C = BC * T3 + CC * T3 * T3
        T4C = BC * T4 + CC * T4 * T4
        T5C = BC * T5 + CC * T5 * T5
        Tquadratic = [T2C, T3C, T4C, T5C]
        # Tsky correction
        FL = T2C / T2
        # non-linearity
        NonLin = 100.0 * (FL - 1.0)
        # Calculate new tsys factors
        tsys_factors = [Tquadratic[0][i] / cal_data['sky'][i] for i in range(4)]
        module_logger.info("process_minical_calib: Tquadratic: {}".format(Tquadratic))
        module_logger.info("process_minical_calib: Tnd: {}".format(Tnd))
        module_logger.info("process_minical_calib: NonLin: {}".format(NonLin))
        module_logger.info("process_minical_calib: New tsys factors: {}".format(tsys_factors))

        return {'gains': [a.tolist() for a in gains],
                'linear': [a.tolist() for a in Tlinear],
                'quadratic': [a.tolist() for a in Tquadratic],
                'nd_temp': Tnd.tolist(),
                'non_linearity': NonLin.tolist(),
                'tsys_factors': tsys_factors}

    @Pyro5.api.oneway
    @async_method
    def tsys_calibration(self, settle_time=1.0, pm_integration_time=3.0):
        """
        Calibrate power meter read out by establishing a correspondance between
        sky temperature (tsys) and raw power meter readout.

        This method implements an algorithm found in an article by Stelzried,
        C.T, published in 1987, entitled "Non-Linearity in Measurement Systems:
        Evaluation Method and Application to Microwave Radiometers".

        Keyword Args:
            settle_time (float): Time to wait after setting feed to sky.
                This was added to algorithm at Tom Kuiper's recommendation.

        Returns:
            dict: results of DSSServer.process_minical_calib.
        """
        self.info["tsys_calibration"]["date"] =  \
                          datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss")
        try:
            self.info["tsys_calibration"]["el"] = float(self.hdwr("Antenna",
                                      "get","ElevationAngle")["ElevationAngle"])
        except Exception as err:
            self.logger.error(
               "tsys_calibration: Couldn't get elevation angle: {}".format(err))

        def set_preamp_off():
            for f in self.equipment["FrontEnd"].channel:
                c = self.equipment["FrontEnd"].channel[f]
                c.set_preamp_off()

        def set_preamp_on():
            for f in self.equipment["FrontEnd"].channel:
                c = self.equipment["FrontEnd"].channel[f]
                c.set_preamp_on()

        def set_feed_sky():
            for f in self.equipment["FrontEnd"].channel:
                c = self.equipment["FrontEnd"].channel[f]
                c.retract_load()

        def set_feed_load():
            for f in self.equipment["FrontEnd"].channel:
                c = self.equipment["FrontEnd"].channel[f]
                c.insert_load()

        def set_PM_mode(mode):
            for f in self.equipment["FrontEnd"].channel:
                c = self.equipment["FrontEnd"].channel[f]
                for p in c.PM:
                    pm = c.PM[p]
                    pm.set_mode(mode)

        def get_PM_readings(n, timeout=0.3):
            """
            average power meter readings
            
            Args:
              n: number of seconds
              timeout: length of time to allow for a reading
            """
            all_readings = []
            t0 = time.time()
            t_delta = time.time() - t0 # initially near 0 so test id True
            while t_delta < float(n):
                try:
                    readings = np.array(
                         [r[-1] for r in self.equipment["FrontEnd"].read_PMs()])
                    if len(readings) != 4:
                        continue
                    all_readings.append(readings)
                except Exception as err:
                    self.logger.error("tsys_calibration.get_PM_readings:"+
                                  " Couldn't read power meters: {}".format(err))
                time.sleep(timeout)
                t_delta = time.time() - t0 # time elapsed since the start.
            all_readings = np.array(all_readings)
            return np.mean(np.array(all_readings), axis=0)

        calib = {}
        self.info["tsys_calibration"]['running'] = True

        msg = "Turning preamp bias off"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({'status': msg})
        set_preamp_off()

        # set mode to W
        set_PM_mode("W")
        calib['mode'] = b'W'

        # We should be zeroing power meters here before collecting data.
        calib['zero'] = get_PM_readings(pm_integration_time)
        self.logger.debug("tsys_calibration: zero readings: {}".format(
                                                                 calib["zero"]))

        msg = "Turning preamp bias on"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({'status': msg})
        set_preamp_on()

        # collect data, load + no noise diode
        msg = "Turning noise diode off and setting feeds to load"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg})
        set_feed_load()
        self.equipment["FrontEnd"].set_ND_off()
        calib['load'] = get_PM_readings(pm_integration_time)
        self.logger.debug("tsys_calibration: load readings: {}".format(
                                                                 calib["load"]))

        # collect data, load + noise diode
        msg = "Turning noise diode on"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg})
        self.equipment["FrontEnd"].set_ND_on()
        calib['load+ND'] = get_PM_readings(pm_integration_time)
        self.logger.debug("tsys_calibration: load+ND readings: {}".format(
                                                              calib["load+ND"]))

        # collect data, sky + noise diode
        msg = "Setting feeds to sky"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg})
        set_feed_sky()
        time.sleep(settle_time)
        calib['sky+ND'] = get_PM_readings(pm_integration_time)
        self.logger.debug("tsys_calibration: sky+ND readings: {}".format(
                                                               calib["sky+ND"]))

        # collect data, sky + no noise diode
        msg = "Turning noise diode off"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg})
        self.equipment["FrontEnd"].set_ND_off()
        calib['sky'] = get_PM_readings(pm_integration_time)
        self.logger.debug("tsys_calibration: sky readings: {}".format(
                                                                  calib["sky"]))

        # get front end temperature.
        msg = "Getting front end temperatures"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg})
        fe_temp = self.equipment["FrontEnd"].read_temps()
        calib['Tload'] = np.array([fe_temp['load1'], fe_temp['load1'],
                                   fe_temp['load2'], fe_temp['load2']])

        self.logger.debug("tsys_calibration: calib: {}".format(calib))

        tsys_calibration_base_dir = self.info["tsys_calibration"]["data_dir"]
        # create an HDF5 calibration file object
        f_obj, f_path = self._create_calibration_file_obj(
                          tsys_calibration_base_dir, "tsys_cal")
        for key in calib:
            self.logger.debug("tsys_calibration: creating dataset %s", key)
            f_obj.create_dataset(key, data=np.array(calib[key]))
        f_obj.close()

        results = DSSServer.process_minical_calib(calib)
        tsys_factors = np.array(results["tsys_factors"])
        tsys_factors[np.logical_not(np.isfinite(tsys_factors))] = 1.0
        self.info["tsys_calibration"]["tsys_factors"] = tsys_factors.tolist()
        self.info["tsys_calibration"]['running'] = False
        self.save_info()

        msg = "Minical finished"
        self.logger.info("tsys_calibration: " + msg)
        self.tsys_calibration.cb({"status": msg, "results": results})
        return results

    def stop_tsys_calibration(self):
        """Stop flux calibraton from running"""
        self.info["tsys_calibration"]["running"] = False

    @Pyro5.api.oneway
    def tip(self):
        self.logger.debug("tip: called.")
        self.info["tip"]["running"] = True
        limits = [15., 88.]
        group_names = ["ascending", "descending"]
        tip_return_data = {name: {} for name in group_names}
        tip_base_data_dir = self.info["tip"]["data_dir"]
        f_tip, f_tip_path = self._create_calibration_file_obj(
            tip_base_data_dir, "tip_results")

        def get_current_el():
            return float(self.hdwr("Antenna", "get", "ElevationAngle"))

        def collect_tsys_data(target_el, current_el_callback, tol=0.1, sample_rate=0.3):
            el_data = []
            tsys_data = []
            current_el = current_el_callback()
            while abs(current_el - target_el) > tol:
                try:
                    tsys = self.get_tsys()
                    time.sleep(sample_rate)
                except Exception as err:
                    self.logger.error("tip.collect_tsys_data: Error getting system temperature data: {}".format(err))
                    continue
                current_el = current_el_callback()
                self.logger.debug("tip.collect_tsys_data: current elevation: {}".format(current_el))
                el_data.append(current_el)
                tsys_data.append(tsys)
            return el_data, tsys_data

        self.logger.info("tip: setting offset in EL and XEL to 99")
        self.hdwr("Antenna", "set_offset_one_axis", "EL", 99)
        self.hdwr("Antenna", "set_offset_one_axis", "XEL", 99)
        for i in range(len(limits)):
            limit = limits[i]
            group_name = group_names[i]
            self.logger.info("tip: Moving to {}".format(limit))
            try:
                self.hdwr("Antenna", "move", limit, axis="EL")
            except Exception as err:
                self.logger.error("tip: error: {}".format(err), exc_info=True)
            el_data, tsys_data = collect_tsys_data(limit, get_current_el)
            grp = f_tip.create_group(group_name)
            grp.create_dataset("el", data=el_data)
            grp.create_dataset("tsys", data=tsys_data)
            tip_return_data[group_name]["el"] = el_data
            tip_return_data[group_name]["tsys"] = tsys

        f_tip.close()
        self.info["tip"]["running"] = False
        return tip_return_data


    # --------------------------------- Data Acquisition ----------------------

    @auto_test()
    def get_tsys(self, timestamp=False):
        """
        Get system temperature, in units of Kelvin, i.e. power meter readings
        multipled by factors derived from flux calibration.
        
        Notes
        =====
        This is not decorated ``@async_method'' because the client call does not
        specify a callback.

        Example
        =======
        Typical result from the power meters::
          [4.800e-08, 1.1612e-07, 3.6388e-08, 7.22583e-08]
        Args:
            timestamp (boolean, optional): Return a timestamp along with readings.

        Returns:
            list/tuple: list with system temperature readings, and optionally a
                datetime.datetime object corresponding to when readings were
                requested.
        """
        self.logger.debug("get_tsys(%s): entered; calling hdwr", logtime())
        res = self.hdwr("FrontEnd", "read_PMs")
        self.logger.debug("get_tsys(%s): hdwr response: %s", logtime(), res)
        tsys = []
        for i in range(len(res)):
          reading = res[i][-1]
          if reading > 1:
            reading = 0
          tsys.append(reading*self.info["tsys_calibration"]["tsys_factors"][i])
        self.tsys = tsys
        self.logger.debug("get_tsys(%s): returns %s", logtime(), tsys)
        if not timestamp:
          return tsys
        else:
          timestamp = datetime.datetime.utcnow()
          self.logger.debug("get_tsys: timestamp: {}".format(timestamp))
          return timestamp, tsys

    @Pyro5.api.oneway
    def get_spectrum(self):
        """
        Get the spectra from all ROACHs

        This has a call to the backend client, which makes a Pyro call to the
        server
        """
        self.logger.debug("get_spectrum: invoked")
        print("get_spectra: invoked")
        response = self.equipment["Backend"].one_scan()
        self.logger.debug("get_spectrum: headers: %s", response[0])
        print(("get_spectra: headers: %s" % response[0]))
        self.get_spectrum.cb(response) # is the callback to the web client
        return response

    def get_last_spectra(self):
        """
        CURRENTLY DOES NOT WORK; see workaround below
        """
        scan_keys = list(self.gallery.keys())
        scan_keys.sort()
        self.last_scan = scan_keys[-1]
        rec_keys = list(self.gallery[last_scan].keys())
        rec_keys.sort()
        self.last_rec = rec_keys[-1]
        return last_scan, last_rec

    @Pyro5.api.oneway
    def last_scan(self):
        """
        Return the last recorded good scan set from the server
        """
        self.logger.debug("last_scan: entered")
        response = self.equipment['Backend'].last_spectra()
        self.logger.debug("last_scan: got %s", response)
        self.last_scan.cb(response)
        self.logger.debug("last_scan: finished")

    @Pyro5.api.oneway
    def last_beam_diff(self):
        last_scan, last_rec = self.last_scan()

    @Pyro5.api.oneway
    def single_scan(self, feed,
                    scan_time=60.0,
                    integration_time=5.0):
        """
        acquire a single scan of 'integration_time'-long spectra

        The server converts'integration_time' into a number of accumulations,
        that is, the number of raw spectra to make up one integration. It then
        calculates the number of spectra to make up a scan.
        """
        n_accums = math.ceil(scan_time / integration_time)

        el_offset = self.info["boresight"]["offset_el"]
        xel_offset = self.info["boresight"]["offset_xel"]

        self.logger.debug(
            ("single_scan: Setting feed to {}, "
             "PO offsets: el/xel: {}/{}").format(
                feed, el_offset, xel_offset)
        )
        self.logger.debug("single_scan: requesting feed change with %s, %s, %s",
                          feed, el_offset, xel_offset)
        self.equipment["Antenna"].feed_change(
            feed, el_offset, xel_offset
        )

        time.sleep(10)

        self.logger.debug("single_scan: calling Backend single_scan")
        self.equipment["Backend"].single_scan(n_accums)

        while not self.equipment["Backend"].scan_completed:
            time.sleep(0.01)

    @async_method
    def start_spec_scans(self, n_scans=1, n_spectra=10, int_time=1,
                               log_n_avg=4, mid_chan=None):
        """
        This is invoked by the Vue client

        The first three arguments control the integration pattern  The last two
        are used to decimate spectra for display.

        @param n_scans : number of scans
        @type  n_scans : int

        @param n_spectra : number of records per scan
        @type  n_spectra : int

        @param int_time : integration time (s)
        @type  int_time : float

        @param log_n_avg : exponent of 2 number of scans to average
        @type  log_n_avg : int

        @param mid_chan : middle channels of squished spectrum
        @type  mid_chan : int
        """
        self.logger.debug("start_spec_scans(%s): invoked for %d scans of %d spectra",
                          logtime(), n_scans, n_spectra)
        if self.obsmode == "BMSW" or self.obsmode == "BPSW" or self.obsmode == "PSSW":
          # must be even number of scans
          if n_scans % 2:
            n_scans += 1
          # start in beam 1; add boresight offsets to this!!!!!!!!!!!!!!!!!!!!!!!!!
          self.hdwr("Antenna", "set_offset_one_axis", "EL", 0)
          self.hdwr("Antenna", "set_offset_one_axis", "XEL", 0)
        self.n_scans = n_scans
        self.n_spectra = n_spectra

        # cannot make server calls when data return in SAOspec thread; do now
        # refresh weather data
        self.get_weather()
        # refresh antenna angles
        self.get_antenna_angles()
        # other stuff from servers
        self.bandwidth = self.backend.bandwidth
        self.num_chan = self.backend.num_chan
        # ``obsfreq`` needs to be based on DC channel
        self.obsfreq = self.frontend.data['frequency']*1e6 
        self.record_int_time = int_time
        self.polcodes = self.backend.polcodes()
        self.logger.debug("start_spec_scans: integration time is %s", int_time)
        # save these attributes for returning data to plot
        self.log_n_avg = log_n_avg
        if mid_chan:
          self.mid_chan = mid_chan
        else:
          self.mid_chan = (32768/2)/2**log_n_avg
        # start
        self.scans_left = n_scans
        self.spectra_left = n_spectra
        self.equipment['Backend'].start_recording(parent=self,
                                               n_accums=n_spectra,
                                               integration_time=int_time)
        self.logger.debug("start_spec_scans: finished")
        self.start_spec_scans.cb({"left": self.scans_left}) # sent to client

    def integr_done(self):
        """
        process the output from start_handler

        This mainly handles dicts of the form
        {'scan':   int,
         'record': int,
         'titles': list,
         'type':   str,
         'data':   list[lists]}
        where the inner lists are rows of a table.
        """
        self.logger.debug("integr_done: called")
        res = self.backend.cb_receiver.queue.get()
        starttime = nowgmt()
        self.logger.debug("integr_done: got %s message at %s", 
                          type(res), starttime)
        if type(res) == dict:
          self.logger.debug("integr_done: invoked with keys: %s",
                            list(res.keys()))
          # process a spectrum table
          if "type" in res and res["type"] == "data":
            # reformat 
            # get the ROACH input signals
            self.get_signals()
            # format table for Google Charts
            spectra_table = self.display_data(res)
            # notify the client that a record has been received
            try:
              self.start_spec_scans.cb({"type": "start",
                                        "scan": res["scan"],
                                        "record": res["record"],
                                        "table": spectra_table})
            except AttributeError as details:
              self.logger.debug("integr_done: cb-2 failed: %s", str(details))
              pass
            self.spectra_left -= 1
            self.logger.debug("integr_done: %d spectra left", self.spectra_left)
            self.logger.debug("integr_done: elapsed time %s", nowgmt()-starttime)
            # add to FITS row and add to FITS file when spectra_left = 0.
            self.add_data_to_FITS(res)
            # beam and/or position switching if appropriate.
            if self.spectra_left:
              # not yet done
              pass
            else:
              # finish the scan
              self.logger.debug("integr_done: spectra done")
              # manage antenna according to observing mode
              if self.obsmode[4:] == "BMSW" or self.obsmode[4:] == "PBSW":
                self.logger.debug("integr_done: obsmode is %s", self.obsmode)
                self.logger.debug("integr_done: %d scans left", self.scans_left)
                # beam sw. or beam and pos. sw.; # switch beams
                if self.scans_left % 2:
                  # odd scans are beam 2
                  self.el_offset = 0
                  self.xel_offset = 0
                else:
                  # reference beam offset
                  self.el_offset = 14
                  self.xel_offset = 31
                self.logger.debug("integr_done: sending offset commands EL=%d, XEL=%d",
                                  self.el_offset, self.xel_offset)
                self.hdwr("Antenna", "set_offset_one_axis", "EL",  self.el_offset)
                self.hdwr("Antenna", "set_offset_one_axis", "XEL", self.xel_offset)
                # report new position to client
                self.start_spec_scans.cb({"xel_offset": self.xel_offset,
                                          "el_offset": self.el_offset})
              self.scans_left -= 1
              self.logger.debug("integr_done: now %d scans left", self.scans_left)
              if self.scans_left:
                self.equipment['Backend'].start_recording(parent=self,
                                                          n_accums=self.n_spectra,
                                         integration_time=self.record_int_time)
            # forward to client
            try:
              last_data = {"type":   "saved",
                           "scan":   res["scan"],
                           "record": res["record"]}
              self.start_spec_scans.cb(last_data)
              #fd = open(self.last_spectra_file, "w")
              #json.dump(last_data, fd)
              #fd.close()
            except AttributeError as details:
              self.logger.debug("integr_done: cb-3 failed: %s", str(details))
              #pass
        # did not get a dict but a list instead
        elif type(res) == list:
          self.logger.error("integr_done: got 'list' type result")
          # just the titles
          self.logger.debug("integr_done: got %s", res[0])
          self.start_spec_scans.cb(res)
        # got something other than dict or list
        else:
          self.logger.debug("integr_done: got type {}".format(type(res)))
          self.start_spec_scans.cb(res)
        self.logger.debug("integr_done: finished")
        
    def squish(self, table_array, logY=True, n_avg=None, mid_chan=None):
        """
        Compress columns in a spectrum table formatted for Google Charts

        @param table_array : spectrum table as a numpy array
        """
        if n_avg == None:
          n_avg = 2**self.log_n_avg # log2 number of channels to average
        else:
          n_avg = 2**n_avg
        self.logger.debug("squish: will average channels by %d", n_avg)
        if mid_chan == None:
          mid_chan = self.mid_chan # not used
        #table_array = np.array(table)
        num_chans, num_specs = table_array.shape
        self.logger.debug("squish: table has %d rows and %d columns",
                          num_chans, num_specs)
        new_array = table_array.reshape(num_chans//n_avg, n_avg, num_specs)
        self.logger.debug("squish: new table shape is %s", new_array.shape)
        squished_array = new_array.mean(axis=1)
        self.logger.debug("squish: squished array: %s", squished_array)
        if logY:
          data_columns = squished_array[:, 1:]
          log_array = np.ma.log10(data_columns).data
          self.logger.debug("squish: using log values.")
          squished_array[:, 1:] = log_array
        return squished_array

    def identify_signal(roachname):
        """
        Returns signal name, polarizatio and beam for a ROACH
        """
        index = self.roachnames.index(roachname)
        return {"name": self.fe_signals[index],
                "pol":  self.pols[index],
                "beam": self.beams[index]}

    def get_signals(self):
        """
        Gets mappings for beam and pol numbers for ROACH and signal names

        After this has been run::
          In [4]: self.pols
          Out[4]: [0, 1, 0, 1]

          In [5]: self.beams
          Out[5]: [0, 0, 1, 1]

          In [6]: self.backend.roachnames
          Out[6]: [u'sao64k-1', u'sao64k-2', u'sao64k-3', u'sao64k-4']

          In [7]: self.signal_end
          Out[7]:
          array([['sao64k-1', 'sao64k-3'],
                 ['sao64k-2', 'sao64k-4']], dtype='|S8')

          In [8]: self.fe_signals
          Out[8]: ['F1E22I', 'F1H22I', 'F2E22I', 'F2H22I']

          In [9]: self.rx_signals
          Out[9]: ['R1E22I', 'R1H22I', 'R2E22I', 'R2H22I']
        """
        crossover_mapping = {False: {"R1": "F1", "R2": "F2"},
                             True:  {"R1": "F2", "R2": "F1"}}
        pol_mapping = {"E": 0, "H": 1, "L": 0, "R": 1}
        be = self.backend
        self.logger.debug("get_signals: ROACH names: %s", self.roachnames)
        input_names = be.inputs.keys()
        self.logger.debug("get_signals: inputs: %s", input_names)
        self.rx_signals = [ be.inputs[name].signal.name
                                                 for name in input_names ]
        self.logger.debug("get_signals: receiver signals: %s", self.rx_signals)
        crossover = self.receiver.crossSwitch.get_state()
        self.fe_signals = []
        self.pols = []
        self.beams = []
        self.SB = []
        for signal in self.rx_signals:
          index = self.rx_signals.index(signal)
          rxID = signal[:2]
          feedID = crossover_mapping[crossover][rxID]
          feed_num = int(feedID[1])-1
          self.beams.append(feed_num)
          pol_num = pol_mapping[signal[2]]
          self.pols.append(pol_num)
          feed_sig = signal.replace(rxID, feedID)
          self.fe_signals.append(feed_sig)
          self.logger.debug("get_signals: %s is on feed %d, pol %d",
                             self.roachnames[index], feed_num, pol_num)
          self.SB.append(signal[-1]) # last character
        self.logger.debug("get_signals: front end signals: %s", self.fe_signals)
        self.logger.debug("get_signals: pol codes: %s", self.pols)
        self.logger.debug("get_signals: beam codes: %s", self.beams)
        self.signal_end = np.empty((2,2),dtype='|S8') # 2D array with indices pol,beam
        for roach in self.roachnames:
          index = self.roachnames.index(roach)
          self.signal_end[self.pols[index],self.beams[index]] = roach

    def difference_beams(self, res):
        """
        Subtract beam 2 from beam 1 for each polarization
        """
        diffs = {}
        for pol in self.pols:
          beams = self.signal_end[pol,:]
          bm1roach = self.signal_end[pol, beams[0]]
          bm2roach = self.signal_end[pol, beams[1]]
          diffs[pol] = res["data"][bm1roach] - res["data"][bm2roach]
        return diffs

    def format_as_nparray(self, res):
        """
        convert dict of ROACH spectra to 2D array
        """
        scan = res["scan"]
        record = res["record"]
        data = res["data"]
        self.logger.debug("format_as_nparray: for scan %d record %d", scan, record)
        datakeys = list(data.keys())
        self.logger.debug("display_data: data keys: %s", datakeys)
        datakeys.sort()
        datalists = []
        for roach in datakeys:
          self.logger.debug("display_data: %s has %d samples", roach, len(data[roach]))
          datalists.append(data[roach])
        data_array = np.array(datalists).transpose()
        return data_array
        
    def display_data(self, res):
        """
        This creates a gallery of spectral data sets suitable got Google Charts

        'gallery' is indexed with [scan] and [record]self.backend.num_chan

        @param res : numpy 2D array of spectra
        """
        scan = res["scan"]
        record = res["record"]
        data = res["data"]
        self.logger.debug("display_data: for scan %d record %d", scan, record)
        # convert list of dicts to a table
        self.data_array = self.format_as_nparray(res)
        # add signal names
        feed_sig = self.fe_signals
        squished = self.squish(self.data_array).tolist()
        spectra_table = [['Frequency'] + feed_sig] + squished
        if scan in self.gallery:
          pass
        else:
          self.gallery[scan] ={}
        self.gallery[scan][record] = spectra_table
        self.logger.debug("display_data: stored scan %d record %d", scan, record)
        return spectra_table

    def add_data_to_FITS(self, res):
        """
        Polulate the next row of the FITS binary table

        In the case where 'record' = 0, all the columns are populated.  When it
        is not, then only the time-dependent columns get added to.
        """
        scan, record, data = res["scan"], res["record"], res["data"]
        # index is the row number of the scan in the set of scans
        index = scan - 1 # FITS scans are 1-based
        if scan in self.scans:
          pass
        else:
          self.scans.append(scan)
        if record == 1:
          # these data are constant for the scan
          self.source = self.info["point"]["current_source"]
          if self.source:
            self.bintabHDU.data[index]['OBJECT'] = self.source['name']
            self.RA =  self.source['ra']*24/math.pi    # J2000 from radians
            self.dec = self.source['dec']*180/math.pi  # J2000 from radians
          else:
            self.logger.warning("add_data_to_fits: no source seleted")
            self.bintabHDU.data[index]['OBJECT'] = "no source"
            self.RA = 0.0
            self.dec = 0.0
            self.bintabHDU.data[index]['VELOCITY'] = 0
          self.bintabHDU.data[index]['EXPOSURE'] = self.record_int_time
          self.bintabHDU.data[index]['BANDWIDT'] = self.bandwidth
          self.bintabHDU.data[index]['SCAN'] = scan   # int
          self.bintabHDU.data[index]['CYCLE'] = 1     # int (0 means bad row)
          self.bintabHDU.data[index]['OBSMODE'] =  self.obsmode
          # self.bintabHDU.data[index]['SIG']
          # self.bintabHDU.data[index]['CAL']
          # self.bintabHDU.data[index]['TCAL']
          self.bintabHDU.data[index]['RESTFREQ'] = self.restfreq
          self.bintabHDU.data[index]['OBSFREQ'] = self.obsfreq
          self.bintabHDU.data[index]['VELDEF'] = veldef
          if self.source:
            if "velocity" in self.source["info"]:
              self.logger.debug("add_data_to_FITS: source velocity: %s",
                                self.source["info"]["velocity"])
              self.logger.debug("add_data_to_FITS: source velocity type: %s",
                                type(self.source["info"]["velocity"]))
              self.bintabHDU.data[index]['VELOCITY'] = \
                                                self.source["info"]["velocity"]
            else:
              self.logger.warning("add_data_to_FITS: %s has no velocity",
                                self.source['name'])
              self.bintabHDU.data[index]['VELOCITY'] = 0
          else:
            # velocity already set to 0 above
            pass
          self.bintabHDU.data[index]['EQUINOX'] = equinox
          # data axis specifications
          # frequency
          self.bintabHDU.data[index]['CRVAL1'] = \
                                          self.bintabHDU.data[index]['OBSFREQ']
          self.bintabHDU.data[index]['CDELT1'] = \
                           self.bintabHDU.data[index]['BANDWIDT']/self.num_chan
          self.bintabHDU.data[index]['CRPIX1'] = 0
          if self.SB[0] == 'U': # assume all downconverters the same
            self.bintabHDU.data[index]['SIDEBAND'] = +1
            self.bintabHDU.data[index]['CDELT1'] = \
                   self.bintabHDU.data[index]['BANDWIDT']/self.num_chan
          elif self.SB[0] == 'L':
            self.bintabHDU.data[index]['SIDEBAND'] = -1
            self.bintabHDU.data[index]['CDELT1'] = \
                  -self.bintabHDU.data[index]['BANDWIDT']/self.num_chan
          else:
            self.logger.error("IF mode %s is not supported", self.SB[0])
          # second and third data axes (coordinates)
          RAstr = str(self.RA)
          decstr = str(self.dec)
          coords = ' '.join((RAstr, decstr))
          c = astropy.coordinates.SkyCoord(coords, unit=(u.hourangle,u.deg))
          self.bintabHDU.data[index]['CRVAL2'] = c.ra.hourangle
          self.bintabHDU.data[index]['CRVAL3'] = c.dec.deg
          # fourth data axis (polarization)
          refval, delta = self.backend.polcodes()
          self.bintabHDU.data[index]['CRVAL4'] = refval
          self.bintabHDU.data[index]['CDELT4'] = delta
        # these data change for every record
        # current time
        now = time.gmtime() # struct_time tuple
        date_obs = time.strftime("%Y/%m/%d", now) # str
        self.bintabHDU.data[index]['DATE-OBS'] = date_obs
        midnight = time.mktime(dateutil.parser.parse(date_obs).timetuple())
        UNIXtime = calendar.timegm(now) # int
        # for convenience in Python; not FITS standard
        self.bintabHDU.data[index]['UNIXtime'][0,record,0,0,0,0] = UNIXtime
        self.bintabHDU.data[index]['TIME'] = UNIXtime - midnight
        # sidereal time
        #astrotime = astropy.time.Time(UNIXtime, format='unix', scale='utc',
        #                              location=self.location)
        #astrotime.delta_ut1_utc = 0 # forget about fraction of second and IERS
        astrotime = UnixTime_to_datetime(UNIXtime)
        self.bintabHDU.data[index]['LST'][0,record,0,0,0,0] = (
          A.greenwich_sidereal_time(
                    now.tm_year, now.tm_yday + (now.tm_hour+now.tm_min/60.)/24.
                  )
                  - self.location.lon.hour
          ) % 24
        self.bintabHDU.data[index]['VFRAME'] = \
                     V_LSR(self.RA, self.dec, self.telescope.number, astrotime)
        self.bintabHDU.data[index]['RVSYS'] = \
                                       self.bintabHDU.data[index]['VELOCITY'] \
                                     - self.bintabHDU.data[index]['VFRAME']
        #    the following could be changed to one per scan
        self.bintabHDU.data[index]['TAMBIENT'][0,record:0,0,0,0] = self.temperature
        self.bintabHDU.data[index]['PRESSURE'][0,record:0,0,0,0] = self.pressure
        self.bintabHDU.data[index]['HUMIDITY'][0,record:0,0,0,0] = self.humidity
        self.bintabHDU.data[index]['WINDSPEE'][0,record:0,0,0,0] = self.windspeed
        self.bintabHDU.data[index]['WINDDIRE'][0,record:0,0,0,0] = self.winddirection
        self.bintabHDU.data[index]['BEAMXOFF'][0,record:0,0,0,0] = self.xel_offset
        self.bintabHDU.data[index]['BEAMEOFF'][0,record:0,0,0,0] = self.el_offset
        # more columns
        # get the system temperatures
        tsys = self.tsys
        self.logger.debug("add_data_to_FITS: TSYS: %s", tsys)
        # data array has shape (32768,5)
        #self.data_array = np.array(data)
        self.logger.debug("add_data_to_FITS: data_array shape is %s",
                          self.data_array.shape)
        #data_only = self.data_array[:,1:] # the first column is frequency
        self.logger.debug("add_data_to_FITS: data_only shape is %s",
                          self.data_array.shape)
        for ridx in range(4):
          roach = self.roachnames[ridx]
          pol = self.pols[ridx]
          beam = self.beams[ridx]
          data = self.data_array[:,ridx]
          self.bintabHDU.data[index]['data'][beam,record,pol,0,0,:] = data
          self.bintabHDU.data[index]['TSYS'][beam,record,pol,0,0,0] = tsys[ridx]
          self.logger.debug(
          "add_data_to_FITS: stored sc %d, rec %d, pol %d, bm %d for %s at row %d",
                          scan, record, pol, beam, roach, index)
        if self.spectra_left == 0:
          # save scan
          self.save_FITS()

    @Pyro5.api.oneway
    def two_beam_nod(self,
                     cycles=1,
                     scan_time=60.0,
                     integration_time=None):
        """
        """
        default_integration_time = {
            "Antenna": 2.0,
            "FrontEnd": 2.0,
            "Receiver": 2.0,
            "Backend": 1.0
        }

        if integration_time is None:
            integration_time = default_integration_time
        default_integration_time.update(integration_time)
        integration_time = default_integration_time.copy()
        self.logger.info(
            "two_beam_nod: cycles: {}, scan_time: {}".format(
                cycles, scan_time))

        # for equip in ["Antenna", "Receiver", "FrontEnd"]:
        #for equip in ["Antenna", "Receiver"]:
        #    if hasattr(self.equipment[equip], "daemon"):
        #        if not self.equipment[equip].is_alive():
        #            self.equipment[equip].daemon = True
        #
        #    self.equipment[equip].start_recording(
        #        interval=integration_time[equip]
        #    )
        #    self.logger.debug("two_beam_nod: {} recording".format(equip))

        for cycle in range(cycles):
            for feed in range(2):
                self.two_beam_nod.cb({"done": False,
                                      "cycle": cycle,
                                      "feed": feed})
                self.single_scan(
                    feed,
                    scan_time=scan_time,
                    integration_time=integration_time["Backend"]
                )

        #for equip in ["Antenna", "Receiver", "FrontEnd"]:
        #    self.equipment[equip].stop_recording()
        #    self.logger.debug(
        #        "two_beam_nod: {} recording stopped".format(equip))
        self.two_beam_nod.cb({"done": True})

    @Pyro5.api.oneway
    def single_beam_nodding(self,
                            cycles=1,
                            time_per_scan=60.0,
                            integration_time=5.0,
                            power_meter_monitor_interval=2.0,
                            antenna_monitor_interval=2.0):
        raise NotImplementedError()

# ---------------------------- Miscellaneous Methods --------------------------

    @async_method
    def set_obsmode(self, new_mode):
        """
        called by client to set observing mode
        """
        self.obsmode = new_mode
        self.logger.debug("set_obsmode(%s): mode is now %s",
                          logtime(), self.obsmode)

    def set_rest_freq(self, new_freq):
        self.restfreq = new_freq
        self.logger.info("set_rest_freq (%s): rest frequency is now %f",
                         logtime(), self.restfreq)

    def server_time(self, *args, **kwargs):
        self.logger.debug("args: %s", args)
        self.logger.debug("keyword args: %s", kwargs)
        return datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss")

    def get_configs(self):
        """
        Gets a dict with context names and paths to their configurations
        """
        from MonitorControl.Configurations import configs
        return configs

    def help(self):
      return """
     Attributes:
        observatory (MonitorControl.Observatory): Observatory instance
        equipment (dict): dictionary describing antenna/station hardware
        boresight_manager (BoresightManager): post processing manager object
            for retrieving old boresight results.
        info (dict): dictionary containing information about current status
            of different long running calibration/observation methods, as
            well as sources, and verifiers.

    Methods:
      Start-up and shut-down methods:
        set_info(path, val)
        get_info(path=None)


        save_info()
        load_info()
        close()
      Hardware control:
        configure(import_path, *args, **kwargs)
        hdwr(hdwr, method_name, *args, **kwargs)
        list_hdwr()
      Source management:
        load_sources(loader="json")
        get_sources(source_names=None, when=None, filter_fn=None, formatter=None)
        report_source_info(name_or_dict, units="degrees")
        is_within(name_or_dict, bounds, axis="el")

      Observatory details:
        _get_observer_info_dict()

      Antenna control:
        point(name_or_dict)

      Data acquisition}:
        get_tsys(timestamp=False): return list of Tsys obtained from HP power meters
        single_scan(feed, scan_time=60.0, integration_time=5.0): returns a single
          spectrum
        two_beam_nod(cycles=1, scan_time=60.0, integration_time=None): starts a
          sequence of spectral scans in beam and position switching mode
        single_beam_nodding(cycles=1, time_per_scan=60.0, integration_time=5.0,
          power_meter_monitor_interval=2.0, antenna_monitor_interval=2.0): starts
          a position switching sequence

      Calibration:
        scanning_boresight(el_previous_offset, xel_previous_offset,
          limit=99.0, sample_rate=0.3, rate=3.0, settle_time=10.0,
          src_name_or_dict=None,two_direction=True, additional_offsets=None,
          channel=0, attrs=None)
        stepping_boresight(el_previous_offset, xel_previous_offset,
          n_points=9, integration_time=2, settle_time=10.0, two_direction=True,
          src_name_or_dict=None, additional_offsets=None, channel=0, attrs=None)
        get_boresight_analyzer_object(file_path)
        get_most_recent_boresight_analyzer_object()
        process_minical_calib(cal_data, Tlna=25, Tf=1, Fghz=20, TcorrNDcoupling=0)
        tsys_calibration(settle_time=10.0, pm_integration_time=5.0)
        stop_tsys_calibration()
        tip()

      File management:
        _create_calibration_file_path(...):
        _create_calibration_file_obj(...):
        get_boresight_file_paths(...):

      Miscellaneous:
        server_time(): returns current time
      """

    @async_method
    def get_projects(self):
      """
      get a list of all the projects
      """
      projects = []
      for project in projcfg.get_projects():
        projects.append(project)
      projects.sort()
      self.get_projects.cb(projects)
      return projects

    @async_method
    def get_activities(self):
      """
      get a list of all the activities of the current project
      """
      project = self.info['project']['name']
      activities = projcfg.get_activity()[project]
      self.logger.debug("get_activities: activities: %s", activities)
      activities.sort()
      self.get_activities.cb(activities)
      return activities

    @async_method
    def get_equipment(self):
      """
      get a list of all the devices in the current configuration
      """
      devices = {}
      for device,obj in list(self.equipment.items()):
        if obj != None:
          devices[device] = str(obj)
      self.get_equipment.cb(devices)
      return devices

    @async_method
    def change_project(self, project, activity=None, context=None):
      """
      select new project
      """
      self.info['sources'] = {}
      self.info['verifiers'] = {}
      self.info['project']['name'] = project
      self.info['project']["source_dir"] = projects_dir+project+"/Observations"
      self.project = project
      if activity:
        self.activity = activity
      else:
        self.activity = self.get_default_activity(self.project)
      self.logger.debug("change_project: activity is %s", self.activity)
      if context:
        if context in list(self.get_configs().keys()):
          observatory, equipment = station_configuration(context)
      else:
        context = configs[self.project][self.activity]
        self.logger.debug("change_project: context is %s", context)
        if context in list(self.get_configs().keys()):
          observatory, equipment = station_configuration(context)
        else:
          # assume a form AAAADDB
          activity = context[:4]
          dss = int(context[4:6])
          band = context[6]
          now = time.gmtime()
          timestr = "%02d%02d" % (now.tm_hour, now.tm_min)
          observatory, equipment = std_configuration(None, self.activity, dss,
                                          now.tm_year, now.tm_yday, timestr, band)

    @async_method
    def get_activitys_project(self, activity):
      """
      get the project associated with the current activity
      
      This is just for an information request by the client.  It does not change
      the current ptoject.
      """
      self.logger.debug("get_activitys_project: called for %s", activity)
      project = projcfg.activity_project(activity)
      self.logger.debug("get_activitys_project: project is %s", project)
      self.get_activitys_project.cb(project)
      return project

    @async_method
    def get_default_activity(self, project):
      """
      This assumes a specific format for the project and activity names.
      
      This is just for an information request by the client.  It does not change
      the current ptoject.
      """
      self.logger.debug("get_default_activity: called for %s", project)
      activity = get_auto_project(project).split("_")[1]+'0'
      self.logger.debug("get_default_activity: activity is %s", activity)
      self.get_default_activity.cb(activity)
      return activity

    @async_method
    def get_project_activities(self, project):
      """
      Get the activities associated with a project.

      This assumes a specific format for the project and activity names. It
      should probably go in the Automation module.
      """
      self.logger.debug("get_project_activities: called for %s", project)
      activity_root = get_auto_project(project).split("_")[1]
      proj_activities = []
      for activity in self.get_activities():
        if activity_root in activity:
          proj_activities.append(activity)
      proj_activities.sort()
      self.logger.debug("get_project_activities: activities are %s",
                        proj_activities)
      self.get_project_activities.cb(proj_activities)
      return proj_activities


# ================================= Program ===================================

if __name__ == "__main__":
    
    def create_arg_parser():
      """
      create an argument parser and define arguments
      """
      import argparse
      parser = argparse.ArgumentParser(description="Fire up DSS control server.")
      parser.add_argument("--verbose", "-v",
                        dest="verbose", required=False,
                        action="store_true", default=True,
                        help="In verbose mode, the log level is DEBUG; default: False")
      parser.add_argument("--simulated", "-s",
                        dest="simulated", required=False,
                        action="store_true", default=True,
                        help="In simulated mode, DSS Server won't attempt to "
                             +"connect to hardware servers. Default: True")
      parser.add_argument("--flask", "-f",
                        dest="flask", required=False,
                        action="store_true", default=True,
                        help="Run server as flask server; default: True")
      parser.add_argument("--flaskio", "-fio",
                        dest="flaskio", required=False,
                        action="store_true", default=True,
                        help="Run server as flask io server; default: True")
      return parser

    # parsed is an object with arguments as attributes
    parsed = create_arg_parser().parse_args()

    # specify logging level
    level = logging.DEBUG
    if not parsed.verbose:
        level = logging.INFO
    mylogger = setup_logging(logLevel=level)

    logging.getLogger("support").setLevel(logging.DEBUG)

    mylogger.debug("arguments: %s", parsed)

    # create and launch the central server
    #server = DSSServer(observatory, equipment,
    #                   logger=logging.getLogger(__name__+".DSSServer"))
    server = DSSServer('WBDC2_K2')

    try:
      if parsed.flask:
        app, server = DSSServer.flaskify(server)
        app.run(port=5000)
      elif parsed.flaskio:
        app, socketio, server = DSSServer.flaskify_io(server)
        socketio.run(app, port=5000, debug=False, log_output=False)
      else:
        server.launch_server(
            objectId=equipment["Antenna"].name,
            objectPort=50015, ns=False, threaded=False, local=True
        )
    except (KeyboardInterrupt, SystemExit):
      mylogger.warning("Server terminated at %s",
                       datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss"))
      server.close()

