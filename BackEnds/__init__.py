"""
Superclass for backend devices

Classes::

  Backend(Device) which has private class
    DSProc(Device), which has private class
      Channel(Device)
  Processor(Device)
  
"""
import logging
import numpy

import MonitorControl as MC
import support.lists

logger = logging.getLogger(__name__)
module_logger = logger

class Backend(MC.Device):
  """
  Defines the Backend class, some assembly of DSP hardware.

  Ultimately the signal is processed and recorded.  Although only the
  properties of the recorded signal are required for data analysis, it is
  good documentation practice to identify the device which records the signal
  so the FITS keyword BACKEND is strongly recommended.

  This is an base (or ancestor) class. A Backend may use multiple processors
  represented by the private class DSProc.  A ROACH is one realization of a
  DSProc. All DSProc instances must have the same firmware to implement
  parallel signal paths.

  Public attributes, in addition to those defined for the Device superclass::
    - DSProc - private class for hardware
  """

  def __init__(self, name, inputs=None, output_names=None, active=True,
               processors=None):
    """
    Initialize a Backend object

    A Backend instance takes in data from one or more of its inputs, processes
    them into one or more outputs and passes them on to identical Processor
    objects (data anlysis computers).

    @param name : a name for the back end
    @type  name : str

    @param active : set to False if this device is unavailable
    @type  active : bool

    @param processors : ordered list of digital signal processing devices
    @type  processors : list of str
    """
    mylogger = logging.getLogger(module_logger.name+".Backend")
    self.name = name
    mylogger.debug(" initializing %s", self)
    if output_names:
      if (MC.valid_property(output_names,'product', abort=False) or
          MC.valid_property(output_names,'stokes', abort=False)  or
          MC.valid_property(output_names,'stats', abort=False)     ):
        pass
      else:
        raise MC.MonitorControl.Error(output_names,
                             "does not have a valid statistic code")
    MC.Device.__init__(self, name, inputs=inputs, output_names=output_names,
                    active=active)
    self.name = name
    self.logger = mylogger
    self.logger.debug(' inputs: %s', inputs)
    self.data['bandwidth'] = 0.0
    self.data['freqres'] = 0.0
    self.data['refpix'] = 0

  def start(self, integration_time):
    """
    Start taking data.

    @param integration_time : stop after this many seconds; raise 'done' flag'
    @type  integration_time : float
    """
    pass

  def stop(self,save=True):
    """
    Stop taking data.

    @param save : True to save data, False to discard.
    @type  save : Boolean
    """
    if save == True:
      self.read()

  def read(self):
    """
    Read data into memory.
    """
    pass

  def polcodes(self):
    """
    Returns the parameters defining the STOKES axis of SDFITS table from signals

    This returns the NRAO FITS codes for the polarizations of the signals
    entering a backend.
    """
    pols = []
    for inpt in self.inputs.keys():
      # ignore absent inputs
      if self.inputs[inpt].signal:
        pols.append(self.inputs[inpt].signal['pol'])
    pols = support.lists.unique(pols)
    pols.sort()
    # convert to NRAO code
    if pols == ['E', 'H']:
      refval = -5; delta = +1
    elif pols == ['L', 'R']:
      refval = -2; delta = -1
    return refval, delta


  class DSProc(MC.Device):
    """
    A DSProc may have multiple inputs (Channel instances) and outputs (DataChl
    instances).  For example, a Stokes spectrometer would have two inputs (say
    RCP and LCP) and four outputs, probably RR*, LL*, RL* and R*L or maybe
    I, Q, U and V. Derived classes (or subclasses) of this class realize actual
    hardware.

    Public attributes::
      logger - logging.Logger instance
      name   - unique strict identifying the backend
      parent - Backend instance to which this belongs

    Attributes inherited from Device::
       - name    - user-defined unique identifier string for the instance
       - data    - dictionary with parameters specific to the class
       - active  - True if working, False if not
       - inputs  - instances of devices which provide signal inputs
       - outputs - instances of devices which accept signals from this device
    """
    def __init__(self, parent, name, inputs=None, output_names=None,
                 active=True):
      """
      """
      mylogger = logging.getLogger(module_logger.name+".Backend.DSProc")
      self.name = name
      self.parent = parent
      mylogger.debug(" initializing for %s", self)
      MC.Device.__init__(self, name, inputs=inputs, output_names=output_names,
                    active=active)
      self.logger = mylogger
      self.logger.debug(' inputs from superclass: %s', self.inputs)
      self.logger.debug(' superclass initialized for %s', self)

    class Channel(MC.Device):
      """
      A Channel is a superclass for a single signal path through a DSProc,
      which receives its signal from a parent Backend input.

      Public Attributes::
        - logger
        - parent

      Attributes inherited from Device::
        - name    - user-defined unique identifier string for the instance
        - data    - dictionary with parameters specific to the class
        - active  - True if working, False if not
        - inputs  - instances of devices which provide signal inputs
        - outputs - instances of devices which accept signals from this device
      """
      def __init__(self, parent, name, inputs=None, output_names=None,
                           active=True):
        """
        Make the parent aware that this child exists
        """
        mylogger = logging.getLogger(
                                  module_logger.name+".Backend.DSProc.Channel")
        self.name = name
        self.parent = parent
        mylogger.debug(" initializing %s", self)
        MC.Device.__init__(self, name, inputs=inputs, output_names=output_names,
                        active=active)
        self.logger = mylogger
        self.logger.debug(' inputs: %s', self.inputs)

    class DataChl(MC.Device):
      """
      A DataChl is a superclass for a single output from a Backend

      The destination of a DataChl is a process on another host identified with
      a socket.

      Public Attributes::
        - parent

      Attributes inherited from Observing_Device::
        - name         - user-defined unique identifier string for the
                           instance
        - data         - dictionary with parameters specific to the class
        - active       - True if working, False if not
        - sources      - instances of devices which provide signal inputs
        - destinations - instances of devices which accept signals from this
                          device
      """
      def __init__(self, parent, name, inputs=None, output_names=None,
                   active=True):
        """
        Make the parent aware that this child exists
        """
        mylogger = logging.getLogger(
                                   module_logger.name+"Backend.DSProc.DataChl")
        self.name = name
        self.parent = parent
        mylogger.debug(" initializing %s", self)
        MC.Device.__init__(self, name, inputs=inputs, output_names=output_names,
                          active=active)
        self.logger = mylogger
        self.logger.debug(' inputs: %s', self.inputs)

