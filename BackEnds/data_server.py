"""
Class for serving and recording post-processed live data

The functions which are the tasks to be performed must be defined outside the
class.  I don't recall why.  This should be looked into.

The general plan here is this::
            -------------------------------- reader hands packets to 16 unpackers
           /   |        |         |
          /    |        |         | 16 unpacker_queues
         /     |        |         |
        /      |        |         |
       /       |        |         |
      /        |        |         |
  unpacker unpacker unpacker unpacker ... (12 more)
      \        |        |        /
       \       |        |       /
        \      |        |      /
         \     |        |     /
          \    |        |    / 4 aggregator_queues
           \   |        |   /
            \  |        |  /
             \ \        / /
              \ \      / /
               \ \    / /
                \ \  / /
                aggregator  .... (3 more)
                   / \
   ordered_queue  /   \ monitor_queue
                 /     \
         data_server  averager 
              |          |
          HDF5 file  pickle file    

Then the main thread collects the results from the four aggragators and writes
them to disk.

Example::
  /usr/bin/python \
  /usr/local/lib/python2.7/DSN-Sci-packages/MonitorControl/BackEnds/data_server.py \
  --end_time=2018-191T13:20:00
"""
import cPickle
import h5py
import logging
import numpy
import os
import socket
import sys
import time

from Queue import Empty as QueueEmpty
from multiprocessing import Process, Queue, Value
from struct import unpack_from

from Data_Reduction import get_obs_dirs
from DatesTimes import ISOtime2datetime
from support.logs import get_loglevel, initiate_option_parser, init_logging
from support import sync_second

logger = logging.getLogger(__name__)

pkt_size = 1026*64/8
pkt_fmt = "!8cHHI"+1024*4*"H"
num_workers = 16
num_aggregators = 4
max_count = 5000

if socket.gethostname() == 'gpu1':
  IP = '10.0.0.12'
else:
  IP = '10.0.0.2'
      
def unscramble_packet(input_queue, output_queue):
    """
    gets unscrambled packet
    
    Packet Structure::
      __________________________________________________________________
      |                         64-bit Frames                          |
      |________________________________________________________________|
      | Frame |          uint(3)          | uint(2) | uint(1)| uint(0) |
      |_______|___________________________|_________|__________________|
      |   0   |                user defined header                     |
      |   1   | (pol << 63) + pkt_cnt_sec | sec_cnt |   raw_pkt_cnt    |
      |----------------------------------------------------------------|
      |   2   |            F512           |    F0   |  P512  |   P0    |
      |   3   |            F513           |    F1   |  P513  |   P1    |
      |  ...  |             ...           |   ...   |   ...  |  ...    |
      |  512  |           F1022           |  F510   | P1022  | P510    |
      |  513  |           F1023           |  F511   | P1023  | P511    |
      |----------------------------------------------------------------|
      |  514  |            F512           |    F0   |  P512  |   P0    |
      |  515  |            F513           |    F1   |  P513  |   P1    |
      |  ...  |             ...           |   ...   |   ...  |  ...    |
      | 1024  |           F1022           |  F510   | P1022  | P510    |
      | 1025  |           F1023           |  F511   | P1023  | P511    |
      |----------------------------------------------------------------|
    where P means 'power' and F means 'fourth moment'.  Note that the columns
    are in reversed order: 3,2,1,0.
    
    The unpacking is into::
      - 8 chars
      - 2 unsigned shorts and 1 unsigned int
      - 1024*4 unsigned shorts
    """
    def unscramble(data):
      """
      unscrambles a packet
      """
      D = numpy.array(data, dtype=numpy.uint16).reshape((1024,4))
      power = {}
      power['I'] = numpy.append(D[:512,0],D[:512,1])
      power['Q'] = numpy.append(D[512:,0],D[512:,1])
      kurt = {}
      kurt['I'] = numpy.append(D[:512,2],D[:512,3]).astype(numpy.float32)/4096.
      kurt['Q'] = numpy.append(D[512:,2],D[512:,3]).astype(numpy.float32)/4096.
      return power, kurt

    while True:
      one_second = {}
      one_second['hdr'] = []
      one_second['pkt cnt sec'] = []
      one_second['sec cnt'] = []
      one_second['raw pkt cnt'] = []
      one_second['pwr-I'] = []
      one_second['krt-I'] = []
      one_second['pwr-Q'] = []
      one_second['krt-Q'] = []
      count = max_count
      while count:
          pkt_buf = input_queue.get()
          if count == max_count:
            one_second['time'] = time.time()
          result = unpack_from(pkt_fmt, pkt_buf)
          one_second['hdr'].append(result[:8])
          one_second['pkt cnt sec'].append(result[8])
          one_second['sec cnt'].append(result[9])
          one_second['raw pkt cnt'].append(result[10])
          data = result[11:]
          powr, kurtsis = unscramble(data)
          one_second['pwr-I'].append(powr['I'])
          one_second['krt-I'].append(kurtsis['I'])
          one_second['pwr-Q'].append(powr['Q'])
          one_second['krt-Q'].append(kurtsis['Q'])
          count -= 1
      output_queue.put(one_second)

