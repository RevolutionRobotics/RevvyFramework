import unittest

from mock import Mock

from revvy.robot.ports.common import PortInstance
from revvy.robot.ports.motor import create_motor_port_handler


class TestMotorPortHandler(unittest.TestCase):
    def test_constructor_reads_port_amount_and_types(self):
        configs = {"NotConfigured": {}}

        mock_control = Mock()
        mock_control.get_motor_port_amount = Mock(return_value=6)
        mock_control.get_motor_port_types = Mock(return_value={"NotConfigured": 0, "DcMotor": 1})

        ports = create_motor_port_handler(mock_control, configs)

        self.assertEqual(1, mock_control.get_motor_port_amount.call_count)
        self.assertEqual(1, mock_control.get_motor_port_types.call_count)

        self.assertEqual(6, ports.port_count)

    def test_motor_ports_are_indexed_from_one(self):
        configs = {"NotConfigured": {}}

        mock_control = Mock()
        mock_control.get_motor_port_amount = Mock(return_value=6)
        mock_control.get_motor_port_types = Mock(return_value={"NotConfigured": 0})

        ports = create_motor_port_handler(mock_control, configs)

        self.assertRaises(KeyError, lambda: ports[0])
        self.assertIs(PortInstance, type(ports[1]))
        self.assertIs(PortInstance, type(ports[2]))
        self.assertIs(PortInstance, type(ports[3]))
        self.assertIs(PortInstance, type(ports[4]))
        self.assertIs(PortInstance, type(ports[5]))
        self.assertIs(PortInstance, type(ports[6]))
        self.assertRaises(KeyError, lambda: ports[7])

    def test_configure_raises_error_if_driver_is_not_supported_in_mcu(self):
        configs = {
            "NotConfigured": {'driver': 'NotConfigured', 'config': {}},
            "Test": {'driver': "NonExistentDriver"}
        }

        mock_control = Mock()
        mock_control.get_motor_port_amount = Mock(return_value=6)
        mock_control.get_motor_port_types = Mock(return_value={"NotConfigured": 0})
        mock_control.set_motor_port_type = Mock()

        ports = create_motor_port_handler(mock_control, configs)

        self.assertIs(PortInstance, type(ports[1]))
        self.assertEqual(0, mock_control.set_motor_port_type.call_count)

        ports[1].configure("NotConfigured")
        self.assertEqual(1, mock_control.set_motor_port_type.call_count)

        self.assertRaises(KeyError, lambda: ports[1].configure("Test"))
        self.assertEqual(1, mock_control.set_motor_port_type.call_count)