class Processor(MC.Device):
  """
  Data processing device (computer) which provides additional processing

  This is only needed if the Backend must 'push' the processed data to a
  processing host.
  """
  def __init__(self, parent, name, inputs=None, output_names=None,
                     active=True, datahost=None):
    """
    Initialize a Backend.Processor subsystem.
    """
    mylogger = logging.getLogger(parent.logger.name+".DSProc")
    self.name = name
    self.parent = parent
    mylogger.debug(" initializing %s", self)
    MC.Device.__init__(self, name, inputs=inputs,
                          output_names=output_names, active=active)
    self.logger = mylogger
    self.logger.debug(' inputs: %s', self.inputs)
    if datahost:
      dest_IP = socket.gethostbyname(datahost)
      try:
        self.MACbase = self.parent.summary[name+' MAC'] # MAC base address
      except KeyError:
        # interface not defined
        module_logger.warning("__init__: %s device not known",name)
      else:
        self.IP = self.parent.summary[name+' IP']
        mac_base = decode_MAC(self.MACbase)
        ip_addr = decode_IP(self.IP)
        mac_addr = mac_base+ip_addr


############################# module methods ################################


def get_freq_array(bandwidth, n_chans):
  """
  Create an array of frequencies for the channels of a backend

  @param bandwidth : bandwidth
  @type  bandwidth : float

  @param n_chans : number of channels
  @type  n_chans : int

  @return: frequency of each channel in same units as bandwidth
  """
  return numpy.arange(n_chans)*float(bandwidth)/n_chans

def freq_to_chan(frequency,bandwidth,n_chans):
  """
  Returns the channel number where a given frequency is to be found.

  @param frequency : frequency of channel in sane units as bandwidth.
  @type  frequency : float

  @param bandwidth : upper limit of spectrometer passband
  @type  bandwidth : float

  @param n_chans : number of channels in the spectrometer
  @type  n_chans : int

  @return: channel number (int)
  """
  if frequency < 0:
    frequency = bandwidth + frequency
  if frequency > bandwidth:
    raise RuntimeError("that frequency is too high.")
  return round(float(frequency)/bandwidth*n_chans) % n_chans

def get_smoothed_bandshape(spectrum, degree = None, poly_order=15, plot=False):
  """
  Do a Gaussian smoothing of the spectrum and then fit a polynomial.
  Optionally, the raw and smoothed data and the fitted polynomial can be
  plotted.

  Notes
  =====
  numpy.polyfit(x, y, deg, rcond=None, full=False, w=None, cov=False)
  Least squares polynomial fit.
  Fit a polynomial::
  
     p(x) = p[0] * x**deg + ... + p[deg]
     
  of degree deg to points (x, y).
  Returns a vector of coefficients p that minimises the squared error.

  @param spectrum : input data
  @type  spectrum : list of float

  @param degree : number of samples to smoothed (Gaussian FWHM)
  @type  degree : int

  @param poly_order : order of the polynomial
  @type  poly_order : int

  @param plot : plotting option
  @type  plot : boolean

  @return: (polynomial_coefficient, smoothed_spectrum)
  """
  if degree == None:
    degree = len(spectrum)/100
  # normalize the spectrum so max is 1 and convert to dB.
  max_lev = numpy.max(spectrum)
  norm_spec = numpy.array(spectrum)/float(max_lev)
  norm_spec_db = 10*numpy.log10(norm_spec)
  # optionally plot normalized spectrum
  if plot:
    pylab.plot(norm_spec_db)
  # do a Gaussian smoothing
  norm_spec_db_smoothed = smoothListGaussian(norm_spec_db, degree=degree)
  # deal with the edges by making them equal to the smoothed end points
  norm_spec_db_smoothed_resized = numpy.ones(len(spectrum))
  # left end
  norm_spec_db_smoothed_resized[0:degree] = norm_spec_db_smoothed[0]
  # middle
  norm_spec_db_smoothed_resized[degree:degree+len(norm_spec_db_smoothed)] = \
      norm_spec_db_smoothed
  # right end
  norm_spec_db_smoothed_resized[degree+len(norm_spec_db_smoothed):] = \
      norm_spec_db_smoothed[-1]
  if plot:
    pylab.plot(norm_spec_db_smoothed_resized)
    poly = numpy.polyfit(range(len(norm_spec_db_smoothed)),
                         norm_spec_db_smoothed,poly_order)
    pylab.plot(numpy.polyval(poly, range(len(norm_spec_db_smoothed))))
    pylab.show()
  return poly, norm_spec_db_smoothed_resized
