.. MonitorControl documentation master file, created by
   sphinx-quickstart on Mon Aug  3 13:38:44 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Single Dish Radio Astronomy Software Tools
==========================================

For an overview of SDRAST and the current status please visit https://sdrast.github.io/.

Note
====
These packages are in a very preliminary state and need lots of work.  The original code was very specific to the DSN context.  The conversion will proceed subsystem by susbsystem.

Base Class Modules
==================
.. automodapi:: MonitorControl
.. automodapi:: MonitorControl.Antenna
.. automodapi:: MonitorControl.FrontEnds
.. automodapi:: MonitorControl.Receivers
.. automodapi:: MonitorControl.BackEnds

Context Modules
===============
.. automodapi:: MonitorControl.Antenna.DSN
.. automodapi:: MonitorControl.FrontEnds.DSN
.. automodapi:: MonitorControl.Receivers.DSN
.. automodapi:: MonitorControl.BackEnds.DSN

.. toctree::
   :maxdepth: 2
   :caption: Contents:



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

Last revised by Tom Kuiper 2020 Aug 3.
