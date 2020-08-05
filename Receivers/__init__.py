"""
Module for controlling and monitoring DSN science receivers

This has the highest Receiver superclass which described the functionality of
a generic receiver.
"""
import MonitorControl as MC

import logging

module_logger = logging.getLogger(__name__)

class Receiver(MC.Device):
  """
  Device which converts RF signals to IF signals for detection or digitization

  The input channels accept ComplexSignal class signals. The outputs provide
  IF class signals.
  """
  def __init__(self, name, inputs = None, output_names = None, active=True):
    """
    Initialize a Receiver instance.
    
    Inputs may be left unspecified and defined later but a Receiver instance
    must have some signal inputs. Likewise for outputs.

    
    @param name : unique identifier
    @type  name : str

    @param inputs : signal channels
    @type  inputs : Port instances

    @param output_names : names of the output channels/ports
    @type  output_names : list of str

    @param active : True is the FrontEnd instance is functional
    @type  active : bool
    """
    mylogger = logging.getLogger(module_logger.name+".Receiver")
    self.name = name
    mylogger.debug("__init__: for %s", self)
    MC.Device.__init__(self, name, inputs=inputs,
                              output_names=output_names, active=active)
    self.logger = mylogger
    self.logger.debug("__init__: %s done", name)

  class RFsection(MC.Device):
    """
    A Receiver.RFsection may split the incoming band into sub-bands,
    measure the incoming power, etc. But the simplest case is just to pass the
    signal on to the mixer(s).
    """
    def __init__(self, parent, name, inputs=None, output_names=None,
                 active=True):
      """
      Initialize a Receiver.RFsection

      This just invokes the Device superclass initialization.  The other
      arguments are the same as for Receiver.

      @param parent : the Receiver to which this belongs
      @type  parent : Receiver instance
      """
      mylogger = logging.getLogger(parent.logger.name+".RFsection")
      self.name = name
      mylogger.debug("__init__: for %s", self)
      MC.show_port_sources(inputs, 
                        "Receiver.RFsection.__init__: inputs before init:",
                        mylogger.level)
      MC.Device.__init__(self, name, inputs=inputs,
                      output_names=output_names, active=active)
      # generic Receiver class RF section does not connect outputs to inputs
      MC.show_port_sources(self.inputs,
                        "Receiver.RFsection.__init__: inputs after init:",
                        mylogger.level)
      MC.show_port_sources(self.outputs,
                        "Receiver.RFsection.__init__: outputs after init:",
                        mylogger.level)
      self.logger = mylogger
      self._update_signals()
      mylogger.debug("__init__: %s initialized", name)

  class PolSection(MC.Device):
    """
    Polarization conversion hybrid.
    
    This is an optional section that converts one orthogonal polarization pair,
    e.g. H,V, to the other mode, like H,V to R,L.  It is assumed that this is
    an optional operation which is performed only if attribute 'convert' is
    True.  To know what is being converted to what requires knowledge of the
    specific receiver.
    """
    def __init__(self, parent, name, inputs=None, output_names=None,
                 active=True):

      """
      Initialize a Receiver.PolSection

      The arguments are the same as for RFsection.  In this case, the inputs
      are signal pairs, one from each down-converter chain, each a Receiver
      instance.
      """
      mylogger = logging.getLogger(parent.logger.name+".PolSection")
      MC.Device.__init__(self, name, inputs=inputs,
                      output_names=output_names, active=active)
      self.logger = mylogger
      self.convert = False
      self.logger.debug(" %s initialized", name)
      
    def set_state(self, convert=False):
      """
      Set the state of a polarization hybrid to convert pol mode or not
      
      This is for a E/H -> L/R conversion.  If the hybrid inputs are L/R then
      the logic sign must be changed in a sub-class version
      """
      self.logger.warning(" set pol mode invoked from Receiver.PolSection")
      self._set_state(convert)
      if self.state:
        self.pols = ["L", "R"]
      else:
        self.pols = ["E", "H"]
      #self.update_signals()

    def get_state(self):
      """
      This gets replaced by the sub-class
      """
      self.logger.debug("get_state: invoked")
      self.state = self._get_state()
      return self.state

    def _set_state(self, state):
      """
      This gets replaced by the sub-class
      """
      self.state = state
      
    def _get_state(self):
      """
      This gets replaced by the sub-class
      """
      self.logger.debug("_get_state: invoked")
      return self.state
      
  class DownConv(MC.Device):
    """
    Comprises the local oscillator and mixer and IF electronics.

    This is the only mandatory component of a Receiver
    """
    def __init__(self, parent, name, inputs=None, output_names=None,
                 active=True):
      """
      Initialize a Receiver.DownConv

      You might think that a method to set the LO would be mandatory but in
      fact we have one receiver with fixed LOs.

      The arguments are the same as for PolSection.
      """
      MC.Device.__init__(self, name, inputs=inputs,
                              output_names=output_names, active=active)
      self.logger = logging.getLogger(module_logger.name+".DownConv")

    def set_state(self, state=False):
      """
      """
      self._set_state(state)
      return self._get_state()

    def get_state(self):
      """
      """
      self.state = self._get_state()
      return self.state
      
      
    class Channel(MC.Device):
      """
      Part of a downconverter with multiple parallel IFs
      
      If the mixer outputs were split so as to be handled differently then
      the downconverter would have channels
      """
      def __init__(self, parent, name, inputs=None, output_names=None,
                   active=True):
        MC.Device.__init__(self, name, inputs=inputs,
                              output_names=output_names, active=active)
  
