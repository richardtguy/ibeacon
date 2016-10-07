#!/usr/local/bin/python3

import time
import ibeacon, config, hue



# Test bridge (Hue and Lightify)
bridge = hue.Bridge(hue_uname=config.HUE_USERNAME, hue_IP=config.HUE_IP_ADDRESS, lightify_IP=config.LIGHTIFY_IP)

for light in bridge:
	light.off()
	
time.sleep(2)

for light in bridge:
	light.on()



# Test presence sensor
"""
def welcome_home(person):
	print('welcome home %s' % (person))
	
def bye(person):
	print('bye')

presence_sensor = ibeacon.PresenceSensor(welcome_callback=welcome_home, last_one_out_callback=bye, topic='ibeacon/fqko3', scan_timeout=config.SCAN_TIMEOUT)
beacon1 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54480"}
beacon2 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54481"}
print((presence_sensor.register_beacon(beacon1, "Richard")))
print((presence_sensor.register_beacon(beacon2, "Michelle")))
presence_sensor.start()

time.sleep(10)

presence_sensor.stop()
"""



