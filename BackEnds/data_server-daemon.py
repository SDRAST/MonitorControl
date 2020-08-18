"""
Class for serving and recording post-processed live data

The functions which are the tasks to be performed must be defined outside the
class.  I don't recall why.  This should be looked into.

The generalplan here is this::
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
"""
import cPickle
import h5py
import logging
import numpy
import os
import signal
import socket
import time

from multiprocessing import Process, Queue
from struct import unpack_from

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
        #try:
          pkt_buf = input_queue.get()
          if count == max_count:
            one_second['time'] = time.time()
          result = unpack_from(pkt_fmt, pkt_buf)
          one_second['hdr'].append(result[:8])
          one_second['pkt cnt sec'].append(result[8])
          one_second['sec cnt'].append(result[9])
          one_second['raw pkt cnt'].append(result[10])
          data = result[11:]
          power, kurtosis = unscramble(data)
          one_second['pwr-I'].append(power['I'])
          one_second['krt-I'].append(kurtosis['I'])
          one_second['pwr-Q'].append(power['Q'])
          one_second['krt-Q'].append(kurtosis['Q'])
          count -= 1
        #except (KeyboardInterrupt):
        #  # wait for reader to finish
        #  pass
      output_queue.put(one_second)
      #logger.debug("unscramble_packet: unscrambled %d packets from %s at %f",
      #              max_count, input_queue, one_second['time'])
      #logger.debug("unscramble_packet: unscrambling ended at %f", time.time())

def get_packet(socket, unpacker_queues):
  """
  gets packets and assigns them to unscramblers
  """
  while True:
    #try:
      for unpacker in range(num_workers):
        #logger.debug("get_packet: getting data for worker %d", unpacker)
        #logger.debug("get_packet: putting data on %s at %f",
        #             unpacker_queues[unpacker], time.time())
        for count in range(max_count):
          data, addr = socket.recvfrom(pkt_size)
          unpacker_queues[unpacker].put(data)
        #logger.debug("get_packet: finished %d packets at %f",
        #             max_count, time.time())
    #except KeyboardInterrupt:
    #  # nothing to do; signal_handler takes care of it
    #  pass

def aggregate_data(inqueue, outqueue):
  """
  move data from the input queue to the output queue
  """
  working = True
  while working:
    #try:
      data = inqueue.get()
      #logger.debug("aggregate_data: got data from %s at %s", inqueue, data['time'])
      #logger.debug("aggregate_data: sent data to %s at %s", outqueue, data['time'])
      outqueue.put(data)
    #except KeyboardInterrupt:
    #  # nothing to do; signal_handler takes care of it
    #  working = False

def average_one_second(inqueue, outfile):
  """
  collects ordered raw data and writes 1-sec averages to file
  """
  def merge_1_sec(one_second):
    """
    Average power and kurtosis data for one second
    
    @param one_second - 1 sec worth of data
    @type  one_second - dict
    """
    for key in ['pwr-I', 'krt-I', 'pwr-Q', 'krt-Q']:
      array1d = numpy.array(one_second[key]).mean(axis=0)
      array2d = array1d.reshape(array1d.shape[0],1)
      if key == 'pwr-I':
        merged = array2d
      else:
        merged = numpy.append(merged, array2d, axis=1)
    return merged
    
  working = True
  while working:
    #try:
      one_second = inqueue.get()
      average = {}
      logger.debug("average_one_second: got data from %s at %s",
                   inqueue, one_second['time'])
      array_1_sec = merge_1_sec(one_second)
      cPickle.dump(array_1_sec, outfile)
      outfile.flush()
      logger.debug("average_one_second: sent data to %s at %s",
                   outfile.name, one_second['time'])
    #except KeyboardInterrupt:
    #  # nothing to do; signal_handler takes care of it
    #  working = False
  

