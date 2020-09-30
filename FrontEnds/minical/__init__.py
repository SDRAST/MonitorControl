# -*- coding: utf-8 -*-
"""
module minical

Example of use::
  from hardware_adhoc import FE, PM
  fe = FE()
  ...initialize power meters
  cal_data = minical_data(fe, pms)
  gains, Tlinear, Tquadratic, Tnd, NonLin = process_minical(cal_data)
"""
import logging

from MonitorControl.FrontEnds.minical.get_minical import minical_data
from MonitorControl.FrontEnds.minical.process_minical import process_minical
from support.pyro import get_device_server

logger = logging.getLogger(__name__)

# the following classes enable the use legacy code in get_minical and process_minical

K2 = get_device_server("K2_Server-crux", pyro_ns="crux")

class FE(object):
  def __init():
    self.logger = logging.getLogger(module_logger.name+".FE")

  def set_feed(feed, code):
    if feed == 1:
      if code == sky:
        K2.set_WBDC(13)
      elif code == load:
        K2.set_WBDC(14)
      else:
        self.logger.error("set_feed: bad code %d", code)
    elif feed == 2:
      if code == sky:
        K2.set_WBDC(15)
      elif code == load:
        K2.set_WBDC(16)
      else:
        self.logger.error("set_feed: bad code %d", code)

  def set_ND(state):
    if state == on:
      K2.set_WBDC(23)
    elif state == off:
      K2.set_WBDC(24)
    else:
        self.logger.error("set_ND: bad code %d", state)

  def preamp_bias(feed, state):
    if feed == 1:
      if state:
        K2.set_WBDC(25)
      else:
        K2.set_WBDC(26)
    elif feed == 2:
      if state:
        K2.set_WBDC(27)
      else:
        K2.set_WBDC(28)

class PM(object):
  def __init(ID):
    self.ID = ID
    self.logger = logging.getLogger(module_logger.name+".PM")
    self.get_option = None
    self.set_W = 390+self.ID
    self.set_dB = 400+self.ID
  def zero():
    pass
  def get_mode(ID):
    pass
  def set_mode(ID, mode):
    if mode.upper() == "W":
      K2.set_WBDC(self.set_W)
    elif mode.lower() == "db":
      K2.set_WBDC(self.set_dB)
    else:
      self.logger.error("PM: bad mode %d", mode)
  def get_average(number):
    readings = K2.read_pms()
    return readings
