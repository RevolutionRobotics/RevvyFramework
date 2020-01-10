# SPDX-License-Identifier: GPL-3.0-only

import enum
import os
import signal
import traceback
import time
from threading import Lock, Event

from revvy.hardware_dependent.rrrc_transport_i2c import RevvyTransportI2C
from revvy.hardware_dependent.sound import SoundControlV1, SoundControlV2
from revvy.mcu.rrrc_control import RevvyControl, BatteryStatus, Version, BootloaderControl
from revvy.mcu.rrrc_transport import TransportException
from revvy.robot.drivetrain import DifferentialDrivetrain
from revvy.robot.imu import IMU
from revvy.robot.remote_controller import RemoteController, RemoteControllerScheduler, create_remote_controller_thread
from revvy.robot.led_ring import RingLed
from revvy.robot.ports.common import PortInstance
from revvy.robot.ports.motor import create_motor_port_handler
from revvy.robot.ports.sensor import create_sensor_port_handler
from revvy.robot.sound import Sound
from revvy.robot.status import RobotStatus, RemoteControllerStatus, RobotStatusIndicator
from revvy.robot.status_updater import McuStatusUpdater
from revvy.robot_config import empty_robot_config
from revvy.scripting.resource import Resource
from revvy.scripting.robot_interface import MotorConstants
from revvy.scripting.runtime import ScriptManager
from revvy.utils.logger import get_logger
from revvy.utils.thread_wrapper import periodic


Motors = {
    'NotConfigured': {'driver': 'NotConfigured', 'config': {}},
    'RevvyMotor':    {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 35, 0.25, 0, -100, 100],
            'position_controller': [4, 0, 0, -600, 600],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution':  1536
        }
    },
    'RevvyMotor_CCW': {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 35, 0.25, 0, -100, 100],
            'position_controller': [4, 0, 0, -600, 600],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution': -1536
        }
    },
    'RevvyMotor_Old':    {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 25, 0.3, 0, -100, 100],
            'position_controller': [10, 0, 0, -900, 900],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution':  1168
        }
    },
    'RevvyMotor_Old_CCW': {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 25, 0.3, 0, -100, 100],
            'position_controller': [10, 0, 0, -900, 900],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution': -1168
        }
    },
    'RevvyMotor_Dexter': {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 8, 0.3, 0, -100, 100],
            'position_controller': [10, 0, 0, -900, 900],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution':  292
        }
    },
    'RevvyMotor_Dexter_CCW': {
        'driver': 'DcMotor',
        'config': {
            'speed_controller':    [1 / 8, 0.3, 0, -100, 100],
            'position_controller': [10, 0, 0, -900, 900],
            'acceleration_limits': [14400, 3600],
            'encoder_resolution': -292
        }
    }
}


Sensors = {
    'NotConfigured': {'driver': 'NotConfigured', 'config': {}},
    'HC_SR04':       {'driver': 'HC_SR04', 'config': {}},
    'BumperSwitch':  {'driver': 'BumperSwitch', 'config': {}},
    'EV3':           {'driver': 'EV3', 'config': {}},
    'EV3_Color':     {'driver': 'EV3_Color', 'config': {}},
}