class KurtosisDataServer(object):
  """
  capture kurtosis packets from the 10Gbe port, unpack them and write to file
  """
  def __init__(self):
    """
    initialize the server
    """
    self.logger = logging.getLogger(logger.name+".KurtosisDataServer")
    self.socket = self._open_socket() # 10Gbe port
    self.ordered_queue = Queue() # final queue for ordered, unscrambled packets
    self.monitor_queue = Queue() # queue for averaging data in 1 sec blocks
    UTtime = self._open_datafile()
    self._open_monitor_file(UTtime)
    self._create_workers_and_queues()
    signal.signal(signal.SIGINT,  self.signal_handler)
    signal.signal(signal.SIGHUP,  self.signal_handler)
    signal.signal(signal.SIGTERM, self.signal_handler)
    self._start_workers()
    self.run()
    self._join_workers()
    
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
    self.unpacker_queue = {} # one unpacker_queue for each worker
    self.unpacker = {}
    self.aggregator_queue = {}
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
    self.averager = Process(target=average_one_second,
                            name="averager",
                            args=(self.monitor_queue, self.mfile))
    self.reader = Process(target=get_packet,
                          name="reader",
                          args=(self.socket, self.unpacker_queue))
    
  def _open_datafile(self):
    """
    opens an HDF5 file for unpacked data
    """
    UTtuple = time.gmtime()
    fname = time.strftime("kurt-%Y-%j-%H%M%S.hdf5", UTtuple)
    path = "/data/HDF5/dss14/" + str(UTtuple.tm_year) + "/" \
           + str(UTtuple.tm_yday) + "/"
    self.logger.debug("_open_datafile: %s", path+fname)
    try:
      self.file = h5py.File(path+fname)
    except IOError:
      os.makedirs(path)
      self.file = h5py.File(path+fname)
  
  def _open_monitor_file(self, UTtime):
    """
    opens file for 1-sec monitor data
    """
    UTtuple = time.gmtime(UTtime)
    fname = time.strftime("mon-%Y-%j-%H%M%S.pkl", UTtuple)
    path = "/data/HDF5/dss14/" + str(UTtuple.tm_year) + "/" \
           + str(UTtuple.tm_yday) + "/"
    self.logger.debug("_open_datafile: %s", path+fname)
    try:
      self.mfile = open(path+fname, "wb+")
    except IOError:
      os.makedirs(path)
      self.mfile = h5py.File(path+fname)
    return UTtime
    
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
    for count in range(num_aggregators):
      self.aggregator[count].join()
      self.logger.debug("_join_workers: started aggregator %d", count)
    for count in range(num_workers):
      self.unpacker[count].join()
      self.logger.debug("_start_workers: started unpacker %d", count)
    self.averager.join()
    self.reader.join()
    
  def signal_handler(self, signl, frame):
    """
    This does not end the thread
    """
    if signl == signal.SIGINT:
      self.logger.debug("signal_handler: Ctrl-C received")
    elif signl == signal.SIGHUP:
      self.logger.debug("signal_handler: Hangup signal received")
    else:
      return
    self.not_done = False
    
    # stop the reader first
    try:
      self.reader.terminate()
      #self.reader.join()
      self.logger.warning("signal_handler: reader terminated")
    except AttributeError:
      self.logger.debug("signal_handler: no reader to terminate")
      pass
    time.sleep(16) # give all the unpackers time to finish.
      
    # stop the unpackers
    for count in range(num_workers):
      try:
        self.unpacker[count].terminate()
        #self.unpacker[count].join()
        self.logger.warning("signal_handler: unpacker %d terminated", count)
      except AttributeError:
        self.logger.error("signal_handler: no %s to terminate",
                          self.unpacker[count])
        pass 
    time.sleep(4) # give the aggregators time to empty their queues.
    
    # stop the aggregators
    for count in range(num_aggregators):
      try:
        self.aggregator[count].terminate()
        #self.aggregator[count].join()
        self.logger.warning("signal_handler: aggregator %d terminated",
                            count)
      except AttributeError, details:
        self.logger.error(
                  "signal_handler: AttributeError: failed to terminate %s\n%s",
                  self.aggregator[count], details)
        pass
    
    time.sleep(4) # give time to finish writing to files
    try:
      self.socket.close()
    except Exception, details:
      self.logger.debug("signal_handler: cannot close socket: %s", details)
    try:
      self.file.close()
    except ValueError:
      # probably already closed
      self.logger.warning("signal_handler: file close error")
    
    # stop the averager
    try:
      self.averager.terminate()
      self.averager.join()
      self.logger.warning("signal_handler: averager %d terminated", count)
    except ValueError, details:
      self.logger.warning(
                       "signal_handler: VaueError: failed to terminate %s\n%s",
                       self.averager, details)
      pass
    except AttributeError, details:
      self.logger.warning(
                  "signal_handler: AttributeError: failed to terminate %s\n%s",
                  self.averager, details)
      pass

  def run(self):
    """
    """
    self.not_done = True
    grpnum = 0
    while self.not_done:
      try:
        one_second = self.ordered_queue.get()
        timestruc = time.gmtime(one_second['time'])
        if timestruc.tm_min == 0 and timestruc.tm_sec == 0:
          self.logger.debug("run: start of new hour at %s",
                            time.asctime(timestruc))
          # close the main data file
          self.file.close()
          self.logger.debug("run: %s closed", self.file.name)
          # stop the averager
          self.averager.terminate()
          self.logger.debug("run: averager terminated")
          self.averager.join(1)
          # close the monitor file
          self.logger.debug("run: averager finished")
          self.mfile.close()
          self.logger.debug("run: %s closed", self.mfile.name)
          UTtime = self._open_datafile()
          self.logger.debug("run: %s opened", self.file.name)
          self._open_monitor_file(UTtime)
          self.logger.debug("run: %s opened", self.mfile.name)
          self.averager = Process(target=average_one_second,
                                  args=(self.monitor_queue, self.mfile))
          self.averager.start()
          self.logger.debug("run: averager started")
        self.monitor_queue.put(one_second)
        grpname = "one_second %5d" % grpnum
        grp = self.file.create_group(grpname)
        for d in one_second.keys():
          ds = grp.create_dataset(d, data=numpy.array(one_second[d]))
        self.file.flush()
        self.logger.debug("run: got %s" % grpnum)
        grpnum += 1
      except KeyboardInterrupt:
        self.not_done = False
  
    #self.reader.join()
    #for count in range(num_workers):
    #  self.unpacker[count].join()
    #for count in range(num_aggregators):
    #  self.aggregator[count].join()
    #self.averager.join()
    
