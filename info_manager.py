"""
provides class to manage program status information
"""
import datetime
import json
import logging
import os
import sys
import time

import DatesTimes as DT
from local_dirs import projects_dir

# the async approach depends on the type of communication between programs
if 'MonitorControl.pyro_server' in sys.modules.keys():
  from support.asyncio.pyro import async_method
elif 'MonitorControl.web_server' in sys.modules.keys():
  from support.asyncio.flaskio import async_method
else:
  from support.asyncio import async_method

logger = logging.getLogger(__name__)

class InfoManager(object):
    """
    class to manage program status information
    """
    def __init__(self, parent=None, activity="default"):
        """
        """
        self.parent = parent
        self.activity = activity
        self.logger = logging.getLogger(logger.name+".InfoManager")
        
    def _init_info(self, progname):
        """
        initialize program parameters to defaults
        
        This is provided by the parent program but must contain at least the
        items below.
        """
        self.info = {
          "info_save_dir": projects_dir + self.parent.project + "/Status/" \
                                             + progname + "/",
          "last_change": DT.logtimestamp(),
          "project":     {"name":     self.parent.project,
                          "activity": self.parent.activity,
                          "observer": None},
          "sources":     {},
          "verifiers":   {},
          "calibrators": {}
        }
        self.logger.debug("_init_info({}): info: {}".format(
                                                        DT.logtime(),self.info))

    def init_info(self, progname, activity='default', template=None):
      """
      """
      self._init_info(progname)
      self.info.update(template)
      return self.info

        
    @async_method
    def set_info(self, path, val):
        """
        Set some path within ``_info`` attribute in a thread safe manner

        Examples:

            >>> server.set_info(["project", "name"],"TAMS")
            >>> server.set_info(["tip","running"],False)

        Args:
            path (list): "path", inside info property to value we want to set.
            val (obj): desired value.

        """
        self.logger.debug("set_info: called with path: {}, val: {}".format(path, val))
        with self.parent.lock:
            info_copy = self.info
            sub_path = self.info[path[0]]
            self.logger.debug("set_info: subpath: {}".format(sub_path))
            for p in path[1:-1]:
                sub_path = sub_path[p]
                self.logger.debug("set_info: subpath: {}".format(sub_path))
            sub_path[path[-1]] = val
            self.set_info.cb() # no response to client

    #@support.test.auto_test()
    @async_method
    def get_info(self, path=None):
        """
        Get some path in ``info`` attribute in thread safe attribute
        If no path is provided, return entire ``info`` attribute

        Examples:

            >>> server.get_info(["boresight","running"])
            False
            >>> server.get_info(["point","current_source"])
            "0521-365"

        Args:
            path (list/None): Get some value from ``info``, or some value from a
                subdictionary of ``info``.

        Returns:
            obj: Either value of dictionary/subditionary, or subdictionary itself.
        """
        self.logger.debug("get_info: path: {}".format(path))
        with self.parent.lock:
            if path is None:
                self.get_info.cb(self.info) # send client the entire info dict
                return self.info
            sub_path = self.info[path[0]]
            for p in path[1:]:
                sub_path = sub_path[p]
            self.get_info.cb(sub_path) # send client the requested data
            return sub_path

    #@support.test.auto_test()
    def save_info(self):
        """
        Dump info attribute to a file.
        """
        # info file should go with others, not where the file was loaded from
        # if not os.path.exists(self.info["info_save_dir"]):
        #    os.makedirs(self.info["info_save_dir"])
        # self.logger.debug(
        #    "save_info: info_save_dir: {}".format(self.info["info_save_dir"]))
        save_file_name = "info_{}.json".format(DT.logtimestamp())
        save_file_path = os.path.join(self.info["info_save_dir"], save_file_name)
        self.logger.info("save_info: Saving file {}".format(save_file_path))
        t0 = time.time()
        with open(save_file_path, "w") as f:
            json.dump(self.info, f)
        self.logger.debug(
            "save_info({}): Took {:.3f} seconds to dump info".format(DT.logtime(),
                time.time() - t0))

    #@support.test.auto_test()
    def load_info(self):
        """
        Load in _info attribute from most recently dumped settings file.
        
        This assumes a file name like "info_2020-269-22h39m15s.json"
        
        Attribute ``info`` contains parameters for an ongoing observing activity
        so ``CentralServer`` can start with the same software configuration as
        the previous time.
        
        The location of the info files is specified in the file w
        """
        save_file_dir = self.info['info_save_dir']
        self.logger.debug(
            "load_info: Looking in {} for status files".format(save_file_dir))
        try:
          statusfiles = os.listdir(save_file_dir)
        except FileNotFoundError:
          self.logger.warning("load_info: directory not found; using defaults")
          os.makedirs(self.info["info_save_dir"])
          self.logger.info("load_info: creates %s", save_file_dir)
          return
        self.logger.debug("load_info: found %s", statusfiles)
        
        file_paths = []
        file_datetime_objs = []
        for f_name in statusfiles:
            if ".json" in f_name:
                try:
                    # a status file name must have the form
                    #   <stuff>_YEAR-DOY-HHhMMmSSs.<ext>
                    datetime_str = os.path.splitext(f_name)[0].split("_")[1]
                    datetime_obj = datetime.datetime.strptime(datetime_str,
                                                              "%Y-%j-%Hh%Mm%Ss")
                    file_datetime_objs.append(datetime_obj)
                    file_paths.append(os.path.join(save_file_dir, f_name))
                except Exception as err:
                    self.logger.debug(
                           "load_info: Can't parse file name {}".format(f_name))
        if len(file_paths) > 0:
            # now order the files
            ordered_dt_objs, ordered_paths = list(zip(*sorted(zip(
                                              file_datetime_objs, file_paths))))
            # now get most recent path!
            most_recent_path = ordered_paths[-1]
            self.logger.info("load_info: Using file {} to set info".format(
                                                              most_recent_path))
            # now load it into memory and set _info attribute
            t0 = time.time()
            with open(most_recent_path, "r") as f:
                # info_new = Trackable(json.load(f))
                info_new = json.load(f)
            # correct this if not current
            info_new['info_save_dir'] = save_file_dir
            self.info = info_new
            self.logger.debug(
                       "load_info({}): Took {:.3f} seconds to load info".format(
                          DT.logtime(), time.time() - t0))
        else:
            self.logger.info(
                   "load_info: Couldn't find any files from which to load info")
            
    def report_info(self):
        """
        """
        return self.info

