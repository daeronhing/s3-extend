#!/usr/bin/env python3

"""
 This is the Python Banyan GUI that communicates with
 the Raspberry Pi Banyan Gateway

 Copyright (c) 2019 Alan Yorinks All right reserved.

 Python Banyan is free software; you can redistribute it and/or
 modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
 Version 3 as published by the Free Software Foundation; either
 or (at your option) any later version.
 This library is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 General Public License for more details.

 You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
 along with this library; if not, write to the Free Software
 Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""
import argparse
# noinspection PyPackageRequirements
import logging
import pathlib
import serial
# noinspection PyPackageRequirements
from serial.tools import list_ports
import signal
import sys
import threading
import time
from python_banyan.banyan_base import BanyanBase


# noinspection PyMethodMayBeStatic
class PicoboardGateway(BanyanBase, threading.Thread):
    """
    This class is the interface class for the picoboard supporting
    Scratch 3.

    It will regularly poll the picoboard, normalize the sensor data, and then
    publish it. Data is published in the form of a list.
    """

    def __init__(self, back_plane_ip_address=None, subscriber_port='43125',
                 publisher_port='43124', process_name='PicoboardGateway',
                 com_port=None, publisher_topic=None, log=False):
        """
        :param back_plane_ip_address:
        :param subscriber_port:
        :param publisher_port:
        :param process_name:
        :param com_port: picoboard com_port
        """

        # initialize parent
        super(PicoboardGateway, self).__init__(back_plane_ip_address, subscriber_port,
                                               publisher_port, process_name=process_name)

        self.channels = {0: "D", 1: "C",
                         2: "B", 3: "btn", 4: "A",
                         5: "lt", 6: "snd", 7: "slide", 15: "id"}

        self.log = log
        if self.log:
            fn = str(pathlib.Path.home()) + "/pbgw.log"
            self.logger = logging.getLogger(__name__)
            logging.basicConfig(filename=fn, filemode='w', level=logging.DEBUG)
            sys.excepthook = self.my_handler

        self.baud_rate = 38400
        self.publisher_topic = publisher_topic

        # place to receive data from picoboard
        self.data_packet = None

        # data value positions in the data stream
        # generated by the picoboard

        # position 0 = board id
        # position 1 = D  analog inverted logic
        # position 2 = C  analog inverted logic
        # position 3 = B  analog inverted logic
        # position 4 = Button  digital inverted logic
        # position 5 = A  analog inverted logic
        # position 6 = Light  analog inverted logic
        # position 7 = sound  analog
        # position 8 = slider analog

        # positional indices into data stream for analog sensors
        # light is a special case and removed from this list
        self.analog_sensor_list = [1, 2, 3, 5, 7, 8]

        # positional values for specific sensor types
        self.button_position = 4
        self.light_position = 6
        self.sound_position = 7

        # indices that require data inversion.
        # light is left out of this list and handled separately.
        self.inverted_analog_list = [1, 2, 3, 5]

        # The payload data is built as a list of entries.
        # Indices are as follows:
        # index 0 = D  analog inverted logic
        # index 1 = C  analog inverted logic
        # index 2 = B  analog inverted logic
        # index 3 = Button  digital inverted logic
        # index 4 = A  analog inverted logic
        # index 5 = Light  analog inverted logic
        # index 6 = sound  analog
        # index 7 = slider analog

        self.payload = {'report': []}

        # poll request for picoboard data
        self.poll_byte = b'\x01'

        # if a com port was specified use it.
        if com_port:
            self.picoboard = serial.Serial(com_port, self.baud_rate,
                                           timeout=1, writeTimeout=0)
        # otherwise try to find a picoboard
        else:
            if self.find_the_picoboard():
                print('picoboard found on:', self.picoboard.port)
            else:
                print('Please wait 5 seconds...')
                time.sleep(5)
                if not self.find_the_picoboard():
                    print('Cannot find Picoboard')
                    self.shutdown()
        # start the thread to receive data from the picoboard
        threading.Thread.__init__(self)
        self.daemon = True
        self.stop_event = threading.Event()
        self.start()

        # allow thread time to start
        time.sleep(.2)

        while True:
            try:
                time.sleep(.001)
            except (KeyboardInterrupt, serial.SerialException):
                self.shutdown()

    def find_the_picoboard(self):
        """
        Go through the ports looking for an active board
        """

        try:
            the_ports_list = list_ports.comports()
        except (KeyboardInterrupt, serial.SerialException):
            sys.exit(0)

        for port in the_ports_list:
            if port.pid is None:
                continue
            else:
                print('Looking for picoboard on: ', port.device)
                try:
                    self.picoboard = serial.Serial(port.device, self.baud_rate,
                                                   timeout=1, writeTimeout=0)
                except (KeyboardInterrupt, serial.SerialException):
                    sys.exit(0)
                try:
                    self.picoboard.write(self.poll_byte)
                    time.sleep(.2)
                except (KeyboardInterrupt, serial.SerialException):
                    self.shutdown()

                not_done = True
                while not_done:
                    num_bytes = self.picoboard.in_waiting
                    if num_bytes < 18:
                        try:
                            self.picoboard.write(self.poll_byte)
                            time.sleep(.5)
                        except (KeyboardInterrupt, serial.SerialException):
                            self.shutdown()
                    # check the first 2 bytes for channel 0 or f
                    else:
                        data_packet = self.picoboard.read(18)
                        pico_channel = (int(data_packet[0]) - 128) >> 3
                        if pico_channel != 15 and pico_channel != 0:
                            continue
                        # check if the channel data is a value of 4
                        pico_data = int(data_packet[1])

                        if pico_data != 4:
                            return False
                        else:
                            return True

    def analog_scaling(self, value, index):
        """
        scale the normal analog input range of 0-1023 to 0-100
        :param value:
        :param index: sensor index value within data stream
        :return: A value scaled between 0 and 100
        """
        if index == self.light_position:
            input_low = 0
            input_high = 100
        elif index in self.inverted_analog_list:  # the light channel
            input_low = 1023
            input_high = 0
        else:
            input_low = 0
            input_high = 1023

        new_value_low = 0
        new_value_high = 100

        return round(((value - input_low) * ((new_value_high - new_value_low) / (input_high - input_low))) +
                     new_value_low)

    def my_handler(self, xtype, value, tb):
        """
        for logging uncaught exceptions
        :param xtype:
        :param value:
        :param tb:
        :return:
        """
        self.logger.exception("Uncaught exception: {0}".format(str(value)))

    def run(self):
        """
        This method run continually, receiving responses
        to the poll request.

        Formulas for adjusting light and sound are from this URL:
        https://twiki.cern.ch/twiki/pub/Sandbox/DaqSchoolExercise14/A_pico.py.txt
        """
        self.picoboard.write(self.poll_byte)

        while True:
            self.data_packet = None
            # if there is data available from the picoboard
            # retrieve 18 bytes - a full picoboard packet
            cooked = None
            try:
                while self.picoboard.in_waiting != 18:
                    # no data available, just kill some time
                    try:
                        time.sleep(.001)
                    except (KeyboardInterrupt, serial.SerialException):
                        self.shutdown()
            except (KeyboardInterrupt, serial.SerialException):
                self.shutdown()
            # if self.picoboard.inWaiting():
            self.data_packet = self.picoboard.read(18)
            # get the channel number and data for the channel
            for i in range(9):
                # first channel reporting
                if i == 0:
                    pico_channel = (int(self.data_packet[0]) - 128) >> 3
                    if pico_channel != 15 and pico_channel != 0:
                        continue
                    # check if the channel data is a value of 4
                    pico_data = int(self.data_packet[1])
                    if pico_data != 4:
                        break
                # pico_channel = self.channels[(int(self.data_packet[2 * i]) - 128) >> 3]
                raw_sensor_value = ((int(self.data_packet[2 * i]) & 7) << 7) + int(self.data_packet[2 * i + 1])
                if i == 0:  # id
                    cooked = raw_sensor_value
                elif i == self.light_position:
                    if raw_sensor_value < 25:
                        cooked = 100 - raw_sensor_value
                    else:
                        cooked = round((1023 - raw_sensor_value) * (75 / 998))
                    cooked = self.analog_scaling(cooked, self.light_position)

                elif i == self.sound_position:
                    n = max(0, raw_sensor_value - 18)
                    if n < 50:
                        cooked = int(n / 2)
                    else:
                        cooked = 25 + min(75, int((n - 50) * (75 / 580)))
                elif i == self.button_position:  # invert digital input
                    cooked = int(not raw_sensor_value)

                if i in self.analog_sensor_list:
                    # scale for standard analog:
                    cooked = self.analog_scaling(raw_sensor_value, i)

                # don't add the firmware id to the payload -
                # the extension does not need it.
                if i != 0:
                    self.payload['report'].append(cooked)

            self.publish_payload(self.payload, self.publisher_topic)
            # print(self.payload)
            self.payload = {'report': []}
            self.picoboard.write(self.poll_byte)

    def shutdown(self):
        """
        Exit gracefully

        """
        self.picoboard.reset_input_buffer()
        self.picoboard.reset_output_buffer()
        self.picoboard.close()
        sys.exit(0)

def picoboard_gateway():
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", dest="back_plane_ip_address", default="None",
                        help="None or IP address used by Back Plane")
    parser.add_argument("-c", dest="com_port", default="None",
                        help="Use this COM port instead of auto discovery")
    parser.add_argument("-l", dest="log", default="False",
                        help="Set to True to turn logging on.")
    parser.add_argument("-n", dest="process_name",
                        default="PicoboardGateway", help="Set process name in "
                                                         "banner")
    parser.add_argument("-p", dest="publisher_port", default='43124',
                        help="Publisher IP port")
    parser.add_argument("-r", dest="publisher_topic",
                        default="from_picoboard_gateway", help="Report topic")
    parser.add_argument("-s", dest="subscriber_port", default='43125',
                        help="Subscriber IP port")

    args = parser.parse_args()

    kw_options = {
        'publisher_port': args.publisher_port,
        'subscriber_port': args.subscriber_port,
        'process_name': args.process_name,
        'publisher_topic': args.publisher_topic
    }

    if args.back_plane_ip_address != 'None':
        kw_options['back_plane_ip_address'] = args.back_plane_ip_address

    if args.com_port != 'None':
        kw_options['com_port'] = args.com_port

    log = args.log.lower()
    if log == 'false':
        log = False
    else:
        log = True

    kw_options['log'] = log

    PicoboardGateway(**kw_options)


# signal handler function called when Control-C occurs
# noinspection PyShadowingNames,PyUnusedLocal
def signal_handler(sig, frame):
    print('Exiting Through Signal Handler')
    raise KeyboardInterrupt


# listen for SIGINT
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    picoboard_gateway()
