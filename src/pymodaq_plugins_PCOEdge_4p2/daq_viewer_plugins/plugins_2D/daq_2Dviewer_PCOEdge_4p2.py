from pymodaq.utils.daq_utils import ThreadCommand
from pymodaq.utils.daq_utils import DataFromPlugins, Axis
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter import Parameter
from qtpy import QtCore,QtWidgets
import numpy as np

# import pylablib as pll
# pll.par["devices/dlls/pco_sc2"] = "path/to/dlls"
from pylablib.devices import PCO
# cam = PCO.PCOSC2Camera()

class PythonWrapperOfYourInstrument:
    #  TODO Replace this fake class with the import of the real python wrapper of your instrument
    pass


class DAQ_2DViewer_PCOEdge_4p2(DAQ_Viewer_base):
    """
    """
    serialnumbers = PCO.list_cameras('usb3')

    params = comon_parameters + [
        ## TODO for your custom plugin
        # elements to be added here as dicts in order to control your custom stage
        ############
        {'title': 'Camera name:', 'name': 'camera_name', 'type': 'str', 'value': '', 'readonly': True},
        {'title': 'Serial number:', 'name': 'serial_number', 'type': 'list', 'limits': serialnumbers},
        {'title': 'X binning', 'name': 'x_binning', 'type': 'int', 'value': 1},
        {'title': 'Y binning', 'name': 'y_binning', 'type': 'int', 'value': 1},
        {'title': 'Image width', 'name': 'hdet', 'type': 'int', 'value': 1, 'readonly': True},
        {'title': 'Image height', 'name': 'vdet', 'type': 'int', 'value': 1, 'readonly': True},
        {'title': 'Timing', 'name': 'timing_opts', 'type': 'group', 'children':
            [{'title': 'Exposure Time (ms)', 'name': 'exposure_time', 'type': 'int', 'value': 100},
             {'title': 'Frame delay', 'name': 'frame_delay', 'type': 'float', 'value': 100},
            {'title': 'FPS', 'name': 'fps', 'type': 'float', 'value': 0.0, 'readonly': True}]
        }        
    ]

    callback_signal = QtCore.Signal()

    def ini_attributes(self):
        #  TODO declare the type of the wrapper (and assign it to self.controller) you're going to use for easy
        #  autocompletion
        self.controller: PCO.PCOSC2Camera = None
        # TODO declare here attributes you want/need to init with a default value
        self.x_axis = None
        self.y_axis = None
        self.data_shape = 'Data2D'
        self.callback_thread = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == "exposure_time":
            self.controller.set_exposure(param.value()/1000)
        elif param.name() == 'frame_delay':
            self.controller.set_frame_delay(param.value)


    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        if not self.settings.child('serial_number').value() == '':
            self.ini_detector_init(old_controller=controller,
                                   new_controller=PCO.PCOSC2Camera(self.settings.child('serial_number').value()))
        else:
            raise Exception('No compatible PCO was found.')        
        print(self.controller)        
        # Get camera name
        # self.settings.child('camera_name').setValue(self.controller.get_device_info().name)
        self.settings.child('serial_number').setValue(self.controller.get_device_info().serial_number)
        # Set exposure time
        self.controller.set_exposure(self.settings.child('timing_opts', 'exposure_time').value()/1000)        
        # Update image parameters
        (*_, hbin, vbin) = self.controller.get_roi()
        width, height = self.controller.get_detector_size()
        self.settings.child('x_binning').setValue(hbin)
        self.settings.child('y_binning').setValue(vbin)
        self.settings.child('hdet').setValue(width)
        self.settings.child('vdet').setValue(height)

        data_x_axis = np.arange(width)*hbin
        data_y_axis = np.arange(height)*vbin
        self.x_axis = Axis(data=data_x_axis, label='', units='')        
        self.y_axis = Axis(data=data_y_axis, label='', units='')



        wait_func = lambda: self.controller.wait_for_frame(since='lastread', nframes=1, timeout=20.0)
        callback = PCOCallback(wait_func)

        self.callback_thread = QtCore.QThread()  # creation of a Qt5 thread
        callback.moveToThread(self.callback_thread)  # callback object will live within this thread
        callback.data_sig.connect(
            self.emit_data)  # when the wait for acquisition returns (with data taken), emit_data will be fired

        self.callback_signal.connect(callback.wait_for_acquisition)
        self.callback_thread.callback = callback
        self.callback_thread.start()


        ## TODO for your custom plugin. Initialize viewers pannel with the future type of data
        self.data_grabed_signal_temp.emit([DataFromPlugins(name='PCOEdge_4p2 Camera', data=[np.zeros((width, height)),],
                                                           dim='Data2D', labels=['dat0'],
                                                           x_axis=self.x_axis,
                                                           y_axis=self.y_axis), ])

        # note: you could either emit the x_axis, y_axis once (or a given place in the code) using self.emit_x_axis()
        # and self.emit_y_axis() as shown above. Or emit it at every grab filling it the x_axis and y_axis keys of
        # DataFromPlugins)

        info = "Whatever info you want to log"
        initialized = True
        return info, initialized


    def grab_data(self, Naverage=1, **kwargs):
        """
        Grabs the data. Synchronous method (kinda).
        ----------
        Naverage: (int) Number of averaging
        kwargs: (dict) of others optionals arguments
        """
        try:
            # Warning, acquisition_in_progress returns 1,0 and not a real bool
            if not self.controller.acquisition_in_progress():
                self.controller.clear_acquisition()
                self.controller.start_acquisition()
            #Then start the acquisition
            self.callback_signal.emit()  # will trigger the wait for acquisition
        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [str(e), "log"]))

    def emit_data(self):
        """
            Fonction used to emit data obtained by callback.
            See Also
            --------
            daq_utils.ThreadCommand
        """
        try:
            # Get  data from buffer
            frame = self.controller.read_newest_image()
            self.settings.child('timing_opts','frame_delay').setValue(self.controller.get_frame_delay())
            # Emit the frame.
            if frame is not None:       # happens for last frame when stopping camera
                self.data_grabed_signal.emit([DataFromPlugins(name='PCOEdge_4p2 Camera', data=[np.squeeze(frame)],
                                                                dim=self.data_shape, labels=['dat0'],
                                                                x_axis=self.x_axis,
                                                                y_axis=self.y_axis), ])

            # To make sure that timed events are executed in continuous grab mode
            QtWidgets.QApplication.processEvents()

        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [str(e), 'log']))
    def callback(self):
        """optional asynchrone method called when the detector has finished its acquisition of data"""
        raise NotImplementedError
        # data_tot = self.controller.your_method_to_get_data_from_buffer()
        # self.data_grabed_signal.emit([DataFromPlugins(name='Mock1', data=data_tot,
        #                                               dim='Data2D', labels=['dat0'])])
        
    def close(self):
        """
        Terminate the communication protocol
        """
        # Terminate the communication        
        self.controller.close()
        self.controller: PCO.PCOSC2Camera = None
        self.callback_thread.quit()
        self.callback_thread = None
        self.status.initialized = False
        self.status.controller = None
        self.status.info = ""    

    def stop(self):
        """Stop the acquisition."""
        self.controller.stop_acquisition()
        self.controller.clear_acquisition()
        return ''

class PCOCallback(QtCore.QObject):
    """Callback object """
    data_sig = QtCore.Signal()
    def __init__(self,wait_fn):
        super().__init__()
        #Set the wait function
        self.wait_fn = wait_fn

    def wait_for_acquisition(self):
        new_data = self.wait_fn()
        if new_data is not False: #will be returned if the main thread called CancelWait
            self.data_sig.emit()  

if __name__ == '__main__':
    main(__file__,init=False)
