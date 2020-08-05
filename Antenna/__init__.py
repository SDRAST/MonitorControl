import logging
import sys
from math import pi

import MonitorControl as MC
import Astronomy.DSN_coordinates as DSN

logger = logging.getLogger(__name__)


class Telescope(MC.Device, DSN.DSS):
  """
  Defines the Telescope class.

  This class has methods and attributes to describe (an eventually
  control) a radio telescope.
  Telescope inherits from the Observatory class

  Since this is for a single-dish telescope, there should be only one
  instance of this class. It is identified with the FITS keyword TELESCOP.

  Attributes
  ==========
  
  A Telescope() instance has these additional attributes::
   - active -       can be set to False to indicate that it is unservicable
   - data -         a dictionary with parameters for location, pointing, etc.
   - front_ends -   a list of front end objects on the telescope.  This is
                    generated automatically as the front-end objects are
                    created
   - receivers -    a list of down-converter objects on the telescope
   - backends   - a list of signal processing and recording devices
  """
  
  def __init__(self, obs, dss=0, LO=None, active=True):
    """
    Initializes Telescope object

    The Telescope object is passed the Observatory instance (object) of
    which it is a sub-class and a dss number.  If dss is not specified,
    the user must call the methods 'define_site' and 'define_xyz'.

    Note thatan Observatory object is not an Observing_Device, so it is
    not the 'parent' of telescope.

    @param obs : observatory where the telescope is.
    @type  obs : Observatory() instance

    @param dss : DSN station number
    @type  dss : int

    @param LO : frequency reference for the telescope, if any
    @type  LO : Synthesizer() instance
    """
    if dss == 0:
      logger.error("Please specify a DSN station number with 'dss='")
      sys.exit(0)
    name = "DSS-"+str(dss)
    mylogger = logging.getLogger(logger.name+".Telescope")
    mylogger.debug("__init__: for Telescope %s", name)
    DSN.DSS.__init__(self, dss)
    MC.Device.__init__(self, name)
    self.logger = mylogger
    # An observatory has no outputs of type Port but this at least gives some
    # Device as input.
    self.inputs = {obs.name: obs}
    (self['longitude'],self['latitude'],self['elevation'],tz,name,diam) = \
         -180.*self.long/pi, 180*self.lat/pi, self.elev, \
         self.timezone, self.name, self.diam
    #        get_geodetic_coords(dss=int(dss))
    (self['geo-x'],self['geo-y'],self['geo-z']) = self.xyz
    #        get_cartesian_coordinates('DSS '+str(dss))
    self.logger.debug("__init__: coordinates obtained for %s; making Ports with Beam",
                      self)
    self.outputs[self.name] = MC.Port(self, self.name, signal=MC.Beam(str(dss)))
    self.outputs[self.name].signal['dss'] = dss
    self.logger.debug("__init__: Telescope initialized\n")


class Antenna(Telescope):
    """
    A subclass of Telescope that can connect to a server that is currently
    running.
    """
    def __init__(self, obs, dss=0, LO=None, active=True, hardware=False):
        """
        Args:
            obs (MonitorControl.Observatory): passed to superclass
        Keyword Args:
            dss (int): passed to superclass
            LO (object): passed to superclass
            active (bool): passed to superclass
            hardware (bool): whether or not to connect to hardware
        """

        super(Antenna, self).__init__(obs, dss=dss, LO=LO, active=active)

        if hardware:
            tunnel = Pyro4Tunnel(remote_server_name="localhost",
                                local=True,
                                ns_port=50000,
                                ns_host="localhost")
            self.hardware = tunnel.get_remote_object("APC")
        else:
            self.hardware = False

    def __getattr__(self, name):
        if self.hardware != False:
            return getattr(self.hardware, name)
