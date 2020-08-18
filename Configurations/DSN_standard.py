"""
Standard DSN anetnnas, front ends and receivers

Front end names are of the form band+dss, where band is S, X or Ka and dss is
the station number. The available receivers and polarizations for each antenna
are described in dict 'cfg', which follows the convention established in the
MonitorControl module.

The output channels must have unique names because each has its own
independent data stream.
"""
import logging

from Astronomy.DSN_coordinates import DSN_complex_of
from MonitorControl import ClassInstance, Device, Observatory
from MonitorControl.Antenna import Telescope
from MonitorControl.FrontEnds import FrontEnd
from MonitorControl.FrontEnds.DSN import DSN_fe
from MonitorControl.Receivers import Receiver
from MonitorControl.Receivers.DSN import DSN_rx

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def standard_equipment(dss, band, equipment={}):
  """
  Describe a DSN Complex up to the IF switch

  Implicit here is the naming convention explained above for DSN front ends and
  receivers.  The telescope output name is expected to be the same as the
  telescope name.

  The front end names are constructed from the dict `cfg'.  The initialization
  of 'DSN_fe' depends on this to know the band name.  An example of the
  convention::
    inputs        Device    outputs
    X14           FrontEnd  X14R, X14L
    X14R, X14L    Receiver  X14RU, X14LU
  """
  complex_name = DSN_complex_of(dss)
  if complex_name == "Canberra":
    from MonitorControl.Configurations.CDSCC import cfg
  elif complex_name == "Goldstone":
    from MonitorControl.Configurations.GDSCC import cfg
  elif complex_name == "Madrid":
    from MonitorControl.Configurations.MDSCC import cfg
  else:
    raise RuntimeError("invalid Complex name: "+complex_name)
  logger.debug("standard_equipment: DSS-%2d is at %s", dss, complex_name)
  logger.debug("standard_equipment: cfg = %s", cfg)
  # Define the site
  obs = Observatory(complex_name)
  tel = {}
  fe = {}
  rx = {}
  # define the telescope
  #tel[dss] = Telescope(obs, dss=dss)
  tel = Telescope(obs, dss=dss)
  # for each band available on the telescope
  fename = band+str(dss)
  logger.debug("standard_equipment: getting %s details", fename)
  outnames = []
  # for each polarization processed by the receiver
  for polindex in range(len(cfg[dss][band])): # for each band
    outnames.append(fename+list(cfg[dss][band].keys())[polindex])
  #fe[fename] = ClassInstance(FrontEnd, 
  fe = ClassInstance(FrontEnd,
                             DSN_fe, 
                             fename,
                             inputs = {fename:
                                       #tel[dss].outputs[tel[dss].name]},
                                       tel.outputs[tel.name]},
                             output_names = outnames)
  rx_inputs = {}
  rx_outnames = []
  # this connects the receiver to the front end
  for outname in outnames:
    #rx_inputs[outname] = fe[fename].outputs[outname]
    rx_inputs[outname] = fe.outputs[outname]
    rx_outnames.append(outname+'U')
  #rx[fename] = ClassInstance(Receiver, 
  rx = ClassInstance(Receiver,
                             DSN_rx, 
                             fename,
                             inputs = rx_inputs,
                             output_names = rx_outnames)
  equipment['Telescope'] = tel
  equipment['FrontEnd'] = fe
  equipment['Receiver'] = rx
  return equipment
  
