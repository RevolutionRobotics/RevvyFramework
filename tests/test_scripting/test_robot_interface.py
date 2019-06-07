import unittest
from mock import Mock

from revvy.functions import hex2rgb
from revvy.scripting.resource import Resource
from revvy.scripting.robot_interface import RingLedWrapper


class TestRingLed(unittest.TestCase):
    def test_ring_leds_are_indexed_from_one(self):
        led_mock = Mock()
        led_mock.display_user_frame = Mock()
        led_mock.count = 6

        led_resource = Resource()

        robot = Mock()
        robot.is_stop_requested = False

        rw = RingLedWrapper(robot, led_mock, {'led_ring': led_resource}, 0)
        self.assertRaises(ValueError, lambda: rw.set(0, '#112233'))
        rw.set(1, '#112233')
        rw.set(2, '#112233')
        rw.set(3, '#112233')
        rw.set(4, '#112233')
        rw.set(5, '#112233')
        rw.set(6, '#112233')
        self.assertRaises(ValueError, lambda: rw.set(7, '#112233'))

    def test_ring_led_set_remembers_previous_state(self):
        led_mock = Mock()
        led_mock.display_user_frame = Mock()
        led_mock.count = 6

        led_resource = Resource()

        robot = Mock()
        robot.is_stop_requested = False

        rw = RingLedWrapper(robot, led_mock, {'led_ring': led_resource}, 0)
        rw.set(1, '#112233')
        self.assertEqual([hex2rgb("#112233"), 0, 0, 0, 0, 0], led_mock.display_user_frame.call_args[0][0])
        self.assertEqual(1, led_mock.display_user_frame.call_count)

        rw.set([3, 4], '#223344')
        self.assertEqual(
            [hex2rgb("#112233"), 0, hex2rgb("#223344"), hex2rgb("#223344"), 0, 0],
            led_mock.display_user_frame.call_args[0][0]
        )
        self.assertEqual(2, led_mock.display_user_frame.call_count)