def get_packet(socket, unpacker_queues):
  """
  gets packets and assigns them to unscramblers
  """
  while True:
      for unpacker in range(num_workers):
        for count in range(max_count):
          data, addr = socket.recvfrom(pkt_size)
          unpacker_queues[unpacker].put(data)

def aggregate_data(inqueue, outqueue):
  """
  move data from the input queue to the output queue
  """
  working = True
  while working:
      data = inqueue.get()
      outqueue.put(data)
      
mfile = {}
aqtime = {}
pkt_cnt = {}
power = {}
kurtosis = {}

def open_monitor_files(monfile_full_path, signal):
    """
    opens file for 1-sec monitor data
    """
    global mfile, aqtime, pkt_cnt, power, kurtosis
    logger.debug("open_monitor_files: opening %s", monfile_full_path)
    for RF in "I", "Q":
      mfile[RF] = h5py.File(monfile_full_path[RF])
      logger.debug("open_monitor_files: opened %s for %s", monfile_full_path[RF], RF)
      # create the datasets, initial length of 1
      mfile[RF].attrs['signal'] = signal[RF]
      mfile[RF].attrs['channel'] = RF
      aqtime[RF] = mfile[RF].create_dataset('time', (1,), maxshape=(None,),
                                            dtype=numpy.float64)
      pkt_cnt[RF] = mfile[RF].create_dataset('pkt cnt', (1,), maxshape=(None,),
                                             dtype=numpy.int32)
      power[RF] = mfile[RF].create_dataset('power', (1,1024),
                                           maxshape=(None,1024))
      kurtosis[RF] = mfile[RF].create_dataset('kurtosis', (1,1024),
                                              maxshape=(None,1024))

