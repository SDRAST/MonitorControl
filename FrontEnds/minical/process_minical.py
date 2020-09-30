# -*- coding: utf-8 -*-
"""
module process_minical
"""
import logging
import math
import numpy

logger = logging.getLogger(__name__)

def gain_cal(Tlna, Tf, R1, R2, R3, R4, R5, Tp, Fghz, TP4corr):
  """
  Computes minical parameters from minical data
  
  This uses the Stelreid/Klein calibration algorithm
  Stelzried and Klein, Proc. IEEE, 82, 776 (1994) to
  compute B, BC and CC, as well as Tnd.
  The true gain is B ( BC*R + B*CC*R^2 )

  @type Tlna : float
  @param Tlna :	the LNA noise temperature

  @type Tf : float
  @param Tf	: follow-on amplifier noise temperature contribution

  @type R1 : float
  @param R1	: reading with power meter input zeroed

  @type R2 : float
  @param R2	: reading with LNA connected to antenna

  @type R3 : float
  @param R3 : reading with LNA connected to antenna, noise diode on

  @type R4 : float
  @param R4	: reading with LNA connected to ambient load

  @type R5 : float
  @param R5 : reading on ambient load, noise diode on

  @type Tp : float
  @param Tp : physical temperature of ambient load (deg K)

  @type Fghz : float
  @param Fghz : frequency in GHz

  @type TP4corr : float
  @param TP4corr : correction to T4 due to VSWR at the ambient load
  
  @return: tuple::
    B - linear or mean gain
    BC - linear component of second order gain
    CC - quadratic component of second order gain
    Tnd - noise diode temperature (K)
  """
  # correction from Rayleigh-Jeans approx. to Planck
  Tc = -0.024 * Fghz
  # system temperature on the load
  T4P = Tp + Tlna + Tf + Tc + TP4corr
  # This is the gain, assuming the system is linear:
  # 	T = B * ( R - R1 )
  B = T4P * 1.0/(R4 - R1)
  T2 = B * (R2 - R1) # linear system temperature on sky
  T3 = B * (R3 - R1) # linear system temperature on sky with noise diode
  T5 = B * (R5 - R1) # linear system temperature in load with noise diode
  M = T5*T5 - T4P*T4P - T3*T3 + T2*T2
  N = T5 - T4P - T3 + T2
  CC = N/(N*T4P - M)
  BC = 1.0 - CC*T4P
  Tnd = BC*(T3-T2) + CC*(T3*T3-T2*T2)
  return B, BC, CC, Tnd

def process_minical(cal_data,
                    Tlna = 25,
                    Tf = 1,
                    Fghz = 20,
                    TcorrNDcoupling=0):
  """
  Process minical data
  
  @type cal_data : dict
  @param cal_data : returned by pm_minical for one pm
  
  @type Tlna : float
  @param Tlna : noise temperature of the LNA

  @type Tf : float
  @param Tf : follow-on contribution to the noise temperature

  @type Fghz : float
  @param Fghz : frequency in GHz for Rayleigh-Jeans to Planck correction
  
  @type TcorrNDcoupling : float
  @param TcorrNDcoupling : fraction of ND power that couples into the signal path

  @return: [gains, Tlinear, Tquadratic, Tnd, NonLin]
  """
  R1 = cal_data['zero']
  R2 = cal_data['sky']
  if type(R2) == numpy.ndarray:
    if len(R2.nonzero()[0]) == 0:
      logger.error("process_minical: sky data is zero")
      raise RuntimeError("no valid data")
  else:
    # int or float
    if R2 == 0:
      logger.error("process_minical: zero input")
      return None
  R3 = cal_data['sky+ND']
  R4 = cal_data['load']
  R5 = cal_data['load+ND']
  pm_mode = cal_data['mode']
  if pm_mode == "dBm":
    # convert dBm to W
    if type(R2) == numpy.ndarray:
      R2 = numpy.power(10.0,R2/10.0) / 1000.0
      R3 = numpy.power(10.0,R3/10.0) / 1000.0
      R4 = numpy.power(10.0,R4/10.0) / 1000.0
      R5 = numpy.power(10.0,R5/10.0) / 1000.0
    else:
      R2 = math.pow(10.0,R2/10.0) / 1000.0
      R3 = math.pow(10.0,R3/10.0) / 1000.0
      R4 = math.pow(10.0,R4/10.0) / 1000.0
      R5 = math.pow(10.0,R5/10.0) / 1000.0
  logger.debug("process_minical: R1=%s", R1)
  logger.debug("process_minical: R2=%s", R2)
  logger.debug("process_minical: R3=%s", R3)
  logger.debug("process_minical: R4=%s", R4)
  logger.debug("process_minical: R5=%s", R5)
  gains = gain_cal(Tlna, Tf, R1, R2, R3, R4, R5,
                   cal_data['Tload'], Fghz, TcorrNDcoupling)
  print "gain_cal returned B, BC, CC, Tnd:", gains
  B = gains[0]	# linear gain
  if type(B) == numpy.ndarray:
    if len(B.nonzero()[0]) == 0:
      logger.error("process_minical: failed: gains are zero")
      raise RuntimeError("failed")
  else:
    # int or float
    if B == 0:
      logger.error("process_minical: failed")
      return None
  BC = gains[1]	# linear term of polynomial gain
  CC = gains[2]	# quadratic term of polynomial gain
  # equivalent temperature of noise diode
  Tnd = gains[3]
  # sky, linear gain
  T2 = B * (R2 - R1)
  if type(T2) == numpy.ndarray:
    if len(T2.nonzero()[0]) == 0:
      logger.error("process_minical: failed: sky values are zero")
      raise RuntimeError("failed")
  else:
    # int or float
    if T2 == 0:
      logger.error("process_minical: failed")
      return None
  # sky + ND
  T3 = B * (R3 - R1)
  # load
  T4 = B * (R4 - R1)
  # load + ND
  T5 = B * (R5 - R1)
  Tlinear = [T2, T3, T4, T5]
  T2C = BC*T2 + CC*T2*T2
  T3C = BC*T3 + CC*T3*T3
  T4C = BC*T4 + CC*T4*T4
  T5C = BC*T5 + CC*T5*T5
  Tquadratic = [T2C, T3C, T4C, T5C]
  # Tsky correction
  FL = T2C/T2
  # % non-linearity
  NonLin = 100.0*(FL - 1.0)
  return gains, Tlinear, Tquadratic, Tnd, NonLin

