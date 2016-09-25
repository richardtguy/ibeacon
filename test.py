import hue, config, time

print('Testing initialise connection to Lightify Gateway')
bridge = hue.Bridge(lightify_uname=config.LIGHTIFY_USERNAME, lightify_pword=config.LIGHTIFY_PASSWORD, lightify_serial=config.LIGHTIFY_SERIAL)

for light in bridge:
	light.on()