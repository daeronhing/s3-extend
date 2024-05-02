#!/usr/bin/env python

import pigpio
import time

# based on an example provided with the pigpio library

class Sonar:
    """
    This class encapsulates a sonar device with separate
    trigger and echo pins.

    A pulse on the trigger initiates the sonar ping and shortly
    afterwards a sonar pulse is transmitted and the echo pin
    goes high.  The echo pins stays high until a sonar echo is
    received (or the response times-out).  The time between
    the high and low edges indicates the sonar round trip time.
    """

    def __init__(self, pi, trigger, echo):
        """
        The class is instantiated with the Pi to use and the
        gpios connected to the trigger and echo pins.
        """
        self.pi = pi
        self._trig = trigger
        self._echo = echo

        self._trig_mode = pi.get_mode(self._trig)
        self._echo_mode = pi.get_mode(self._echo)

        pi.set_mode(self._trig, pigpio.OUTPUT)
        pi.set_mode(self._echo, pigpio.INPUT)

        self._inited = True

    def read(self):
        """
        Triggers a reading.  The returned reading is the distance in cm
        """
        self.pi.gpio_trigger(self._trig, 15, 1)
        t3 = time.time()
        
        # Wait for echo pin to receive
        while not self.pi.read(self._echo):
            t4 = time.time()
            if (t4 - t3) > 0.03:
                return -1
            
        t1 = time.time()
        
        # Wait for receive finish
        while self.pi.read(self._echo):
            t5 = time.time()
            if (t5 - t1) > 0.03:
                return -2
            
        t2 = time.time()
        return ((t2-t1) * 340 / 2) * 100

    def cancel(self):
        """
        Cancels the ranger and returns the gpios to their
        original mode.
        """
        if self._inited:
            self._inited = False
            self.pi.set_mode(self._trig, self._trig_mode)
            self.pi.set_mode(self._echo, self._echo_mode)


# if __name__ == "__main__":
#
#     import time
#
#     import pigpio
#
#     pi = pigpio.pi()
#
#     sonar = Sonar(pi, 1, 0)
#
#     end = time.time() + 30
#
#     while time.timme() < end:
#         reading = sonar.read()
#         print("Reading: ".format(reading))
#         time.sleep(0.03)
#
#     sonar.cancel()
#
#     pi.stop()
