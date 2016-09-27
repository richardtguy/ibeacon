import hue, config, time, logging
from lightify import Lightify, Light


print('Testing initialise connection to Lightify Gateway...')
		
# initialise bridge connection to Lightify Gateway via LAN
bridge = hue.Bridge(lightify_IP = config.LIGHTIFY_IP)
"""
for light in bridge:
	light.on()

time.sleep(2)

for light in bridge:
	light.off()
"""
bridge.recall_local_scene('test')
