"""
Pyro interface to DSSServer

This is run on the server host and will start a DSSServer instance as an object
in this program. It requires that the NMC server, the front end server, 
the WBDC server, and the spectrometer server are running.

Usage instructions are at https://ra.jpl.nasa.gov:8443/dshaff/dss-monitor-control
"""
import datetime
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)
from MonitorControl.central_server import CentralServer

from MonitorControl.Configurations  import station_configuration
from support.logs import setup_logging
from support.pyro.pyro5_server import Pyro5Server

__version__ = "1.0.2"
default_level = logging.DEBUG

module_levels = {
    "support": logging.WARNING,
    "MonitorControl": logging.DEBUG,
    "MonitorControl.FrontEnds": logging.DEBUG,
    "MonitorControl.apps.postproc.util": logging.INFO
}

setup_logging(logger=logging.getLogger(""), 
              logLevel=default_level)

for module in module_levels:
    logging.getLogger(module).setLevel(module_levels[module])

class PyroServer(CentralServer, Pyro5Server):
  """
  """
  def __init__(self, context,        # required
                     project="TAMS",
                     import_path=None,
                     config_args=None,
                     config_kwargs=None,
                     boresight_manager_file_paths=None,
                     boresight_manager_kwargs=None,
                     **kwargs):
    """
    Args:
      context:                      (str) configuration name
      project:                      (str)
      import_path:                  (str) a path whose corresponding module
                                          has a station_configuration function
      config_args:                  (tuple/list) passed to station_configuration
      config_kwargs:                (dict) passed to station_configuration
      boresight_manager_file_paths: t.b.d.
      boresight_manager_kwargs:
      kwargs:
    """
    CentralServer.__init__(self,
                           parent=self,
                           context=context,
                           project=project,
                           import_path=import_path,
                           config_args=config_args,
                           config_kwargs=config_kwargs,
                           boresight_manager_file_paths=\
                                                   boresight_manager_file_paths,
                           boresight_manager_kwargs=boresight_manager_kwargs,
                           **kwargs)
    Pyro5Server.__init__(self, obj=self, **kwargs)
    

