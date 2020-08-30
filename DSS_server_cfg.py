"""
class to define the software parameters and a Configuration object for TAMS

Also creates an instance of that class
"""
import os

from support.configuration import Configuration, _make_properties

# This is a list of public configuration objects defined in this module
__all__ = [
    "tams_config"
]
@_make_properties([
    "hdf5_data_dir",
    "fits_data_dir",
    "boresight_data_dir",
    "flux_calibration_data_dir",
    "tipping_data_dir",
    "status_dir",
    "sources_dir",
    "models_dir",
    "log_dir",
    "product_dir",
    "dss",
    "rest_freq"
])

class TAMSConfiguration(object):

    def __init__(self,
                 data_dir="",
                 calibration_dir="",
                 project_dir="",
                 log_dir="",
                 product_dir="",
                 boresight_model_file="",
                 rest_freq=2.223508e10):

        self._data_dir = data_dir
        self._hdf5_data_dir = os.path.join(self._data_dir, "HDF5", "dss43")
        self._fits_data_dir = os.path.join(self._data_dir, "FITS", "dss43")

        self._calibration_dir = calibration_dir
        self._boresight_data_dir = os.path.join(
            self._calibration_dir,
            "boresight_data"
        )
        self._flux_calibration_data_dir = os.path.join(
            self._calibration_dir,
            "flux_calibration_data"
        )
        self._tipping_data_dir = os.path.join(
            self._calibration_dir,
            "tipping_data"
        )
        self._status_dir = os.path.join(
            self._calibration_dir,
            "status"
        )

        self._project_dir = project_dir
        self._sources_dir = os.path.join(self._project_dir, "Observations")
        self._models_dir = os.path.join(self._project_dir, "models")
        self._boresight_model_file = boresight_model_file

        self._log_dir = log_dir

        self._product_dir = product_dir
        self._rest_freq = rest_freq

    @property
    def data_dir(self):
        return self._data_dir

    @data_dir.setter
    def data_dir(self, path):
        self._data_dir = path
        self._hdf5_data_dir = os.path.join(self._data_dir, "HDF5", "dss43")
        self._fits_data_dir = os.path.join(self._data_dir, "FITS", "dss43")

    @property
    def calibration_dir(self):
        return self._calibration_dir

    @data_dir.setter
    def calibration_dir(self, path):
        self._calibration_dir = path
        self.boresight_data_dir = os.path.join(
            self._calibration_dir, "boresight_data")
        self.flux_calibration_data_dir = os.path.join(
            self._calibration_dir, "flux_calibration_data")
        self.tipping_data_dir = os.path.join(
            self._calibration_dir, "tipping_data")
        self.status_dir = os.path.join(
            self._calibration_dir, "status")

    @property
    def project_dir(self):
        return self._project_dir

    @project_dir.setter
    def project_dir(self, path):
        self._project_dir = path
        self._sources_dir = os.path.join(self._project_dir, "Observations")
        self._models_dir = os.path.join(self._project_dir, "models")

    @property
    def boresight_model_file_path(self):
        return os.path.join(self.models_dir, self._boresight_model_file)

from support.local_dirs import data_dir, local_packages, log_dir, projects_dir

tams_config = Configuration(
    TAMSConfiguration,
    data_dir             = data_dir,
    #config_dir           = local_packages + "MonitorControl/Configurations",
    project_dir          = projects_dir + "TAMS",
    log_dir              = log_dir + "dss43",
    calibration_dir      = data_dir,
    product_dir          = data_dir + "products",
    boresight_model_file = "AdaBoostClassifier.2018-07-05T09:17:31.dat",
    rest_freq=2.223508e10
)
#tams_config = Configuration(
#    TAMSConfiguration,
#    data_dir="/home/ops/roach_data/sao_test_data/RA_data",
#    calibration_dir="/home/ops/roach_data/sao_test_data/data_dir",
#    project_dir="/home/ops/projects/TAMS",
#    log_dir="/usr/local/logs/dss43",
#    product_dir="/home/ops/roach_data/sao_test_data/data_dir/products",
#    boresight_model_file="AdaBoostClassifier.2018-07-05T09:17:31.dat",
#    rest_freq=2.223508e10
#)




