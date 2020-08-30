"""
Monitor and Control of DSN radio astronomy equipment

In a very general sense, a configuration consists of Device sub-classes which
operate on signals, and Ports at the Device inputs and outputs which transfer
signals from one Device to another.  Configurations defined for various
situations are in the Configurations sub-module.

Devices may add to the properties of a signal.  This is a typical sequence.

There are many ways a Device may characterize the data.  Most common is power,
or something which is proportional to the average of the square of the voltage
samples.  Cross-product averages may contain polarization information or fringe
visibility. Because the output ports and signals must encode what kind of data
they contain, a number of standard codes are defined for Device, Port and
Signal objects which MUST be used in their names.

Classes::

  MonitorControlError(RuntimeError)
  Signal(object)                     -
  Beam(Signal)                       - signal with both polarizations present
  ComplexSignal(Signal)              - signal with both I and Q components
  IF(Signal)                         - signal with no phase information (I or Q)
  Spectrum(Signal)                   - digitized and usually transformed
  Device(object)                     - generic object with Ports (in and/or out)
  GainSection(Device)                - amplifiers, attenuators, filters, etc.
  Switch(Device)                     - 1xN, Nx1, 2x2 switches
  Port(object)                       - object which passes a Signal
  Observatory(object)                - class for describing infrastructure
  DeviceReadThread(threading.Thread) - gathers data

The module functions are::

  ClassInstance     - provides a specific subclass object for a template class
  valid_property    - forces signal properties to follow a naming convention
  show_port_sources - print diagnostic information about ports
  link_ports        - connect an upstream port with downstream port(s)
  oldest_ancestor   - finds the top parent of the candidate
  find_source       - upstream object belong to a specified class
"""
import copy
import datetime
import logging
import numpy
import os
import Pyro5.api
import re
import time
import threading

from math import pi

import Astronomy.DSN_coordinates as DSN
import support.lists

logger = logging.getLogger(__name__)

moment  = {1: 'mean', 2: 'pwr', 3: 'skew', 4: 'kurt', 5:'hskew', 6:'hkurt'}

signal_property = {
  "band": ["18", "20", "22", "24", "26", "Ka", "S", "X", "K"],
  "beam": ["B1", "B2", "F1", "F2"],
  "pol": ["P1", "P2", "PA", "PB"],
  "pol_type": ["H", "L", "R", "V", "E", "H"],
  "IF": ["IF1", "IF2"],
  "IF_type": ["I", "L", "Q", "U"],
  "product": ['XX', 'XY', 'YX', 'YY'],
  "stokes": ['I', 'Q', 'U', 'V'],
  "stats": list(moment.values())
  }

class MonitorControlError(RuntimeError):
  """
  Error handler for this module

  It was designed for a simple report where 'args' might be a variable
  value and 'message' some text about what is wrong with it, like:
  >>> raise MonitorControlError(self.name," is not a valid name.")

  There are more sophisticated possibilities, like:
  In [1]: from MonitorControl import MonitorControlError
  In [2]: words = ('Class:', 'method: ')
  In [3]: raise MonitorControlError(words,"%s = %s is not possible" % (1,2))
  ---------------------------------------------------------------------------
  ...
  MonitorControlError: 'Class:method: 1 = 2 is not possible'
  """
  def __init__(self, args, message):
    """
    Get error report arguments

    @param args : items to be concatenated
    @type  args : list or tuple

    @param message : error message text
    @type  message : str (could be complex; see above)
    """
    self.message = message
    self.args = args

  def __str__(self):
    """
    return the error report
    """
    return repr("".join(self.args) + self.message)


########################## signal classes #####################################

