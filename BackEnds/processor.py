"""
Class for post-processing devices
"""
import logging
import numpy
import socket

from MonitorControl import Device, ObservatoryError

module_logger = logging.getLogger(__name__)

class Processor(Device):
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
    mylogger = logging.getLogger(parent.logger.name+".Processor")
    self.name = name
    self.parent = parent
    mylogger.debug(" initializing %s", self)
    Device.__init__(self, name, inputs=inputs,
                          output_names=output_names, active=active)
    self.logger = mylogger
    self.logger.debug(' inputs: %s', self.inputs)
    if datahost:
      dest_IP = socket.gethostbyname(datahost)
      try:
        self.MACbase = self.parent.summary[name+' MAC'] # MAC base address
      except KeyError:
        # interface not defined
        module_logger.warning("DataChl: %s device not known",name)
      else:
        self.IP = self.parent.summary[name+' IP']
        mac_base = decode_MAC(self.MACbase)
        ip_addr = decode_IP(self.IP)
        mac_addr = mac_base+ip_addr

