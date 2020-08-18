# -*- coding: utf-8 -*-
"""
This package describes equipment configurations used in DSN radio astronomy.

Nested dict 'cfg' is keyed the DSN stations, then the DSN receivers and then
the polarizations which are available at the inputs of the VLBI DAT matrix
switch, which will also be the DTO matrix switch. This dict can edited easily
if more IFs become available, simply replacing the appropriate 0 with the input
number. If there is no key, that IF does not exist.

References
==========
http://deepspace.jpl.nasa.gov/dsndocs/810-005/302/302C.pdf

Attachment to e-mail from Alina Bedrossian on 03/21/2017 at 09:16 AM gives 
this assignment::
  Antenna Type	Switch	CDSCC	  GDSCC	  MDSCC
      BWG1	      1	    34_S1	  24_S1	  54_S1
	                2	    34_X1	  26_S1	  54_X1
	                3	    34_Ka1	15_X1	  54_Ka1
      BWG2	      4	    35_X1	  25_X1	  55_X1
	                5	    35_Ka1	25_Ka1	55_Ka1
      BWG3	      6	    36_S1	  15_S1	  65_S1
	                7	    36_X1	  26_X1	  65_X1
	                8	    36_Ka1	26_Ka1	63_X2
      70-m	      9	    43_S1	  14_S1	  63_S1
	               10	    43_X1	  14_X1	  63_X1
      AUX	       11	    AUX1	  AUX1	  AUX1
	               12	    AUX2	  AUX2	  AUX2

"""
import logging

logger = logging.getLogger(__name__)

configs = {
  'dss-13'  : ".GDSCC.dss13",
  "DTO"     : ".GDSCC.DTO",
  "DTO-32K" : ".GDSCC.DTO_32K_P4",
  'Krx43'   : ".CDSCC.WBDC1",
  "PSDG"    : ".GDSCC.dto_at_jpl",
  'wbdc2'   : ".CDSCC.WBDC2_at_CIT",
  'WBDC2_K2': ".CDSCC.WBDC2_K2",
  'X43-SAO' : ".CDSCC.DSN_X_SAO",
  'WVSR-14' : ".GDSCC.WVSR"}
            
def station_configuration(context,
                          hardware={},
                          roach_loglevel=logging.WARNING):
  """
  Returns the Observatory instance and equipment dict for a context

  Equipment keys are 'Telescope', 'FE_selector', 'FrontEnd', 'Rx_selector',
  'Receiver', 'IF_switch', 'Backend' and 'sampling_clock'.  They will become
  instances of hardware clients. The default value for each is None, to be
  corrected as appropriate by a specific configuration.
  
  Argument 'hardware' specifies whether a client is to be connected.

  @param context : label for the configuration
  @type  context : str
  
  @param hardware : equipment to be used; default: all
  @type  hardware : dict

  @param roach_loglevel : logging level for corr module
  @type  roach_loglevel : logging module logging level or int

  @return: lab,equipment
  """
  equipment = {'Antenna':        None,    # subclass of Telescope with NMC control
               'FE_selector':    None,
               'FrontEnd':       None,
               'Rx_selector':    None,
               'Receiver':       None,
               'IF_switch':      None,
               'Backend':        None,
               'sampling_clock': None}
  for key in list(equipment.keys()):
    if hardware:
      if key in hardware:
        hardware[key] = hardware[key]
      else:
        hardware[key] = False
    else:
      hardware[key] = False
  logger.debug("station_configuration: hardware is %s", hardware)
  
  if context in configs:
    # invoke the desired configuration
    exec("from "+configs[context]+" import station_configuration")
  else:
    logger.error('station_configuration: "%s" is not a valid context',context)
    logger.error('station_configuration: valid contexts are: %s', list(configs.keys()))
    raise Exception("station_configuration: context %s is not defined",context)
    return None
  lab, equipment = station_configuration(equipment,
                                         hardware=hardware,
                                         roach_loglevel=roach_loglevel)
  return lab, equipment
