"""
Antenna mechanical properties

Module parameters::
  rx_cfg - receivers and their properties installed on each antenna
  feeds  - positions of feeds by subreflector index or receiver position
  mech   - antenna mechanical properties
  wrap   - azimuth wrap parameters
  slew   - slew rates and rate-change
  track  - tracking rate limits

Reference
=========
http://deepspace.jpl.nasa.gov/dsndocs/810-005/302/302C.pdf, Table 1
http://deepspace.jpl.nasa.gov/dsndocs/810-005/101/101F.pdf, Tables 2 and 4
"""
import MonitorControl.Configurations.CDSCC as C
import MonitorControl.Configurations.GDSCC as G
import MonitorControl.Configurations.MDSCC as M

rx_cfg = {}
rx_cfg.update(M.cfg)

feeds = {}
feeds.update(M.feeds)

mech = {}
mech.update(C.mech)
mech.update(G.mech)
mech.update(M.mech)

ant_wrap = {70: {"range": 265},
            34: {"range": 225}}
wrap = {}
wrap.update(C.wrap)
wrap.update(G.wrap)
wrap.update(M.wrap)
wrap[14]['wrap'].update(ant_wrap[70])
wrap[24]['wrap'].update(ant_wrap[34])
wrap[25]['wrap'].update(ant_wrap[34])
wrap[26]['wrap'].update(ant_wrap[34])
wrap[34]['wrap'].update(ant_wrap[34])
wrap[35]['wrap'].update(ant_wrap[34])
wrap[36]['wrap'].update(ant_wrap[34])
wrap[43]['wrap'].update(ant_wrap[70])
wrap[63]['wrap'].update(ant_wrap[70])


#
peak_gain = {"L": [61.04, 0.3],
             "S-SX": [63.59, 0.1],
             "X": {"DSS-14": [74.55, 0.1],
                   "DSS-43": [74.63, 0.1],
                   "DSS-63": [74.66, 0.1]},
             "X-SX": {"DSS-14": [74.35, 0.1],
                      "DSS-43": [74.36, 0.1],
                      "DSS-63": [74.19, 0.1]}}

HPBW_70m = {"L": [0.162, 0.016],
        "S": [0.118, 0.012],
        "X": [0.032, 0.003]}

freq_range = {"L": [1628, 1708],
              "S": [2200, 2300],
              "X": [8200, 8600]}

Tsys = {"L": 31.46,
        "S": {"14": 16.90,
              "43": 18.43,
              "63": 20.10},
        "S-SX": {"14": 20.54,
                 "43": 22.53,
                 "63": 23.80},
        "X": {"14": 16.69,
              "43": 17.49,
              "63": 16.73},
        "X-SX": {"14": 17.63,
                 "43": 18.71,
                 "63": 17.91}}
# Tweaked based upon C. Jacobs numbers  1/11/2018  cjn
# we really need a table see below
#
# ant["13"]= 'AZEL   07.00   89.00   1.000   1.000   180.00   360.00   34.0   5215.5245410    243.20554100     3660.9127280'
# ant["14"]= 'AZEL   06.10   86.00   0.230   0.230    44.55   265.35   70.0   5203.9969110    243.11046180     3677.0522770'
# ant["15"]= 'AZEL   06.15   88.00   0.800   0.800   135.10   223.90   34.0   5204.2343260    243.11280490     3676.6699750'
# ant["24"]= 'AZEL   07.00   88.00   0.800   0.800   135.10   223.90   34.0   5209.4825540    243.12520560     3669.2423250'
# ant["25"]= 'AZEL   07.00   88.00   0.800   0.800   135.10   223.90   34.0   5209.6355690    243.12463680     3669.0405670'
# ant["26"]= 'AZEL   07.00   88.00   0.800   0.800   135.10   223.90   34.0   5209.7663620    243.12698360     3668.8717550'
# ant["34"]= 'AZEL   07.00   88.00   0.800   0.800    45.00   224.00   34.0   5205.5080110    148.98196440    -3674.3931330'
# ant["43"]= 'AZEL   06.50   86.00   0.200   0.200   135.0    264.30   70.0   5205.2517830    148.98126730    -3674.7481110'
# ant["45"]= 'AZEL   06.15   88.00   0.780   0.780    45.00   224.00   34.0   5205.4949520    148.97768560    -3674.3809740'
# ant["54"]= 'AZEL   06.15   88.00   0.800   0.800   134.80   224.90   34.0   4862.8321570    355.74590320     4114.6188350'
# ant["55"]= 'AZEL   06.15   88.00   0.780   0.780   132.70   226.10   34.0   4862.9139380    355.74736670     4114.4950840'
# ant["63"]= 'AZEL   06.35   86.00   0.220   0.230    45.00   264.80   70.0   4862.4507820    355.75199150     4115.1092050'
# ant["65"]= 'AZEL   06.15   88.00   0.800   0.800   135.10   223.80   34.0   4862.7155870    355.74930110     4114.7507230'