class Robot:
    BOOTLOADER_I2C_ADDRESS = 0x2B
    ROBOT_I2C_ADDRESS = 0x2D

    def __init__(self, sounds, i2c_bus=1):
        self._i2c_bus = i2c_bus

        self._log = get_logger('Robot')
        self._get_sound_file = sounds

    def __enter__(self):
        self._i2c = RevvyTransportI2C(self._i2c_bus)

        self._robot_control = RevvyControl(self._i2c.bind(self.ROBOT_I2C_ADDRESS))
        self._bootloader_control = BootloaderControl(self._i2c.bind(self.BOOTLOADER_I2C_ADDRESS))

        self._start_time = time.time()

        # read versions
        self._hw_version = self._robot_control.get_hardware_version()
        self._fw_version = self._robot_control.get_firmware_version()

        self._log('Hardware: {}\nFirmware: {}'.format(self._hw_version, self._fw_version))

        setup = {
            Version('1.0'): SoundControlV1,
            Version('1.1'): SoundControlV1,
            Version('2.0'): SoundControlV2,
        }

        self._ring_led = RingLed(self._robot_control)
        self._sound = Sound(setup[self._hw_version](), self._get_sound_file)

        self._status = RobotStatusIndicator(self._robot_control)
        self._status_updater = McuStatusUpdater(self._robot_control)
        self._battery = BatteryStatus(0, 0, 0)

        self._imu = IMU()

        def _motor_config_changed(motor: PortInstance, config_name):
            callback = None if config_name == 'NotConfigured' else motor.update_status
            self._status_updater.set_slot('motor_{}'.format(motor.id), callback)

        def _sensor_config_changed(sensor: PortInstance, config_name):
            callback = None if config_name == 'NotConfigured' else sensor.update_status
            self._status_updater.set_slot('sensor_{}'.format(sensor.id), callback)

        self._motor_ports = create_motor_port_handler(self._robot_control, Motors)
        for port in self._motor_ports:
            port.on_config_changed(_motor_config_changed)

        self._sensor_ports = create_sensor_port_handler(self._robot_control, Sensors)
        for port in self._sensor_ports:
            port.on_config_changed(_sensor_config_changed)

        self._drivetrain = DifferentialDrivetrain(self._robot_control, self._motor_ports.port_count)

        self.update_status = self._status_updater.read
        self.ping = self._robot_control.ping

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._i2c.close()

    @property
    def robot_control(self):
        return self._robot_control

    @property
    def bootloader_control(self):
        return self._bootloader_control

    @property
    def start_time(self):
        return self._start_time

    @property
    def hw_version(self) -> Version:
        return self._hw_version

    @property
    def fw_version(self) -> Version:
        return self._fw_version

    @property
    def battery(self):
        return self._battery

    @property
    def imu(self):
        return self._imu

    @property
    def status(self):
        return self._status

    @property
    def motors(self):
        return self._motor_ports

    @property
    def sensors(self):
        return self._sensor_ports

    @property
    def drivetrain(self):
        return self._drivetrain

    @property
    def led_ring(self):
        return self._ring_led

    @property
    def sound(self):
        return self._sound

    def reset(self):
        self._log('reset()')
        self._ring_led.set_scenario(RingLed.BreathingGreen)
        self._status_updater.reset()

        def _process_battery_slot(data):
            assert len(data) == 4
            main_status = data[0]
            main_percentage = data[1]
            # motor_status = data[2]
            motor_percentage = data[3]

            self._battery = BatteryStatus(chargerStatus=main_status, main=main_percentage, motor=motor_percentage)

        self._status_updater.set_slot("battery", _process_battery_slot)
        self._status_updater.set_slot("axl", self._imu.update_axl_data)
        self._status_updater.set_slot("gyro", self._imu.update_gyro_data)
        self._status_updater.set_slot("yaw", self._imu.update_yaw_angles)
        # TODO: do something useful with the reset signal
        self._status_updater.set_slot("reset", lambda x: self._log('MCU reset detected'))

        self._drivetrain.reset()
        self._motor_ports.reset()
        self._sensor_ports.reset()

        self._status.robot_status = RobotStatus.NotConfigured
        self._status.update()


class RevvyStatusCode(enum.IntEnum):
    OK = 0
    ERROR = 1
    INTEGRITY_ERROR = 2
    UPDATE_REQUEST = 3