class Signal(object):
  """
  Class for type of signal passing through a Port object.

  A signal is derived from nothing (or the ether, if you like) or from another
  signal. The parent signal is more generic.  In the most general case it has
  two complex polarized components as received by a feed.

  Core signal property is 'beam'. After the two polarizations have been
  separated, the signals have a 'pol' property. After being down-converted
  (mixed) it has an 'IF' property.

  Signals carry some FITS data, namely 'BEAM', 'fechl-pol', 'IF' and 'ifname'.

  Public Attributes::
    name -
    data -
  """
  def __init__(self, name=None, parent_signal=None,
                     beam=None, pol=None, IF_type=None):
    """
    Create a Signal object

    If the parent signal has a name and name is given, then name is appended to
    the parent name.  If name is not given, the parent name is used.  This
    cannot cause an identification problem since the parent and child signals
    are separate objects. If there is no parent signal, a name is required.

    @param name : a name describing the main signal characteristic
    @type  name : str

    @param parent_signal : from which this signal is derived
    @type  parent_signal : Signal instance

    @param beam : feed or beam ID
    @type  beam : str

    @param pol : polarization type: X, Y, H, V, R or L
    @type  pol : str

    @param IF_type : type of IF signal: I, Q, U or L
    @type  IF_type : str

    """
    self.logger = logging.getLogger(logger.name+".Signal")
    self.logger.debug(
       "__init__: entered with parent beam %s", parent_signal)
    self.data = {}
    # copy the parent signal properties
    if parent_signal:
      if name:
        self.name = parent_signal.name+name
      else:
        self.name = parent_signal.name
      #for key in self.data.keys():
      #  self.data[key] = self.parent_signal.data[key]
    else:
      self.name = name
    # Check for a valid name
    if self.name:
      pass
    else:
      raise MonitorControlError(self.name," is not a valid name.")
    # copy the parent properties
    if parent_signal:
      self.copy(parent_signal)
    # set or update properties
    if beam:
      if parent_signal:
        if 'beam' in parent_signal.data:
          raise MonitorControlError("Signal", "property 'beam' cannot be changed")
      else:
        self.data['beam'] = beam
    if pol:
      self.data['pol'] = pol
    if IF_type:
      self.data['IF'] = IF_type
    mykeys = list(self.data.keys())
    self.logger.debug("__init__: created %s with keys %s", self, mykeys)
    for key in mykeys:
      self.logger.debug(" %s = %s", key, self.data[key])

  def __setitem__(self,key,value):
    self.data[key] = value

  def __getitem__(self, key):
    return self.data[key]

  def keys(self):
    return list(self.data.keys())

  def has_key(self,key):
    if key in self.data:
      return True
    else:
      return False

  def copy(self, signal):
    """
    Copy the properties of the specified signal
    """
    for prop in list(signal.data.keys()):
      self.data[prop] = signal.data[prop]


class Beam(Signal):
  """
  Signal class for radiation arriving at a feed.

  There is no more fundamental signal type. A Beam signal has two polarizations
  in it.

  A polarizer extracts one of the polarizations.  An orthomode extracts both.
  The resulting signal(s) are complex, having implicit phase information.
  """
  def __init__(self, name):
    """
    """
    self.logger = logging.getLogger(logger.name+".Beam")
    self.logger.debug("__init__: creating Beam %s", name)
    if type(name) != str:
      raise MonitorControlError(name, " is not an string")
    Signal.__init__(self, name=name, beam=name)

  def __repr__(self):
    return "Beam "+self.name

class ComplexSignal(Signal):
  """
  ComplexSignal class for an RF output from an orthomode or polarizer.

  This is a complex signal with both in-phase and quadrature-phase components.
  A simple mixer extracts only the in-phase component.  A complex mixer
  extracts both.
  """
  def __init__(self, parent_signal, pol=None, name=None):
    """
    Create a ComplexSignal instance

    @param pol : polarization of the signal: X, Y, R or L or X or Y
    @type  pol : str
    """
    mylogger = logging.getLogger(logger.name+".ComplexSignal")
    mylogger.debug("__init__: creating ComplexSignal %s", name)
    mylogger.debug("__init__: entered with parent %s and pol=%s", parent_signal, pol)
    if type(parent_signal) == Beam:
      Signal.__init__(self, name=name, parent_signal=parent_signal, pol=pol)
    elif type(parent_signal) == ComplexSignal:
      Signal.__init__(self, name=name, parent_signal=parent_signal)
    else:
      Signal.__init__(self, name=name, parent_signal=parent_signal, pol=pol)
      self.logger.warning("__init__: %s has no parent signal", self)
    self.logger = mylogger

  def __repr__(self):
    return "ComplexSignal "+self.name

class IF(Signal):
  """
  Electrical signal out of a receiver, suitable for detection or digitization.

  This is the simplest form of signal.  It can be represented by a single
  sequence of real numbers (floats or ints).
  """
  def __init__(self, parent, IF_type=None):
    """
    @param parent : ComplexSignal instance from which this is derived
    @type  parent : ComplexSignal class instance

    @param IF_type : "I", "Q", "U", "L"
    @type  IF_type : str
    """
    mylogger = logging.getLogger(logger.name+".IF")
    mylogger.debug("__init__: creating IF from %s", parent)
    mylogger.debug("__init__: entered with parent %s and IFtype=%s", parent, IF_type)
    self.parent = parent
    if type(parent) == ComplexSignal:
      Signal.__init__(self, parent_signal=parent, IF_type=IF_type,
                            name=IF_type)
    elif type(parent) == IF:
      Signal.__init__(self, parent_signal=parent, name=IF_type)
    else:
      Signal.__init__(self, parent_signal=parent, IF_type=IF_type,
                            name=IF_type)
      self.logger.warning("__init__: %s has no parent signal", self)
    self.logger = mylogger
    self.logger.debug("__init__: IF %s created", self)

  def __repr__(self):
    return "IF "+self.name