slew = {70: {"rate": 0.23,  # deg/sec
             "accel": 0.2,  # deg/s/s
             "decel": 2.5}, # deg/s/s
        34: {"rate": 0.780,
             "accel": 0.4,
             "decel": 5.0}}

track = {70: {"minrate": 0.0001, # deg/s
              "maxrate": 0.25},
         34: {"minrate": 0.0001,
              "maxrate": 0.40}}

el_limit = {"min": 6,
            "max": 89.5}

def azimuth_direction(azstart, azend):
  """
  Direction for shortest distance between two azimuths

  Returns the direction and the distance
  """
  delta_az = azend-azstart
  if delta_az > 180:
    return 'ccw', 360-delta_az
  elif delta_az < -180:
    return 'cw', 360+delta_az
  elif delta_az < 0:
    return 'ccw', -delta_az
  else:
    return 'cw', delta_az


def get_dir_dis(ant,az1,az2):
 """
  A routine to estimate the slew time for any DSN antenna. We assume it is dominated by AZ slews.
  We handle the need to unwrap going through the pole. This can adds a good bit of time.

 """
#
#
 debug = 0

 wrapne  = float(wrap[ant]['wrap']['center'])
 wrapmx  = float(wrap[ant]['wrap']['range'])
# First lets calculate the angles for  the current position(1) and the new position (2)
# By definition CW > 0 and CCW < 0  with respect to the Neutral Wrap angle !!
# abs(CW)  and ABS(CCW) < wrapmx  !!
#------------
 cw_angle1 = az1 - wrapne
 if(cw_angle1 > wrapmx or cw_angle1 < 0):
   cw_angle1 = "Null"
 ccw_angle1 = az1 - wrapne
 if(ccw_angle1  > 0):
    ccw_angle1 = ccw_angle1 - 360
 if(abs(ccw_angle1) > wrapmx):
    ccw_angle1 = "Null"
 if(debug > 1):
   print(('Az1 position:   CW_angle =',cw_angle1,   'CCW_angle=',ccw_angle1))
#------------
 cw_angle2 = az2 - wrapne
 if(cw_angle2 > wrapmx or cw_angle2 < 0):
   cw_angle2 = "Null"
 ccw_angle2 = az2 - wrapne
 if(ccw_angle2  > 0):
    ccw_angle2 = ccw_angle2 - 360
 if(abs(ccw_angle2) > wrapmx):
    ccw_angle2 = "Null"
 if(debug > 1):
   print(('Az2 position:   CW_angle =',cw_angle2,   'CCW_angle=',ccw_angle2))
#--------------
# Note we cannot have the case that both CW and CCW angles are both Null !!
 if(cw_angle1 == "Null"):
    wrap1 = "CCW"
 elif(ccw_angle1 == "Null"):
    wrap1 = "CW"
 else:
#   Could be either
    wrap1 = "CWCCW"
#   But We default to cw
    wrap1 = "CW"
#
 if(cw_angle2 == "Null"):
    wrap2 = "CCW"
 elif(ccw_angle2 == "Null"):
    wrap2 = "CW"
 else:
#   Could be either
    wrap2 = "CWCCW"
#   In this case we simply keep the same wrap as before.
    wrap2 = wrap1
#
#
# Wrap change?
 if(wrap2 == wrap1):
#   No wrap change
    if(debug > 0 ): print(" No wrap change")
    if(wrap2 == "CW"):
      delta = cw_angle1 - cw_angle2
    elif(wrap2 == "CCW"):
      delta = ccw_angle1 - ccw_angle2
#
    if delta > 180:
      delta =  360 - delta
    elif delta < -180:
      delta =  360 + delta

    delta =abs(delta)

 else:
    if(debug > 0 ): print(" Wrap change")
    if(wrap1 == "CW"):
      unwrap =      cw_angle1
      more   = abs(ccw_angle2)
    else:
      unwrap = abs(ccw_angle1)
      more   =      cw_angle2
    delta = unwrap + abs(more)
#   Note delta CAN be > 180 !!
#
 if(debug > 0):
   time = abs(delta)/.23/60
   print(('Wrap1   =',wrap1,           '    Wrap2=',wrap2))
   print((' Del Az = ',abs(delta),  '  Slew time =',time))

 return wrap2,abs(delta)

def slew_time(dss, azel1, azel2):
  """
  Calculate time to move from one position to another

  This is a slight overestimate because the distance travelled during
  acceleration and deceleration is not taken into account.
  """
  ant = mech[dss]['diam']
  accel_time = slew[ant]['accel']/slew[ant]['rate']
  decel_time = slew[ant]['decel']/slew[ant]['rate']
  az1,el1 = azel1
  az2,el2 = azel2
  # at this point we need to calculate which azimuth direction to use
# not needed anymore - see below 		  direction, distance = azimuth_direction(az1,az2)
# Ok we need a more complex algorithm do to the need of handling the wrap!
# The slew time is totally dominated by the AZ slew rate
  direction, distance = get_dir_dis(dss,az1,az2)

  az_slew = distance/slew[ant]['rate']
  el_slew = abs(el2-el1)/slew[ant]['rate']
  return direction, accel_time + max(az_slew, el_slew) + decel_time
