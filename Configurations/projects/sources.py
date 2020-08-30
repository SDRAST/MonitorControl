"""
"""
import json

from astropy.time import Time

from DatesTimes import calendar_date

def get_all_source_data(projdir):
  """
  Gets data from project sources.json and verifiers.json
  
  Returns source and verifier data and day of observation as a datetime
  
  @param projdir : project directory
  @type  projdir : str
  
  @type year : int
  
  @type doy : int
  
  @return: dict, datetime
  """  
  sourcefile = open(projdir+"sources.json","r")
  sourcedata = json.load(sourcefile)
  sourcefile.close()
  verfile = open(projdir+"verifiers.json","r")
  verdata = json.load(verfile)
  verfile.close()
  sourcedata.update(verdata)
  return sourcedata


