"""
Superclass for receiver front ends
"""
import logging

import MonitorControl as MC

module_logger = logging.getLogger(__name__)

class FrontEnd(MC.Device):
  """
  Device which converts EM radiation to electrical signals.

  This is the superclass for all front end implementations

  Each RF band (L, S, X, Ku, K, Ka, Q) is handled by a separate front end.
  The bands are defined in signal_property["band"] in the MonitorControl
  module.

  For multi-feed front ends, a channel is assigned to each feed. Each front
  end or front end channel may put out one or two orthogonal polarizations,
  L and R or X and Y or H and V .The polarizations are defined in
  signal_property["pol_type"] in the MonitorControl module.

  The input channels handle Beam class signals, that is, a signal in which
  both polarizations are present. The output channels provide
  ComplexSignal class signals, that is, two fluctuating voltages whose
  frequency components are 90 deg apart (in quadrature phase).
  """
  def __init__(self, name, inputs=None, output_names=None, active=True):
    """
    Creates a FrontEnd object

    In general, a FrontEnd object will have one input and two outputs
    but for a multi-feed front end, if each feed produces two pols, and the
    implicit polarization encoding is used, each output pair for a given feed
    is a list.  For pols_out it is a list of lists dicts and for
    output_names it is a list of list of str.
    
    @param name : unique name to identify this instance
    @type  name : str

    @param inputs : upstream Port objects providing the signals
    @type  inputs : dict of Port instances

    @param band : optional waveguide band in which the front end operates.
    @type  band : str

    @param pols_out : optional polarization spec for the outputs (see docstr)
    @type  pols_out : dict of str
    
    @param output_names : optional names to be assigned to output ports
    @type  output_names : list of str

    @param active : True is the FrontEnd instance is functional
    @type  active : bool
    """
    mylogger = logging.getLogger(module_logger.name+".FrontEnd")
    # initialize the superclass
    MC.Device.__init__(self, name, inputs=inputs,
                          output_names=output_names, active=active)
    self.logger = mylogger
    self.name = name
    self.logger.debug(" initialized  for %s",self)

  class Channel(MC.Device):
    """
    Provides output from one feed
    """
    def __init__(self, parent, name, inputs=None, output_names=None,
                 active=True):
      """
      Initialize a FrontEnd.Channel
      """
      self.logger = logging.getLogger(parent.logger.name+".Channel")
      MC.Device.__init__(self, name, inputs=inputs,
                                      output_names=output_names, active=active)
      self.name=name
      self.logger = self.logger

  def set_ND(self):
    pass

  def set_cal_signal(self):
    pass