class Spectrum(Signal):
  """
  """
  def __init__(self, parent, name=None, num_chans=0):
    mylogger = logging.getLogger(logger.name+".Spectrum")
    mylogger.debug("__init__: creating Spectrum %s", name)
    mylogger.debug("__init__: entered with parent %s and %s channels", parent,
                                                              num_chans)
    self.name = name
    if type(parent) != IF:
      raise MonitorControlError(str(type(parent)),
                             "Cannot be converted directly to type Spectrum")
    if num_chans <= 0:
      raise MonitorControlError(str(num_chans),
                             " is an invalid number of spectrum channels")
    Signal.__init__(self, name=name, parent_signal=parent)
    self.logger = mylogger
    self.data['num_chans'] = num_chans

  def __repr__(self):
    return "Spectrum "+self.name

###################### generic observing device classes #######################

class Device(object):
  """
  Superclass for anything that receives, processes and outputs a signal.

  Signals are handled by Port instances. Inputs and outputs are channels.
  There may be internal channels connecting inputs and outputs.

  Public Attributes::
    name    - pols = unique(pols) identifier str
    active  - bool is True if device is available
    data    - dict for any kind of data for the device
    inputs  - dict of input Port instances
    outputs - dict of output Port instances

  *Port Naming Convention*
  
  The input and output names must be sortable so that outputs correspond to the
  appropriate input.  For example, if the inputs are X1 and X2 and the outputs
  are A, B, C, D, then A, B must be associated with X1 and C, D to X2.  Further
  A is similar to C and B is similar to D.  (This is because the order in which
  dict key,value pairs are specified is not preserved.)

  The dict 'inputs' should have all the input port names, even ones not used.
  Just assign those the value None.

  'output_names' should be a list of lists, where the inner lists are the
  output names of each of the channels.

  *FITS Header Data*
  
  Wherever possible, a FITS keyword will adhere to the standard usage.  Local
  keywords, not used in the wider community, are in lowercase.
  """
  def __init__(self, name, inputs=None, output_names=None, active=True, hardware=False):
    """
    @param name : name for this observing device
    @type  name : str

    @param inputs : where the signals come from
    @type  inputs : dict of Port instances

    @param output_names : names to be assigned to output ports
    @type  output_names : list of str

    @param active : True if it is working
    @type  active : bool
    """
    self.logger = logging.getLogger(logger.name+".Device")
    self.name = name
    self.logger.debug("__init__: for %s", self)
    if inputs == None:
      self.logger.debug("__init__: no inputs specified")
      self.inputs = {}
    else:
      show_port_sources(inputs,
                        "Device.__init__: input sources for "+str(self),
                        self.logger.level)
      inkeys = list(inputs.keys())
      inkeys.sort()
      self.logger.debug("__init__: Making input ports")
      self.inputs = {}
      for key in inkeys:
        self.logger.debug("Device.__init__: input %s is from %s", key,
                          inputs[key])
        if inputs[key]:
          self.inputs[key] = Port(self, key, source=inputs[key],
                                  signal=copy.copy(inputs[key].signal))
        else:
          self.inputs[key] = Port(self, key)
      show_port_sources(self.inputs,
                        "Device.__init__: input ports for "+str(self),
                        self.logger.level)
    self.outputs = {}
    self.logger.debug("__init__: output names for %s: %s", self, output_names)
    if output_names:
      outnames = support.lists.flatten(output_names)
      for name in outnames:
        self.outputs[name] = Port(self, name)
    show_port_sources(self.outputs,
                      "Device.__init__: output ports for "+str(self),
                      self.logger.level)
    #self.logger.debug("__init__: %s output ports: %s", self, self.outputs.keys())
    self.active = active
    self.data = {}
    self.logger.debug("__init__: done for %s", self)

  def __str__(self):
    return self.base()+' "'+self.name+'"'

  def __repr__(self):
    return self.base()+' "'+self.name+'"'

  def base(self):
    """
    String representing the class instance type
    """
    return str(type(self)).split()[-1].strip('>').strip("'").split('.')[-1]

  def __setitem__(self, key, item):
    self.data[key] = item

  def __getitem__(self, key):
    return self.data[key]

  def keys(self):
    return list(self.data.keys())

  def has_key(self,key):
    if key in self.data:
      return True
    else:
      return False

  def update_signals(self):
    """
    Updates the signals passing out of a device.

    If a device updates it signals, the down-stream devices must update their
    signals also.  Since the destinations are Port objects, the updating must
    be done by the parent of the Port.

    Note that this promulgates updates via the top-level Device outputs.
    It does not update the child Device objects.
    """
    self.logger.debug("update_signals: %s is updating signals", self)
    self._update_signals()
    # update the signals of downstream devices
    for key in self.outputs:
      self.logger.debug("update_signals for %s", self.outputs[key])
      for destination in self.outputs[key].destinations:
        destination.parent.update_signals()

  def _connect_ports(self):
    """
    Propagate signals from inputs to outputs.

    The connections may change when the device changes state.  This is done by
    (re-)defining the port source and destination attributes.The subclass must
    provide an appropriate method to handle that.

    To do this one needs to know what a specific receiver does.  If the
    receiver has sub-components (RFsections, PolSections, DownConvs} then they
    must first have their ports (re)-connected.
    """
    self.logger.debug("_connect_ports: for %s", self.name)
    pass

  def _update_signals(self):
    """
    Copy the port signals from their source ports

    This requires that _connect_ports sets up the port 'source' attribute for
    each port.

    This is not needed here if the input and output ports are on sub-components
    that have their signals updated since the parent ports are then the same as
    the sub-component ports
    """
    self.logger.debug("_update_signals: updating %s",
                        self.name)
    # connect or reconnect the ports
    self._connect_ports()
    # update the signals
    for key in list(self.inputs.keys()):
      self.logger.debug("_update_signals: processing input port %s", key)
      if self.inputs[key].source.signal != None:
        self.inputs[key].signal.copy(self.inputs[key].source.signal)
    for key in list(self.outputs.keys()):
      self.logger.debug("_update_signals: processing output port %s", key)
      if self.outputs[key].source != None:
        self.outputs[key].signal.copy(self.outputs[key].source.signal)


