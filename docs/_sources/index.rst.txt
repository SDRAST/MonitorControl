.. MonitorControl documentation master file, created by
   sphinx-quickstart on Mon Aug  3 13:38:44 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Single Dish Radio Astronomy Software Tools
==========================================

For an overview of SDRAST and the current status please visit https://sdrast.github.io/.

General Purpose Radio Telescope Monitor and Control
===================================================

This is a collection of Python packages for using any fully sterable antenna and
receiver as a radio telescope. The requirement is that the all the systems have
their own controllers which can be operated with through a Python server using a
standard communication protocol (*e.g.* sockets, USB, IEEE-488, RS-232, SNMP,
*etc.*). The base package submodules provide superclasses for clients of these 
servers.

It is possible to use an existing monitor and control system as the server, as
long as there is a way for it to accept commands and send responses using a
standard protocol. In this case, the ``MonitorControl`` server which provides 
the gateway needs to be organized as a set of system servers using the same
interface. 

.. image:: overview.png
In this diagram, each client has a subclass which is specific to the server to
which it interfaces. The client subclasses which used for a particular observing
session are defined in a Python function called ``configuration()``.  There
can be any number of configurations identified by a string ``context``.
Communication between clients and their servers uses the ``Pyro5`` module.

The central server keeps track of what happens to a signal as it enters the
telescope (antenna) and progresses to its final digital format for analysis.
To achieve this there are three base superclasses.

.. image:: baseClasses.png
   :width: 300
Each of the clients in the previous figure is a subclass of ``Device`` which
operates on one or more ``Signal``\ objects that enter and leave *via*
``Port`` objects.

Note
----
These packages are still in a preliminary state.  The original code was very 
specific to the DSN context.  The conversion will proceed subsystem by susbsystem.



Base Class Modules
==================
These modules are all part of the base ``MonitorControl`` package.

.. automodapi:: MonitorControl
.. automodapi:: MonitorControl.Antenna
.. automodapi:: MonitorControl.FrontEnds
.. automodapi:: MonitorControl.Receivers
.. automodapi:: MonitorControl.BackEnds
.. automodapi:: MonitorControl.Configurations

Context Modules
===============
Antenna
-------
.. automodapi:: MonitorControl.Antenna.DSN
.. automodapi:: MonitorControl.Antenna.DSN.simulator

Front Ends
----------
.. automodapi:: MonitorControl.FrontEnds.DSN
.. automodapi:: MonitorControl.FrontEnds.K_band

Receivers
---------
.. automodapi:: MonitorControl.Receivers.DSN
.. automodapi:: MonitorControl.Receivers.WBDC

Back Ends
---------
.. automodapi:: MonitorControl.BackEnds.DSN
.. automodapi:: MonitorControl.BackEnds.ROACH1
.. automodapi:: MonitorControl.BackEnds.ROACH1.SAOclient
.. automodapi:: MonitorControl.BackEnds.ROACH1.simulator

Configurations
--------------
.. automodapi:: MonitorControl.Configurations.CDSCC
.. automodapi:: MonitorControl.Configurations.GDSCC

.. toctree::
   :maxdepth: 2
   :caption: Contents:



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

Last revised by Tom Kuiper 2020 Aug 3.