def average_one_second(inqueue, working, monfile_full_path, signal):
  """
  collects ordered raw data and writes 1-sec averages to file
  
  This takes the four spectra power-I, kurtosis-I, power-Q and kurtosis-Q and
  arranged them in a 2D array which is written to disk
  
  The file is intialized with datasets whose length is one. So if the counter
  is 0, we just write to the datasets.  Otherwise, we increase the size of the
  datasets by one before writing.
  
  It is crucial that file opening, writing and closing happen in the same
  process.
  
  @param inqueue : where the data come from
  @type  inqueue : subprocessing.Queue object
  
  @param working : flag for while loop to run
  @type  working : int
  
  @param monfile_full_path : monitor file name with full path
  @type  monfile_full_path : str
  
  @param signal : four characters signal code, like 'K26X'
  @type  signal : str
  """
  global mfile, aqtime, pkt_cnt, power, kurtosis
  open_monitor_files(monfile_full_path, signal)
  counter = 0
  while working.value:
    try:
      one_second = inqueue.get(False)
    except QueueEmpty:
      continue
    else:
      average = {}
      logger.debug("average_one_second: got data from %s at %s",
                   inqueue, one_second['time'])
      logger.debug("average_one_second: first packet counter: %d", 
                   one_second['raw pkt cnt'][0])
      for IF in ['I', 'Q']:
        if counter:
          # not equal to zero; increase dataset size by one
          # e.g. if the counter is 1, resize the data set to 2
          aqtime[IF].resize(counter+1, axis=0)
          pkt_cnt[IF].resize(counter+1, axis=0)
          power[IF].resize(counter+1, axis=0)
          kurtosis[IF].resize(counter+1, axis=0)
        logger.debug("average_one_second: doing record %d for %s", counter, IF)
        aqtime[IF][counter] = one_second['time']            # float
        pkt_cnt[IF][counter] = one_second['raw pkt cnt'][0] # int, first packet
        # convert list of 1D arrays into 2D array and average along the list
        # axis 0 is frequency; axis 1 is time
        power[IF][counter] = numpy.array(one_second['pwr-'+IF]).mean(axis=0) 
        kurtosis[IF][counter] = numpy.array(one_second['krt-'+IF]).mean(axis=0)
        mfile[IF].flush()
        logger.debug("average_one_second: added row %d to %s for %s",
                     counter, mfile[IF].file, IF)
      counter += 1
  logger.info("average_one_second: finished")
  for key in mfile.keys():
    logger.info("average_one_second: %s closing", mfile[key].file)
    mfile[key].close()
    
