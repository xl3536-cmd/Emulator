"""
Author: Xiaxin Liu
Date: Feb-18-2026

Voltage divider test out with RPI GPIO pin 17 and ssr hat
"""

import RPi.GPIO as GPIO
import time

PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

try:
    while True:
        print(GPIO.input(PIN))
        time.sleep(0.2)
finally:
    GPIO.cleanup()