class Port(object):
  """
  Class for a signal port in an Device.

  Public attributes::
    name         - unique identifier for the port
    source       - a Port instances providing the signal(s)
    destinations - list of Port instances receiving the signal(s)
    signal       - type of signal handled by this channel instance

  Notes
  =====
  When instantiation a Port, the Port should be provided with a 'source'
  attribute, though it is possible, but less obvious, to specify 'source' as
  None and give it a value later.  The Port instantation code should then add
  itself to the upstream Port attribute 'destinations'.
  """
  def __init__(self, parent, name, source=None, signal=None):
    """
    Generic channel of an Device.

    Note
    ====
    It is possible to create a Port without specifying the source and set the
    source attribute later.  However, then setting the upstream destinations
    attribute is also the programmer's responsibility.

    Note that the contents of attribute destinations cannot be specified at
    initialization because the downstream channels are not yet known.

    @param parent : the object to which the port belongs
    @type  parent : Device instance

    @param name : unique identifier
    @type  name : str

    @param source : channel providing the input
    @type  source : Port instance

    @param signal : a signal class instance
    @type  signal : instance of Beam, ComplexSignal or IF
    """
    self.logger = logging.getLogger(parent.logger.name+".Port")
    self.name = name
    self.parent = parent
    self.logger.debug("__init__: for %s", self)
    self.source = source
    self.destinations = []
    self.signal = signal
    self.logger.debug("__init__: specified signal input is %s", self.signal)
    if source:
      self.logger.debug("__init__: signal source is %s with signal %s",
                        source, source.signal)
      if (type(source) == Port or
         issubclass(type(source).__bases__[0], Port) ):
        source.destinations.append(self)
        self.logger.debug("__init__: %s destinations are now %s", source,
                          str(source.destinations))
      else:
        # I don't think this ever happens.
        self.logger.error("__init__: %s outputs are %s which are not Port subclass",
                          source, str(source.outputs))
        raise MonitorControlError(source,"is not a Port")
      #  source.outputs[name].destinations.append(self)
      #  self.logger.debug(" %s outputs[%s] destinations are %s",
      #                    source, name, source.outputs[name].destinations)
    else:
      self.logger.debug("__init__: %s has no input", self)
    self.logger.debug("__init__: %s done", self)

  def __str__(self):
    # 'name' could be an integer key
    return self.parent.base()+"."+self.base()+' "'+str(self.name)+'"'

  def __repr__(self):
    return self.parent.base()+"."+self.base()+' "'+str(self.name)+'"'

  def base(self):
    """
    String representing the class instance type
    """
    return str(type(self)).split()[-1].strip('>').strip("'").split('.')[-1]