class KurtosisDataServer(object):
  """
  capture kurtosis packets from the 10Gbe port, unpack them and write to file
  """
  def __init__(self, endtime=None):
    """
    initialize the server
    
    The unpacked full data go into /data/kurtspec with no project or station 
    information in the path.  The one-second averages go into the project work
    area so it needs to know the project, which we assume to be PESD unless
    otherwise specified, and the station, which it must get from the first 
    packet.
    
    @param endtime : time to stop processing as (hr, min); default: end of hour
    @type  endtime : tuple(int, int)
    """
    self.logger = logging.getLogger(logger.name +
                                         ".{}".format(self.__class__.__name__))
    self.logger.debug("__init__: logger is %s", self.logger.name)
    self.socket = self._open_socket() # 10Gbe port
    # get one packet to get the band and station data
    self.socket.settimeout(2.)
    try:
      data, addr = self.socket.recvfrom(pkt_size)
    except socket.timeout:
      self.logger.error("__init__: no data at socket")
      sys.exit(1)
    self.socket.settimeout(None)
    packet = unpack_from(pkt_fmt, data)
    self.signal = {'I': "".join(packet[:4]),
                   'Q': "".join(packet[4:8])}
    self.logger.info("__init__: signals are %s", self.signal)
    self.dss = {"I": int(self.signal['I'][1:3]), "Q" : int(self.signal['Q'][1:3])}
    self.band = {"I": self.signal['I'][0], "Q": self.signal['Q'][0]}

    # create some of the queues
    self.ordered_queue = Queue() # final queue for ordered, unscrambled packets
    self.monitor_queue = Queue() # queue for averaging data in 1 sec blocks
    # open the files
    UTtime = time.time()
    UTtuple = time.gmtime(UTtime)
    name_suffix = time.strftime("-%Y-%j-%H%M%S.hdf5", UTtuple)
    #   open the HDF5 file
    self._open_datafile("kurt"+name_suffix, UTtuple)
    #   create the monitor data file names
    self.monfile_full_path = {}
    fname = {}
    for RF in ['I', 'Q']:
      session_data_path, session_work_path, ignore2 = \
               get_obs_dirs("PESD", self.dss[RF], UTtuple.tm_year, UTtuple.tm_yday)
      fname = "mon-"+self.band[RF]+name_suffix
      if os.path.exists(session_data_path):
        pass
      else:
        os.makedirs(session_data_path)
      self.monfile_full_path[RF] = session_data_path + fname
    # create the child processes and start them
    self._create_workers_and_queues()
    self._start_workers()
    if endtime:
      self.endhr = endtime[0]
      self.endmin = endtime[1]
      self.endsec = 0
    else:
      now = time.gmtime(time.time())
      self.endhr = now.tm_hour + 1 # on the hour
      self.endmin = 0
      self.endsec = 0
    self.logger.info("__init__: data_server.py will end at %02d:%02d:%02d",
                        self.endhr, self.endmin, self.endsec)
    self.run()
    self.logger.debug("__init__: program has stopped. Wait for processes to end")
    # wait for child processes to finish
    self._join_workers()
    self.logger.info("__init__: All processes have ended")
    
  def _open_socket(self, host=IP, port=60000):
    """
    opens socket to ROACH 10Gbe
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host,port))
    self.logger.info("_open_socket: socket bound")
    return s
  
  def _create_workers_and_queues(self):
    """
    creates the processes to be run concurrently
    """
    self.unpacker_queue = {} # one unpacker_queue for each of 16 workers
    self.unpacker = {}
    self.aggregator_queue = {} # one unpacker_queue for each of 4 aggregators
    self.aggregator = {}
    for count in range(num_workers):
      self.unpacker_queue[count] = Queue()
      if count % num_aggregators == 0:
        # define the aggregator and aggregator queue for this unpacker
        aggregatorID = count/num_aggregators
        self.aggregator_queue[aggregatorID] = Queue()
        self.aggregator[aggregatorID] = Process(target=aggregate_data,
                                    name="aggregator-"+str(aggregatorID),
                                    args=(self.aggregator_queue[aggregatorID],
                                          self.ordered_queue))
        self.logger.debug(
                "_create_workers_and_queues: aggregator %d takes data from %s",
                aggregatorID, self.aggregator_queue[aggregatorID])
        self.logger.debug(
                   "_create_workers_and_queues: aggregator %d puts data on %s",
                   aggregatorID, self.ordered_queue)
      self.unpacker[count] = Process(target=unscramble_packet,
                                    name="unpacker-"+str(count),
                                    args=(self.unpacker_queue[count],
                                          self.aggregator_queue[aggregatorID]))
      self.logger.debug(
                  "_create_workers_and_queues: unpacker %d takes data from %s",
                  count, self.unpacker_queue[count])
      self.logger.debug(
                     "_create_workers_and_queues: unpacker %d puts data on %s",
                     count, self.aggregator_queue[aggregatorID])
    # one averager and one reader
    self.averaging = Value('B', 1)
    self.averager = Process(target=average_one_second,
                            name="averager",
                            args=(self.monitor_queue,
                                  self.averaging,
                                  self.monfile_full_path,
                                  self.signal))
    self.reader = Process(target=get_packet,
                          name="reader",
                          args=(self.socket, self.unpacker_queue))
    
  def _open_datafile(self, fname, UTtuple):
    """
    opens an HDF5 file for unpacked data
    """
    path = "/data/kurtspec/" + str(UTtuple.tm_year) + "/" \
           + str(UTtuple.tm_yday) + "/"
    self.logger.info("_open_datafile: %s", path+fname)
    try:
      self.file = h5py.File(path+fname)
    except IOError:
      os.makedirs(path)
      try:
        self.file = h5py.File(path+fname)
      except Exception, details:
        self.logger.error("_open_datafile: failed: %s", str(details))
    
  def _start_workers(self):
    """
    Start the processes in the right order
    
    First starts the aggregators which combine packets for the final queue.
    Next start the unpackers.  Finally start the reader.
    """
    for count in range(num_aggregators):
      self.aggregator[count].start()
      self.logger.debug("_start_workers: started aggregator %d", count)
    for count in range(num_workers):
      self.unpacker[count].start()
      self.logger.debug("_start_workers: started unpacker %d", count)
    self.averager.start()
    sync_second()
    self.reader.start() # get all the others going before starting the reader
  
  def _join_workers(self):
    """
    block the main task until all the child tasks have finished
    """
    self.reader.join()
    self.logger.debug("_join_workers: reader finished")
    for count in range(num_workers):
      self.unpacker[count].join()
      self.logger.debug("_join_workers: unpacker %d finished", count)
    for count in range(num_aggregators):
      self.aggregator[count].join()
      self.logger.debug("_join_workers: aggregator %d finished", count)
    self.averager.join()
    self.logger.debug("_join_workers: averager finished")
    
  def _terminate(self):
    """
    """
    global mfile
    # stop the reader first
    try:
      self.reader.terminate()
      self.logger.info("_terminate: reader terminated")
    except AttributeError:
      self.logger.error("_terminate: no reader to terminate")
      pass
    # stop the unpackers
    for count in range(num_workers):
      try:
        self.unpacker[count].terminate()
        self.logger.info("_terminate: unpacker %d terminated", count)
      except AttributeError:
        self.logger.error("_terminate: no %s to terminate",
                          self.unpacker[count])
        pass 
    # stop the aggregators
    for count in range(num_aggregators):
      try:
        self.aggregator[count].terminate()
        self.logger.info("_terminate: aggregator %d terminated",
                            count)
      except AttributeError, details:
        self.logger.error(
                  "_terminate: AttributeError: failed to terminate %s\n%s",
                  self.aggregator[count], details)
        pass
    # stop the averager
    try:
      self.averaging.value = 0
      time.sleep(1)
      self.averager.terminate()
      self.logger.info("_terminate: averager %d terminated", count)
    except ValueError, details:
      self.logger.error(
                       "_terminate: VaueError: failed to terminate %s\n%s",
                       self.averager, details)
      pass
    except AttributeError, details:
      self.logger.error(
                  "_terminate: AttributeError: failed to terminate %s\n%s",
                  self.averager, details)
      pass
      
    # close the socket
    try:
      self.socket.close()
      self.logger.debug("_terminate: socket closed")
    except Exception, details:
      self.logger.debug("_terminate: cannot close socket: %s", details)

  def run(self):
    """
    main thread actions
    """
    self.not_done = True
    grpnum = 0 # count the seconds (each group has one second of data)
    while self.not_done:
      try:
        one_second = self.ordered_queue.get()
        # see if the end time has been reached
        timestruc = time.gmtime(one_second['time'])
        if timestruc.tm_hour == self.endhr and \
           timestruc.tm_min == self.endmin and timestruc.tm_sec == self.endsec:
          self.logger.info("run: end at %s",
                            time.asctime(timestruc))
          self.not_done = False
          # self._terminate() -- redundant; see below
          break
        # process one second of data
        #   put data on monitor queue for averaging
        self.monitor_queue.put(one_second)
        # write raw data
        grpname = "%5d" % grpnum
        grp = self.file.create_group(grpname)
        for d in one_second.keys():
          ds = grp.create_dataset(d, data=numpy.array(one_second[d]))
        self.file.flush()
        self.logger.debug("run: got %s" % grpnum)
        grpnum += 1
      except KeyboardInterrupt:
        self.not_done = False
    self.averaging.value = 0
    self.logger.info("run: averaging off")
    self._terminate()
    
if __name__ == "__main__":
  logging.basicConfig()
  mylogger = logging.getLogger()
  
  p = initiate_option_parser("Kurtosis data server","")
  p.usage = "python data_server.py <kwargs>"
  # Add other options here
  p.add_argument('-e', '--end_time',
                 dest = 'end_time',
                 type = str,
                 default = None,
                 help = 'ISO time to end recording; default: on the next hour')
  args = p.parse_args()
  
  # This cannot be delegated to another module or class
  mylogger = init_logging(logging.getLogger(),
                          loglevel   = get_loglevel(args.file_loglevel),
                          consolevel = get_loglevel(args.console_loglevel),
                          logname    = args.logpath+"data_server.log")
  mylogger.debug("arguments: %s", args)
  mylogger.debug(" Handlers: %s", mylogger.handlers)

  if args.end_time:
    end = ISOtime2datetime(args.end_time)
    server = KurtosisDataServer(endtime=(end.hour,end.minute))
  else:
    server = KurtosisDataServer()


