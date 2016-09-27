import hue, config, time, logging
from lightify import Lightify, Light

		
# initialise bridge connection to Lightify Gateway via Cloud API
bridge = hue.Bridge(hue_uname = config.HUE_USERNAME, hue_IP = config.HUE_IP_ADDRESS)

# initialise connection to Lightify Gateway via local network
LIGHTIFY_IP = '192.168.1.10'

lightify = Lightify(LIGHTIFY_IP)

logging.basicConfig(filename='test.log',level=logging.DEBUG)

lightify.update_all_light_status()
lights = lightify.lights()

for light in lights.values():
	bridge.lights[light.name()] = light
	print(light.get_name())
	
print('Testing initialise connection to Lightify Gateway...')

"""
for light in bridge:
	light.off()
	
time.sleep(2)

for light in bridge:
	light.on()
"""