class ScansProcessor(object):
  """
  """
  def __init__(self):
    """
    """
    pass
    
  def record_scans(self, test=True, offset=0):
    """
    Record the scans defined in a scans file
    
    The method reads the .scans file parsing each line into a dict with keys::
      scan     - scan number
      start    - start UNIX time
      stop     - end UNIX time
      source   - source name
      exposure - integration time in seconds
    It gets the observation parameters and then sets the IF switch accordingly.
    It then starts a scan if the current time is equal to or greater than the
    start time and less than the stop time, computing the number of 1-sec
    records to request from the server.
    
    @param test : only print diagnostic info for each scan (default: False)
    @type  test : bool
    
    @param offset : number of seconds before times in the scans file
    @type  offset : int
    
    @param switch_override : manually set designated switch state
    @type  switch_override : dict
    """
    if switch_override:
      self.switch_override = switch_override
    
    def get_obs_pars():
      """
      """
      session_fmt = projects_dir + \
                       "DSAO/Activities/" + self.activity + '/dss%2d/%4d/%03d/'
      session_dir = session_fmt % (self.dss, self.year, self.DOY)
      files = glob.glob(session_dir+"*.scans")
      # there are two but either will do
      scans_file = files[0]
      f = open(scans_file, 'r')
      lines = f.readlines()
      f.close()
      rxID = []
      bands = []
      pols = []
      for f in files:
        # this parses the scans file name for IF channel info
        IF = f.split('.')[0].split('_')[-1]
        receiverID = IF[:-3]+str(self.dss)
        rxID.append(receiverID)
        bands.append(receiverID[:-2])
        pol = IF[-3:]
        pols.append(pol)
        
      return rxID, bands, pols, lines

    def get_scans(lines):
      """
      """
      scans = {}
      scans['scan'] = []
      scans['start'] = []
      scans['stop'] = []
      scans['source'] = []
      scans['exposure'] = []
      for line in lines:
        parts = line.strip().split()
        scans['scan'].append(int(parts[0]))
        scans['source'].append(parts[-1])
        start = calendar.timegm(time.strptime(str(2018)+"/"+ parts[1],
                                "%Y/%j/%H:%M:%S"))
        scans['start'].append(start)
        stop = calendar.timegm(time.strptime(str(2018)+"/"+ parts[2],
                               "%Y/%j/%H:%M:%S"))
        scans['stop'].append(stop)
        scans['exposure'].append(stop-start)
      return scans
      
    rxID, bands, pols, lines = get_obs_pars()
    scans = get_scans(lines)    
    for idx in range(len(scans['scan'])):
      print scans['scan'][idx], scans['start'][idx], scans['stop'][idx], \
            scans['source'][idx], scans['exposure'][idx]
      # do 1 sec scans for integration
      if test:
        print scans['scan'][idx], scans['start'][idx], scans['stop'][idx], \
              scans['source'][idx], scans['exposure'][idx]
      else:
        if offset:
          scans['start'][idx] -= offset
          scans['stop'][idx] -= offset
        if calendar.timegm(time.gmtime()) > scans['stop'][idx]:
          # current time is after scan stop time
          self.logger.info("record_scans: skipping %s", scans['scan'][idx])
        while calendar.timegm(time.gmtime()) < scans['start'][idx]:
          # wait
          time.sleep(0.001)
        self.logger.info("record_scans: sleep ended with scan %s",
                         scans['scan'][idx])
        if calendar.timegm(time.gmtime()) >=  scans['start'][idx]:
          # do scan for exposure
          self.spectrometer.hardware.start(scans['exposure'][idx])
          self.logger.debug("record_scans: recording scan %s for %d sec",
                            scans['scan'][idx], scans['exposure'][idx])
    
if __name__ == "__main__":
  logging.basicConfig()
  mylogger = logging.getLogger()
  mylogger.setLevel(logging.DEBUG)

  server = KurtosisDataServer()

