"""
Flask interface to DSSServer

Enables Vue-based browser client of DSSServer

This is run on the server host and will start a DSSServer instance as an object
in this program. It requires that the NMC server, the front end server, 
the WBDC server, and the spectrometer server are running.

Usage instructions are at https://ra.jpl.nasa.gov:8443/dshaff/dss-monitor-control
"""


import os
import logging
import socket
import sys
import json
import datetime

from flask import Flask
from flask_socketio import SocketIO, emit

from MonitorControl.DSS_server_cfg import tams_config
from MonitorControl.dss_server import DSSServer
from MonitorControl.Configurations  import station_configuration
from support.arguments import initiate_option_parser
from support.logs import setup_logging

__version__ = "1.0.2"

logger = logging.getLogger(__name__)

default_level = logging.DEBUG

module_levels = {
    "support": logging.WARNING,
    "engineio": logging.DEBUG,
    "socketio": logging.DEBUG,
    "eventlet": logging.DEBUG,
    "MonitorControl": logging.DEBUG,
    "MonitorControl.FrontEnds": logging.INFO,
    "MonitorControl.apps.postproc.util": logging.INFO
}

setup_logging(logger=logging.getLogger(""), 
              logLevel=default_level)

for module in module_levels:
    logging.getLogger(module).setLevel(module_levels[module])


class JSONWrapper(object):

    def dumps(self, *args, **kwargs):
        kwargs["allow_nan"] = False
        return json.dumps(*args, **kwargs)

    def loads(self, *args, **kwargs):
        return json.loads(*args, **kwargs)


def setup_server(server):
    """
    Asks DSSServer if the antenna server is simulated
    
    If it is, it does not connect to hardware and sets the Complex to CDSCC.
    This needs fixing, at least, the CDSCC bit.
    """
    server.load_info()
    antenna_simulated = server.hdwr("Antenna", "simulated")
    # this appears to return 'None' instead of 'True' or 'False'
    if antenna_simulated:
        logger.debug("setup_server: switching antenna to workstation 0")
        server.hdwr("Antenna", "connect_to_hardware", 0, "CDSCC")
    return server


def generate_socketio(hardware={}):
    """
    Sets up a Flask server for DSSServer

     start a central server
       the additional keyword arguments for DSSServer are
         import_path   - (str) a path whose corresponding module has a 
                               'station_configuration' function (default None)
         config_args   - (tuple/list) passed to 'station_configuration' 
                                      (default None)
         config_kwargs - (dict) passed to 'station_configuration'
                                (default None) 
         **kwargs      - (dict) keyword arguments for Pyro4Server
    """
    logger.debug("generate_socketio: hardware: %s", hardware)
    server = DSSServer('WBDC2_K2',
                       logger=logging.getLogger(__name__+".DSSServer"),
                       config_args= {"hardware": hardware},
                       boresight_manager_file_paths=[],
                       boresight_manager_kwargs=dict(reload=True,
                                                     dump_cache=False))
    
    # initialize a Flask app
    app = Flask(server.name)
    logger.debug("generate_socketio: Flask initialized")
    app.config['SECRET_KEY'] = "radio_astronomy_is_cool"
    socketio = SocketIO(app, json=JSONWrapper(), cors_allowed_origins="*")
    logger.debug("generate_socketio: SocketIO initialized")
    
    # simulate the antenna connection if desired
    server = setup_server(server)
    logger.debug("generate_socketio: server set up")
    
    # flaskify the server
    app, socketio, server = DSSServer.flaskify_io(
        server, app=app, socketio=socketio
    )
    logger.debug("generate_socketio: server IO flaskified")

    def init(data):
        logger.debug("generate_socketio.init: got {}".format(data))

    def hostname():
        logger.debug("generate_socketio.hostname: called")
        host = socket.gethostname()
        with app.app_context():
            socketio.emit("hostname", host)
        logger.debug("generate_socketio.hostname: host: {}".format(host))

    def teardown():
        logger.debug("generate_socketio.teardown: disconnect at %s",
                     datetime.datetime.now().ctime())
        server.save_info()

    socketio.on_event("init",       init)
    socketio.on_event("hostname",   hostname)
    socketio.on_event("disconnect", teardown)
    return app, socketio, server


def main():
    host = socket.gethostname() # this appears to be unnecessary
    
    usage = "python web_server.py <args>"
    description = """start Flask web server with central M&C server"""
    examples= """
Start server with no hardware control:
  python web_server.py
Start server with all hardware enabled
  python web_server.py --antenna --frontend --receiver --backend
"""
    parser = initiate_option_parser(description,examples)
    parser.usage = usage
    # Add other options here
    parser.add_argument("--antenna", "-a",
                        dest='antenna',
                        action='store_true',
                        default=False,
                        help="connect to antenna server")
    parser.add_argument("--frontend", "-f",
                        dest='frontend',
                        action='store_true',
                        default=False,
                        help="connect to frontend server")
    parser.add_argument("--receiver", "-r",
                        dest='receiver',
                        action='store_true',
                        default=False,
                        help="connect to receiver server")
    parser.add_argument("--backend", "-b",
                        dest='backend',
                        action='store_true',
                        default=False,
                        help="connect to backend server")
    
    args = parser.parse_args()
    
    app_logger = logging.getLogger()

    hardware = {"Antenna":  args.antenna,
                "FrontEnd": args.frontend, 
                "Receiver": args.receiver, 
                "Backend":  args.backend}

    app, socketio, server = generate_socketio(hardware=hardware)
    app_logger.debug("hardware: %s", hardware)
    app_logger.debug("app is %s", app)
    app_logger.debug("socketio is %s", socketio)
    app_logger.debug("server is %s", server)
    socketio.run(app, port=5000)
    app_logger.warning("Server terminated at %s",
                        datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss"))
    server.close()


if __name__ == "__main__":
    main()