class Observatory(object):
  """
  Defines the Observatory class.

  This super-class contains the elements of an observatory, which is
  an entity with one or more antennas, signal processing equipment, etc.

  Attributes
  ==========
   - LO         - optional central frequency reference
   - name       - a string (e.g. "Goldstone")
   - switches   - A list of switches at the observatory
   - telescopes - a list of Telescope objects
  """

  def __init__(self, name, LO=None):
    """
    Initialize Observatory

    Create empty lists for self.telescopes and self.backends which
    both belong to the observatory.

    @param name : the observatory's name.
    @type  name : str

    @param LO : a central frequency reference, if needed
    @type  LO : Synthesizer() instance

    @return: None
    """
    self.name = name

  def __str__(self):
    return self.base()+' "'+self.name+'"'

  def __repr__(self):
    return self.base()+' "'+self.name+'"'

  def base(self):
    """
    String representing the class instance type
    """
    return str(type(self)).split()[-1].strip('>').strip("'").split('.')[-1]

class GainSection(Device):
  """
  Any device which increases or decreases the power level without
  changing the frequency and possible splits the signal.

  Amplification and attenuation are often integral to devices like
  Receiver() or Backend() instances.
  """
  def __init__(self, name, inputs=None, output_names=None,
                     gain=0, active=True):
    Device.__init__(self, name,
                              inputs=inputs, output_names=outputs,
                              active=active)
    self.gain = gain

  def set_gain(self,gain):
    pass

  def get_gain(self):
    pass

