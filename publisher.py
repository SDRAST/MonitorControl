############################## general superclasses ###########################

#from support import NamedClass as MCobject
#from support import PropertiedClass as MCgroup
try:
  from support import zmq
except ImportError:
  logger.warning("failed to import zmq")

try:
  #from support.pyro import config
  #@config.expose
  @Pyro5.api.expose
  class MCPublisher(zmq.ZmqPublisher):

    def __init__(self, name=None):
        super(MCPublisher, self).__init__(name=name)
        logger.debug("MCPublisher.__init__: data_dir is %s for %s",
                            self.data_dir, self.roach_name)

    def stop_publishing(self):
        super(MCPublisher, self).stop_publishing()

    def start_recording(self, *args):
        """
        Initialize the datafile and start publishing
        """
        logger.debug("MCPublisher.start_recording invoked")
        self.start_publishing(*args)

    def stop_recording(self):
        """Alias for stop_publishing"""
        self.stop_publishing()
        
except ImportError:
  logger.warning("failed to import config; no MCPublisher")

