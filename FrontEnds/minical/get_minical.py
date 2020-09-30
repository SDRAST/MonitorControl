# -*- coding: utf-8 -*-
"""
Get minical data from K-band front end
"""
import logging
import time

from support.pyro import get_device_server

logger = logging.getLogger(__name__)

# for legacy code in this module
sky = 0
load = 1
off = 1
on = 0
    
def minical_data_old(fe, pms, diag=False):
  """
  Obtains power meter readings for a mini-calibration

  @type fe : FE (front end) instance
  @param fe : receiver to be calibrated

  @type pms : list of pms instances
  @param pms : power meters taking the readings

  @type diag : bool
  @param diag : output diagnostics if True

  @return: tuple::
    "load+ND"      power reading on ambient load with ND on
    "load"         power reading with ambient load
    "sky+ND"       power reading on sky with ND on
    "sky"          power reading on sky
    "load/100"     power reading on load with 20 dB atten
    "zero"         power reading with RF amps off
    "zeroed"       = True if pm was zeroed; False if not
  """
  #   ---------------------------------- Zero PM
  cal_data = {}
  fe.preamp_bias(1,False)
  fe.preamp_bias(2,False)
  for key in pms.keys():
    cal_data[key] = {}
    try:
      pms[key].set_mode('W')
    except:
      print "Could not set pm",key,"mode to W"
    cal_data[key]['mode'] = pms[key].get_mode()
    print "Zeroing",key
    try:
      pms[key].zero(fe)
      cal_data[key]['zeroed'] = True
    except:
      print "Could not zero pm",key
      cal_data[key]['zeroed'] = False

    cal_data[key]['zero'] = pms[key].get_average(5)
    if diag:
      print key,"Zero power (pre-amps off) =", cal_data[key]['zero']
  fe.preamp_bias(1,True)
  fe.preamp_bias(2,True)
  #   ---------------------------------- Ambient Load
  fe.set_feed(1,load)
  fe.set_feed(2,load)
  fe.set_ND(off)
  pwr_load = {}
  pwr_load_div_100 = {}
  for key in pms.keys():
    cal_data[key]['load'] = pms[key].get_average(5)
    if diag:
      print key,"Power on load =", cal_data[key]['load']
    #   --------------------------------- Ambient load + 20 dB atten
    #  not implemented
    cal_data[key]['load/100'] = 0
  #   --------------------------------- Ambient load + Noise Diode
  fe.set_ND(on)
  pwr_load_ND = {}
  for key in pms.keys():
    cal_data[key]['load+ND'] = pms[key].get_average(5)
    if diag:
      print key,"Power on load with ND =", cal_data[key]['load+ND']
  #   --------------------------------- Sky + Noise Diode
  fe.set_feed(1,sky)
  fe.set_feed(2,sky)
# suggestion below line by Tom 110518
  time.sleep(10)
  pwr_sky_ND = {}
  for key in pms.keys():
    cal_data[key]['sky+ND'] = pms[key].get_average(5)
    if diag:
      print key,"Power on sky with ND =", cal_data[key]['sky+ND']
  #   --------------------------------- Sky
  fe.set_ND(off)
  pwr_sky = {}
  for key in pms.keys():
    cal_data[key]['sky'] = pms[key].get_average(5)
    if diag:
      print key,"Power on sky =", cal_data[key]['sky']
  return cal_data

def minical_data(fe, pms, diag=False):
  """
  Obtains power meter readings for a mini-calibration.

  This version measures the sky first and then the load because of
  a possible problem with load movement on the 4-ch K-band front-end.

  @type fe : FE (front end) instance
  @param fe : receiver to be calibrated

  @type pms : list of pms instances
  @param pms : power meters taking the readings

  @type diag : bool
  @param diag : output diagnostics if True

  @return: dictionary::
    "load+ND"      power reading on ambient load with ND on
    "load"         power reading with ambient load
    "sky+ND"       power reading on sky with ND on
    "sky"          power reading on sky
    "load/100"     power reading on load with 20 dB atten
    "zero"         power reading with RF amps off
    "zeroed"       = True if pm was zeroed; False if not
  """
  #   ---------------------------------- Zero PM
  cal_data = {}
  # This turns the pre-amp biases off for power meter zero calibration
  fe.preamp_bias(1,False)
  fe.preamp_bias(2,False)
  for key in pms.keys():
    cal_data[key] = {}
    try:
      pms[key].set_mode('W')
    except:
      print "Could not set pm",key,"mode to W"
    cal_data[key]['mode'] = pms[key].get_mode()
    print "Zeroing",key
    try:
      pms[key].zero(fe)
      cal_data[key]['zeroed'] = True
    except:
      print "Could not zero pm",key
      cal_data[key]['zeroed'] = False

    cal_data[key]['zero'] = pms[key].get_average(5)
    if diag:
      print key,"Zero power (pre-amps off) =", cal_data[key]['zero']
  fe.preamp_bias(1,True)
  fe.preamp_bias(2,True)
  #   --------------------------------- Sky
  fe.set_ND(off)
  fe.set_feed(1,sky)
  fe.set_feed(2,sky)
  pwr_sky = {}
  for key in pms.keys():
    cal_data[key]['sky'] = pms[key].get_average(5)
    if diag:
      print key,"Power on sky =", cal_data[key]['sky']
  #   --------------------------------- Sky + Noise Diode
  fe.set_ND(on)
  # suggestion below line by Tom 110518
  #time.sleep(10)
  pwr_sky_ND = {}
  for key in pms.keys():
    cal_data[key]['sky+ND'] = pms[key].get_average(5)
    if diag:
      print key,"Power on sky with ND =", cal_data[key]['sky+ND']
  #   --------------------------------- Ambient load + Noise Diode
  fe.set_feed(1,load)
  fe.set_feed(2,load)
  pwr_load_ND = {}
  for key in pms.keys():
    cal_data[key]['load+ND'] = pms[key].get_average(5)
    if diag:
      print key,"Power on load with ND =", cal_data[key]['load+ND']
  #   ---------------------------------- Ambient Load
  fe.set_ND(off)
  pwr_load = {}
  pwr_load_div_100 = {}
  for key in pms.keys():
    cal_data[key]['load'] = pms[key].get_average(5)
    if diag:
      print key,"Power on load =", cal_data[key]['load']
    #   --------------------------------- Ambient load + 20 dB atten
    #  not implemented
    cal_data[key]['load/100'] = 0
  fe.set_feed(1,sky)
  fe.set_feed(2,sky)
  return cal_data

 