class Switch(Device):
  """
  Three basic switch types are recognized: "1xN", "Nx1" and "2x2".
  The latter is a transfer switch, which is just a convenient way
  of handling two parallel 2x1 switches.

  Public attributes::
    inkeys   - sorted list of input names (for Nx1 and 2x2)
    outkeys  - sorted list of output names (for 1xN and 2x2)
    outname  - output port name for Nx1 switch
    parent   -
    states   - a list of str possible switch configurations
    state    - actual configuration
    stype    - 1xN, Nx1 or 2x2

  Public attributes inherited from Device::
    inputs
    logger
    outputs

  """
  def __init__(self, name, inputs={}, output_names=[], stype=None,
               state=0, active=True):
    """
    Initialize a Switch

    For a "1xN" switch there must be only on input.  The outputs are all the
    downstream device ports connected to the switch.
    For an "Nx1" switch, the inputs are the output ports of upstream
    devices and the output port is the input of the downstream device.
    A "2x2" (transfer) switch must have two inputs and two outputs.

    Switches have a state.  For a 1xN or Nx1 switch this integer points to the
    port of a port group which is selected. The keys can be 1,...,N which is
    usually easier for associating a port with an actual hardware port. For a
    2x2 switch, 0 (False) means the signals go straight through and 1 (True)
    means the signals are crossed.

    In order for the software to know what is the uncrossed state of the switch
    it is necessary that the port labels of the inputs and of the outputs are
    ordered. For example, if the ports are A, B, C and D, and A and B are
    inputs, then the uncrossed state is A <-> C and B <-> D.  Or if the ports
    are labelled as input-output pairs, such as in inputs 1, 3 and outputs
    2, 4, then the uncrossed state is 1 <-> 2, 3 <-> 4.

    Inputs and output_names may be specified after initialization but it makes
    the configuration description harder to follow.

    @param name : unique identifier
    @type  name : str

    @param inputs : output channels of upstream devices
    @type  inputs : Port instances

    @param output_names : names of input channels
    @type  output_names : list of str

    @param stype : switch type 1xN, Nx1 or 2x2
    @type  stype : str

    @param state: initial or default state
    @type  state: int

    @param active : True is device is working
    @type  active : bool
    """
    mylogger = logging.getLogger(logger.name +
                                                ".{}".format(self.__class__.__name__))

    mylogger.debug("__init__: for %s switch %s ", stype, name)
    self.name = name
    if output_names == []:
      raise MonitorControlError("","Switch must have some outputs")
    #show_port_sources(inputs, "Switch.__init__: Inputs to Switch:", mylogger.level)
    mylogger.debug("__init__: %s inputs: %s", str(self), str(inputs))
    mylogger.debug("__init__: output names: %s", output_names)
    Device.__init__(self, name, inputs=inputs,
                                output_names=output_names, active=active)
    self.logger = mylogger
    self.stype = stype
    self.inputs = inputs
    if self.stype:
      self.logger.debug("__init__: defining sources and destinations")
      self.inkeys = list(self.inputs.keys())
      self.inkeys.sort()
      self.outkeys = output_names
      self.outkeys.sort()
      # Initialize the switch to the default state
      if self.stype.upper() == "1XN":
        if len(self.inputs) == 1:
          self.states = list(range(len(self.outputs)))
          self.outname = list(self.outputs.keys())[state]
          self.inname = list(self.inputs.keys())[0]
          for key in list(self.outputs.keys()):
            self.outputs[key].source = None
          self.inputs[self.inname].destinations = []
        else:
          raise MonitorControlError(stype, "switch must have one input")
      elif self.stype.upper() == "NX1":
        if len(self.outputs) == 1:
          self.states = list(range(len(self.inputs)))
          self.outname = list(self.outputs.keys())[0]
          for key in list(self.inputs.keys()):
            if self.inputs[key]:
              self.inputs[key].destinations = []
          self.outputs[self.outname].source = None
        else:
          raise MonitorControlError(stype, "switch must have one output")
      elif stype.upper() == "2X2":
        if len(self.inputs) == 2 and len(output_names) == 2:
          # In the default state, the inputs and outputs are not crossed
          self.states = [state,1-state]
          for index in [0,1]:
            inname = self.inkeys[index]
            outname = self.outkeys[index]
            self.outputs[outname].source = self.inputs[inname]
            self.inputs[inname].destinations = [self.outputs[outname]]
        else:
          raise MonitorControlError(stype,
                                 "switch requires two inputs and two outputs")
        for key in list(self.outputs.keys()):
          self.parent.outputs[key] = self.outputs[key]
      else:
        raise MonitorControlError(stype,"is not a valid switch type")
      # default value, but it does not set the state
      self.state = self.states[state]
    else:
      raise MonitorControlError(None,"a switch type must be specified")

  def __str__(self):
    return self.base()+' "'+self.name+'"'

  def __repr__(self):
    return self.base()+' "'+self.name+'"'

  def base(self):
    """
    String representing the class instance type
    """
    return str(type(self)).split()[-1].strip('>').strip("'").split('.')[-1]

  def set_state(self, state):
    """
    This sets the signal path resulting from the switch state.

    Actual control of the switch must be done with methods _set_state() and
    _get_state() which must be provided by a sub-class.
    """
    self.logger.debug("Switch.set_state: setting %s state to %s", self, state)
    if self.stype.upper() == "1XN":
      name = self.inkeys[0]
      outkey = self.outkeys[state]
      self.inputs[name].destinations = [self.outputs[outkey]]
      self.outputs[outkey].source = self.inputs[name]
    elif self.stype.upper() == "NX1":
      name = list(self.outputs.keys())[0]
      inkey = list(self.inputs.keys())[state]
      self.outputs[name].source = self.inputs[inkey]
      self.inputs[inkey].destinations = [self.outputs[name]]
    elif self.stype.upper() == "2X2":
      self._route_signals(state)
    else:
      raise MonitorControlError(stype,"is not a valid switch type")
    # This switches the signals
    self.state = self._set_state(state)
    self._update_signal()
    return self.state

  def _route_signals(self, state):
    """
    Route the inputs to the correct outputs

    If the switch is not set, signals go straight through.  If the switch is
    set, the signals cross over.
    """
    if state:
      self.logger.debug("Switch._route_signals: %s signals crossed over",
                        self)
      self.outputs[self.outkeys[0]].source = self.inputs[self.inkeys[1]]
      self.outputs[self.outkeys[1]].source = self.inputs[self.inkeys[0]]
      self.inputs[self.inkeys[1]].destinations = \
                                                [self.outputs[self.outkeys[0]]]
      self.inputs[self.inkeys[0]].destinations = \
                                                [self.outputs[self.outkeys[1]]]
    else:
      self.logger.debug("Switch._route_signals: %s signals pass through",
                        self)
      self.outputs[self.outkeys[0]].source = self.inputs[self.inkeys[0]]
      self.outputs[self.outkeys[1]].source = self.inputs[self.inkeys[1]]
      self.inputs[self.inkeys[0]].destinations = \
                                                [self.outputs[self.outkeys[0]]]
      self.inputs[self.inkeys[1]].destinations = \
                                                [self.outputs[self.outkeys[1]]]

  def get_state(self):
    """
    Sets the attribute 'state'
    """
    self.logger.debug("get_state: Switch superclass entered for %s", self)
    # First reset all the input destinations to nothing
    for key in self.inkeys:
      if self.inputs[key]:
        self.inputs[key].destinations = []
    for key in self.outkeys:
      self.outputs[key].source = None

    if self._get_state() < 0:
      return self.state
    else:
      if self.stype == "1xN":
        self.inputs[self.inname].destinations = \
                                       [self.outputs[self.outkeys[self.state]]]
        self.outputs[self.outkeys[self.state]].source = \
                                                       self.inputs[self.inname]
      elif self.stype == "Nx1":
        if self.inputs[self.inkeys[self.state]]:
          self.inputs[self.inkeys[self.state]].destinations = \
                                                   [self.outputs[self.outname]]
        self.outputs[self.outname].source = \
                                           self.inputs[self.inkeys[self.state]]
      elif self.stype == "2x2":
        self._route_signals(self.state)
      else:
        raise MonitorControlError(stype,"is not a valid switch type")
    self._update_signal()
    self.logger.debug("get_state: state is %s", self.state)
    return self.state

  def _set_state(self,inport):
    """
    Stub for real device method
    """
    self.logger.error(
                    "_set_state: Switch method should be replaced by subclass")
    self.state = inport
    return self.state

  def _get_state(self):
    """
    Stub
    """
    self.logger.error(
                    "_get_state: Switch method should be replaced by subclass")
    return self.state

  def _update_signal(self):
    """
    """
    self.logger.debug("_update_signal: entered for %s", self)
    for key in self.outkeys:
      self.logger.debug("_update_signal: processing key %s", key)
      self.logger.debug("_update_signal: output is %s", self.outputs[key])
      self.logger.debug("_update_signal: with signal from %s",
                                                      self.outputs[key].source)
      if self.outputs[key].source:
        self.outputs[key].signal = copy.copy(self.outputs[key].source.signal)
    if self.stype == "Nx1" or self.stype == "1xN":
      self.logger.debug(' %s._update_signal: output %s source=%s', self,
                        self.outputs[self.outname],
                        self.outputs[self.outname].source)
    else:
      show_port_sources(self.inputs,
                        "Switch._update_signal: Inputs to 2x2 switch",
                        self.logger.level)
      show_port_sources(self.outputs,
                        "Switch._update_signal: Outputs from 2x2 switch",
                        self.logger.level)
    self.logger.debug("_update_signal: done")