class RobotBLEController:

    # FIXME: revvy_ble intentionally doesn't have a type hint at this moment because it breaks tests right now
    def __init__(self, robot: Robot, sw_version, revvy_ble):
        self._log = get_logger('RobotManager')
        self._log('init')
        self.needs_interrupting = True

        self._configuring = False
        self._robot = robot
        self._ble = revvy_ble
        self._sw_version = sw_version

        self._status_update_thread = periodic(self._update, 0.02, "RobotStatusUpdaterThread")
        self._background_fn_lock = Lock()
        self._background_fns = []

        rc = RemoteController()
        rcs = RemoteControllerScheduler(rc)
        rcs.on_controller_detected(self._on_controller_detected)
        rcs.on_controller_lost(self._on_controller_lost)

        self._remote_controller = rc
        self._remote_controller_thread = create_remote_controller_thread(rcs)

        self._resources = {
            'led_ring':   Resource('RingLed'),
            'drivetrain': Resource('DriveTrain'),
            'sound':      Resource('Sound'),

            **{'motor_{}'.format(port.id): Resource('Motor {}'.format(port.id)) for port in self._robot.motors},
            **{'sensor_{}'.format(port.id): Resource('Sensor {}'.format(port.id)) for port in self._robot.sensors}
        }

        revvy_ble['live_message_service'].register_message_handler(rcs.data_ready)
        revvy_ble.on_connection_changed(self._on_connection_changed)

        self._scripts = ScriptManager(self)
        self._config = empty_robot_config

        self._status_code = RevvyStatusCode.OK
        self.exited = Event()

        self.start_remote_controller = self._remote_controller_thread.start

    def _update(self):
        # noinspection PyBroadException
        try:
            self._robot.update_status()

            self._ble['battery_service'].characteristic('main_battery').update_value(self._robot.battery.main)
            self._ble['battery_service'].characteristic('motor_battery').update_value(self._robot.battery.motor)

            with self._background_fn_lock:
                fns, self._background_fns = self._background_fns, []

            for fn in fns:
                self._log('Running background function')
                fn()
        except TransportException:
            self._log(traceback.format_exc())
            self.exit(RevvyStatusCode.ERROR)
        except Exception:
            self._log(traceback.format_exc())

    @property
    def resources(self):
        return self._resources

    @property
    def config(self):
        return self._config

    @property
    def sound(self):
        return self._robot.sound

    @property
    def status_code(self):
        return self._status_code

    @property
    def robot(self):
        return self._robot

    @property
    def remote_controller(self):
        return self._remote_controller

    def exit(self, status_code):
        self._log('exit requested with code {}'.format(status_code))
        self._status_code = status_code
        if self.needs_interrupting:
            os.kill(os.getpid(), signal.SIGINT)
        self.exited.set()

    def wait_for_exit(self):
        self.exited.wait()
        return self._status_code

    def request_update(self):
        def update():
            self._log('Exiting to update')
            time.sleep(1)
            self.exit(RevvyStatusCode.UPDATE_REQUEST)

        self.run_in_background(update)

    def start(self):
        self._log('start')
        if self._robot.status.robot_status == RobotStatus.StartingUp:
            self._log('Waiting for MCU')

            try:
                self._ping_robot()
            except TimeoutError:
                pass  # FIXME somehow handle a dead MCU

            self._ble['device_information_service'].characteristic('hw_version').update(str(self._robot.hw_version))
            self._ble['device_information_service'].characteristic('fw_version').update(str(self._robot.fw_version))
            self._ble['device_information_service'].characteristic('sw_version').update(str(self._sw_version))

            # start reader thread
            self._status_update_thread.start()

            self._ble.start()
            self._robot.status.robot_status = RobotStatus.NotConfigured
            self.configure(None, lambda: self.sound.play_tune('robot2'))

    def run_in_background(self, callback):
        if callable(callback):
            self._log('Registering new background function')
            with self._background_fn_lock:
                self._background_fns.append(callback)
        else:
            raise ValueError('callback is not callable')

    def _on_connection_changed(self, is_connected):
        self._log('Phone connected' if is_connected else 'Phone disconnected')
        if not is_connected:
            self._robot.status.controller_status = RemoteControllerStatus.NotConnected
            self._robot.sound.play_tune('disconnect')
            self.configure(None)
        else:
            self._robot.status.controller_status = RemoteControllerStatus.ConnectedNoControl
            self._robot.sound.play_tune('bell')

    def _on_controller_detected(self):
        self._log('Remote controller detected')
        self._robot.status.controller_status = RemoteControllerStatus.Controlled

    def _on_controller_lost(self):
        self._log('Remote controller lost')
        if self._robot.status.controller_status != RemoteControllerStatus.NotConnected:
            self._robot.status.controller_status = RemoteControllerStatus.ConnectedNoControl
            self.configure(None)

    def configure(self, config, after=None):
        self._log('Request configuration')
        if self._robot.status.robot_status != RobotStatus.Stopped:
            if not self._configuring:
                self._configuring = True
                self.run_in_background(lambda: self._configure(config))
            if callable(after):
                self.run_in_background(after)

    def _reset_configuration(self):
        self.sound.reset_volume()

        self._scripts.reset()
        self._scripts.assign('Motor', MotorConstants)
        self._scripts.assign('RingLed', RingLed)

        self._remote_controller_thread.stop().wait()

        for res in self._resources:
            self._resources[res].reset()

        # ping robot, because robot may reset after stopping scripts
        self._ping_robot()

        self._robot.reset()

    def _apply_new_configuration(self, config):
        # apply new configuration
        self._log('Applying new configuration')

        live_service = self._ble['live_message_service']

        # set up motors
        for motor in self._robot.motors:
            motor.configure(config.motors[motor.id])
            motor.on_status_changed(lambda p: live_service.update_motor(p.id, p.power, p.speed, p.position))

        for motor_id in config.drivetrain['left']:
            self._robot.drivetrain.add_left_motor(self._robot.motors[motor_id])

        for motor_id in config.drivetrain['right']:
            self._robot.drivetrain.add_right_motor(self._robot.motors[motor_id])

        self._robot.drivetrain.configure()

        # set up sensors
        for sensor in self._robot.sensors:
            sensor.configure(config.sensors[sensor.id])
            sensor.on_value_changed(lambda p: live_service.update_sensor(p.id, p.raw_value))

        # set up remote controller
        for analog in config.controller.analog:
            script = analog['script']
            script_handle = self._scripts.add_script(script)
            self._remote_controller.on_analog_values(
                analog['channels'],
                lambda in_data, scr=script_handle: scr.start({'input': in_data})
            )

        for button in range(len(config.controller.buttons)):
            script = config.controller.buttons[button]
            if script:
                script_handle = self._scripts.add_script(script)
                self._remote_controller.on_button_pressed(button, script_handle.start)

        # start background scripts
        for script in config.background_scripts:
            script_handle = self._scripts.add_script(script)
            script_handle.start()

    def _configure(self, config):

        is_default_config = not config and self._robot.status.robot_status != RobotStatus.Stopped

        if is_default_config:
            config = empty_robot_config

        self._config = config

        self._scripts.stop_all_scripts()
        self._reset_configuration()

        self._apply_new_configuration(config)
        if is_default_config:
            self._log('Default configuration applied')
            self._robot.status.robot_status = RobotStatus.NotConfigured
        else:
            self._robot.status.robot_status = RobotStatus.Configured

        self._configuring = False

    def stop(self):
        self._robot.status.controller_status = RemoteControllerStatus.NotConnected
        self._robot.status.robot_status = RobotStatus.Stopped
        self._remote_controller_thread.exit()
        self._ble.stop()
        self._scripts.reset()
        self._status_update_thread.exit()

    def _ping_robot(self, timeout=0):
        start_time = time.time()
        retry_ping = True
        while retry_ping:
            retry_ping = False
            try:
                self._robot.ping()
            except (BrokenPipeError, IOError, OSError):
                retry_ping = True
                time.sleep(0.1)
                if timeout != 0:
                    if time.time() - start_time > timeout:
                        raise TimeoutError