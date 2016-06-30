import hue
import ibeacon
import config

import time, datetime


# initialise Hue bridge
if config.TESTING: bridge = None
else: bridge = hue.HueBridge(username=config.HUE_USERNAME, IP=config.HUE_IP_ADDRESS)

# initialise daylight sensor (daylight times from sunrise-sunset.org API)
daylight_sensor = hue.DaylightSensor(config.LATITUDE, config.LONGITUDE)

# initialise hue controller (triggers timed actions)
hue_controller = hue.HueController(bridge=bridge, rules=config.RULES, daylight_sensor=daylight_sensor)

# initialise presence sensor
presence_sensor = ibeacon.PresenceMonitor()

# register iBeacons with presence sensor
presence_sensor.register_beacon('54480')
presence_sensor.register_beacon('54482')

# set lights to come on when we get home
welcome_lights = ['Hall 1', 'Hall 2']

occupied_before = False

while True:
	# tick controller to check if any actions should be triggered
	hue_controller.tick()
	
	# take an action if occupied status changes (and it's after sunset)
	occupied_now = presence_sensor.occupied()
	if occupied_before != occupied_now:	
		if	occupied_now:
			print('Welcome home!')
			if daylight_sensor.query(datetime.datetime.now()):
				for light in welcome_lights:
					bridge.get(light).on()
			else:
				for light in bridge:
					light.on()
		else:
			print('Bye!')
			for light in bridge:
				light.off()
			time.sleep(30)
	
	occupied_before = occupied_now
	
	# wait a couple of seconds before restarting scan
	time.sleep(config.DELAY)
	print('.')