############################# Classes for I/O Threads #########################


class DeviceReadThread(threading.Thread):
  """
  One thread in a multi-threaded, multiple device instrument

  This creates a thread which can be started, terminated, suspended, put to
  sleep and resumed. For more discussion see
  http://mail.python.org/pipermail/python-list/2003-December/239268.html
  """

  def __init__(self, actor, action, name=None, suspend=False):
    """
    Create a DeviceReadThread object

    @param actor : the object invoking the thread
    @type  actor : some class instance for which an action is defined

    @param action : to be performed in the run loop
    @type  action : function
    """
    mylogger = logging.getLogger(logger.name+".DeviceReadThread")
    threading.Thread.__init__(self, target=action)
    self.logger = mylogger
    self.actor = actor
    self.action = action
    # if actor is 'self' then name will be generic 'Thread-xxx'
    self.logger.debug("__init__: parent (actor) is %s", self.actor.name)
    self.end_flag=False
    self.thread_suspend=suspend
    self.sleep_time=0.0
    self.thread_sleep=False
    self.sync_sec = False
    self.lock = threading.Lock()
    if name:
      self.name = name
    else:
      try:
        self.name = self.actor.name
      except AttributeError:
        self.name = "actor"
    self.logger.debug(" initialized thread %s", self.name)

  def run(self):
    """
    """
    self.logger.debug("run: thread %s started", self.name)
    while not self.end_flag:
      # Optional sleep
      if self.thread_sleep:
        time.sleep(self._sleeptime)
      # Optional suspend
      while self.thread_suspend:
        time.sleep(0.001) # should maybe be have argument to set this property?
      if self.sync_sec:
        self.sync_second()
        self.sync_sec = False
      self.action()
    self.logger.info(" thread %s done", self.name)

  def terminate(self):
    """
    Thread termination routine
    """
    self.logger.info(" thread %s ends", self.name)
    self.end_flag = True

  def set_sleep(self, sleeptime):
    """
    """
    self.thread_sleep = True
    self._sleeptime = sleeptime

  def suspend_thread(self):
    """
    """
    self.thread_suspend=True

  def resume_thread(self, sync_sec=False):
    """
    """
    self.sync_sec = sync_sec
    self.thread_suspend=False

  def sync_second(self):
    """
    """
    now = int(time.time())
    while not bool(int(time.time())-now):
      time.sleep(0.0001)

# a more appropriate name for the thread
ActionThread = DeviceReadThread



############################# module methods ##################################

