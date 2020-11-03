import logging
import socket

app_logger = logging.getLogger()
app_logger.setLevel(logging.DEBUG)
app_logger.debug("logging started")

from MonitorControl.pyro_server import PyroServer

from support.arguments import initiate_option_parser

def main():
    host = socket.gethostname() # this appears to be unnecessary
    
    usage = "python pyro_server.py <args>"
    description = """start Pyro server with central M&C server"""
    examples= """
Start server with no hardware control:
  python pyro_server.py
Start server with all hardware enabled
  python pyro_server.py --antenna --frontend --receiver --backend
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
    
    #app_logger = logging.getLogger()

    hardware = {"Antenna":  args.antenna,
                "FrontEnd": args.frontend, 
                "Receiver": args.receiver, 
                "Backend":  args.backend}

    server = PyroServer('WBDC2_K2',
                       logger=logging.getLogger(__name__+".PyroServer"),
                       config_args= {"hardware": hardware},
                       boresight_manager_file_paths=[],
                       boresight_manager_kwargs=dict(reload=True,
                                                     dump_cache=False))
    server.info_manager.load_info()
    antenna_simulated = server.hdwr("Antenna", "simulated")
    # this appears to return 'None' instead of 'True' or 'False'
    if antenna_simulated:
        app_logger.debug("setup_server: switching antenna to workstation 0")
        app_server.hdwr("Antenna", "connect_to_hardware", 0, "CDSCC")

    app_logger.debug("hardware: %s", hardware)
    app_logger.debug("server is %s", server)
    
    server.launch_server(
            objectId=server.equipment["Antenna"].name,
            objectPort=50015, ns=False, threaded=False, local=True
        )
    app_logger.warning("Server terminated at %s",
                        datetime.datetime.utcnow().strftime("%Y-%j-%Hh%Mm%Ss"))
    server.close()


if __name__ == "__main__":
    main()
