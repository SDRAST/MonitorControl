MonitorControl
==============

MonitorControl modules, classes and functions
---------------------------------------------

The concept of monitoring and controlling equipment is based on a ``Device``
class with inputs and outputs of the ``Port`` class, which accept and provide
``Signal`` class objects.

The device classes for descriptions of telescopes in ``Antenna``, ``FrontEnd``,
``Receiver``, ``Backend``, and ``Switch``. These are superclasses defined
in subdirectories of the same name, and are not
associated with any specific hardware but define the general characteristics
of the device.

The actual hardware is defined in subdirectories of the prototype directory.
Actual hardware control is performed by independent servers which provide
remote control via the ``Pyro`` module.  The subclasses of the generic devices
are clients of these servers.  The client software is aware of how the signals
are modified at each stage; the servers are not.

Observing at a very primitive level is possible by starting each of the servers
and connecting to them with a Python command line.  This is useful for testing.

There is an overall server which is the parent of the individual clients.
The server can also be operated from the command line.  However, it is intended
to serve monitor and control functions to a web browser client.

The project `website <https://github.com/SDRAST/MonitorControl/>`_ 
contains the  Git repository from which the package can be cloned.

Software `documentation <https://sdrast.github.io/MonitorControl/>`_
is generated with Sphinx.