def ClassInstance(templateClass, subclass, *args, **kwargs):
    """
    This creates an instance of the specified sub-class

    It passes the arguments, if any, to the sub-class initializer.  An
    example of using this function::
    
      >>>  IFsw = ClassInstance(Switch, JFW50MS287, lab, "Nx1", 0)
    
    (The last argument is required for the JFW50MS287 to specify which output
    port it is associated with.)

    Notes
    =====
    
    **Acknowledgment**
    
    This approach was recommended by Barzia Tehrani on 2012 Oct 14, 11:36 am:
    'I have seen Instantiate helper methods just to bridge the gap between
    different languages.'
    
    Arguments
    ---------
    The subclass must provide the template with all the arguments that it
    requires.

    @param templateClass : the superclass for this device
    @type  templateClass : class

    @param subclass : the implementation of this specific device
    @type  subclass : class

    @param args : sequential arguments required to initialize the subclass

    @param kwargs : keyword arguments required to intitialize the subclass
    """
    logger.debug(
                "ClassInstance: making %s instance with subclass %s",
                 str(templateClass), str(subclass))
    subclasses = templateClass.__subclasses__()
    if subclasses:
      for sub in subclasses:
        if sub == subclass:
          # return an instance of the subclass
          return sub(*args,**kwargs)
      # Hopefully this statement is never reached
      raise MonitorControlError(str(subclass),
                             "is not a subclass of the template class")
    else:
      raise MonitorControlError(str(templateClass),"has no subclasses")

def valid_property(keylist, ptype, abort=True):
  """
  All entries must have a substr matching an entry in the signal property list.

  The property code must appear first in the key, followed by a dash (minus).

  @param keylist : list of keys to be tested
  @type  keylist : list of str

  @param ptype : key for signal_property dict
  @type  ptype : str

  @param abort : raise Exception on failure
  @type  abort : bool

  @return: a dict with properties for each key or an empty dict
  """
  allowed = signal_property[ptype]
  flatlist = support.lists.flatten(keylist)
  match = {}
  for key in flatlist:
    test = key.split('-')[0]
    for pattern in allowed:
      if re.search(pattern, test):
        match[key] = pattern
        break
  if abort == True and match == {}:
    raise MonitorControlError(str(keylist), (" has no valid %s code" % ptype))
  else:
    return match

def show_port_sources(ports, header, loglevel):
  """
  Helper method to print diagnostic information about ports.
  """
  if loglevel < logging.INFO:
    text = "show_port_sources: "+header+"\n"
    if ports is None:
        return
    inkeys = list(ports.keys())
    inkeys.sort()
    for key in inkeys:
      if hasattr(ports[key], "source"):
        if hasattr(ports[key].source, "signal"):
          text += ("      %s gets a signal %s from %s\n" %
                                (ports[key], ports[key].source.signal,
                                 ports[key].source))

        else:
          text += ("      %s  gets no signal from %s\n" %
                                (ports[key], ports[key].source))
      else:
        text += ("      %s has no source\n" %
                    (ports[key]))
    logger.debug(text[:-1]) # removes the last \n
  else:
    pass

def link_ports(inputs, outputs):
  """
  Connect an upstream port with downstream port(s).

  This connects an upstream port with downstream port(s), both of which are
  dicts. The source of the downstream port(s), given by 'outputs', is the
  upstream port. In the general case there is one input port and one or more
  output ports.  So 'outputs', at least, must be a dict. If there is more than
  one upstream ports for a downstream port (think of a quadrature hybrid as an
  example) then the 'source' attribute is a list. The Device initialization
  must then change 'source' from a port to a list of ports.

  Example: connect a device input to its outputs. (See FrontEnd)

  Example: connect a device output to the downstream device inputs. (See
  KurtSpec)

  @param inputs : upstream port(s)
  @type  inputs : dict

  @param outputs : downstream port(s)
  @type  outputs : dict
  """
  inkeys = list(inputs.keys())
  inkeys.sort()
  outkeys = list(outputs.keys())
  outkeys.sort()
  logger.debug('link_ports: input keys are %s', inkeys)
  logger.debug('link_ports: output keys are %s', outkeys)
  for outkey in outkeys:
    logger.debug('link_ports: processing output %s', outkey)
    logger.debug('link_ports: %s source is %s',
                        outputs[outkey], outputs[outkey].source)
    if len(inkeys) > 1:
      for inkey in inkeys:
        outputs[outkey].source.append(inputs[inkey])
        inputs[inkey].destinations.append(outputs[outkey])
    else:
      outputs[outkey].source = inputs[inkeys[0]]
      inputs[inkeys[0]].destinations.append(outputs[outkey])
    outputs[outkey].signal = outputs[outkey].source.signal
    logger.debug('link_ports: %s source= %s', outputs[outkey],
                         outputs[outkey].source)

def oldest_ancestor(candidate):
  """
  finds the top parent of the candidate
  """
  try:
    parent = candidate.parent
  except AttributeError:
    return candidate
  else:
    return oldest_ancestor(parent)

def find_source(device, source_class):
  """

  """
  logger.debug("Trying %s", device)
  ancestor = oldest_ancestor(device)
  if issubclass(ancestor.__class__, source_class):
    return ancestor
  elif issubclass(device.__class__, Port):
    return find_source(device.source, source_class)
