"""
functions for managing observing projects
"""
import glob
import json
import logging
import os

from support import local_dirs

logger = logging.getLogger(__name__)

def activity_project(activity):
  """
  gives the projects associated with the activity
  """
  projects = []
  if activity:
    for project,activities in get_activity().items():
      logger.debug("%s: %s", project,activities)
      if activity in activities:
        projects.append(project)
    return projects
  else:
    # this allows the function to be called even if there is no activity
    return None

def get_projects():
  """
  Returns a list of paths to projects
  
  Returns a list containing the specified project or, if None, a list to
  currently serviced projects.
  
  Note: for now it returns all the sub-directories of 
  /usr/local/projects/DSAO/Science.  It should read a file maintained by the
  DSAO scheduling manager.
  
  @return: list of str
  """
  sciprojects = []
  paths = glob.glob(local_dirs.proj_conf_path+"*")
  for path in paths:
    if os.path.isdir(path):
      sci_project = os.path.basename(path)
      sciprojects.append(sci_project)
  logger.debug("get_projects: directory items: %s", sciprojects)
  # is this necessary?
  try:
    sciprojects.remove('__pycache__')
  except:
    pass
  return sciprojects

def get_activity():
  """
  Returns a list of paths to activities  (modeled on get_projects)
  
  Returns a list containing the specified activity or, if None, a list to
  currently serviced projects.
  
  Note: for now it returns all the sub-directories of 
  /usr/local/projects/DSAO/Activities.  It should read a file maintained by the
  DSAO scheduling manager.
  
  @return: list of str
  """
  projects = get_projects()
  logger.debug("get_activity: directory items: %s", projects)
  activities = {}
  for project in projects:
    proj_conf_path = local_dirs.proj_conf_path+project+"/"
    conf_file = open(proj_conf_path+"configuration.json")
    conf = json.load(conf_file)
    conf_file.close()
    try:
      activities[project] = list(conf.keys())
    except:
      activities[project] = []
  return activities

def get_session_dirs(activity, dss, year, doy):
  """
  Returns the directories used for a given observing session
  
  The directories don't actually need to exist. The user must call
  mkdir_if_needed().
  
  The directories are::
    session_dir  - where in the DSAO project analysis results are, link to
    realdir      - path in the project directory where the session's files are,
    activity_dir - where in the DSAO project the script and logs are,
    project_dir  - the head of the project's working directory,
    FITSdir      - for the FITS files derived from the conversion of FFT files,
    wvsr_dir     - where the raw WVSR data files are, and
    fftdir       - where the FFT files from the first post-processing steps are
    
  Examples::
    session_dir  - '/usr/local/projects/DSAO/Science/AUTO_EGG/dss14/2017/025/'
    realdir      - '/usr/local/projects/FREGGS/Observations/dss14/2017/025/'
    activity_dir - '/usr/local/projects/DSAO/Activities/EGG0/dss14/2017/025/'
    project_dir  - '/usr/local/projects/DSAO/Science/AUTO_EGG/'
    FITSdir      - '/usr/local/RA_data/FITS/dss14/2017/025/'
    wvsr_dir     - '/data/17g025/'
    fftdir       - '/data/post_processing/auto/17g025/'
  
  @param project : AUTO version of project, like AUTO_EGGx
  @type  project : str
  
  @param dss : station number, e.g. 14
  @type  dss : int
  
  @param year : 4-digit year of observation
  @type  year : int
  
  @param doy : day-of-year of observation, e.g. 68
  @int   doy :
  """
  obs_suffix = "dss%2d/%4d/%03d/" % (dss, year, doy)
  activity_dir = act_proj_path + activity + "/"+obs_suffix
  project = activity_project(activity)
  project_dir = sci_proj_path + get_auto_project(project) + "/"
  session_dir = project_dir+obs_suffix # observing session working files
  wvsrdir = wvsr_dir + make_datadir_name(session_dir)
  fftdir = get_Naudet_FFT_dir(session_dir)
  # define data directory for data structure files (load or dump)
  projectname = get_real_project(project)
  realdir = projects_dir+projectname+"/Observations/"+obs_suffix
  datadir = fits_dir+obs_suffix
  return session_dir, realdir, activity_dir, project_dir, datadir, wvsrdir, fftdir

