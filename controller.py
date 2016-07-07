import hue
import config

import time, datetime


# initialise Hue bridge
if config.TESTING: bridge = None
else: bridge = hue.HueBridge(username=config.HUE_USERNAME, IP=config.HUE_IP_ADDRESS)

# initialise daylight sensor (daylight times from sunrise-sunset.org API)
daylight_sensor = hue.DaylightSensor(config.LATITUDE, config.LONGITUDE)

# initialise presence sensor and register beacons
presence_sensor = hue.PresenceSensor()
presence_sensor.register_beacon('54480')	# Richard
presence_sensor.register_beacon('54481')	# Michelle

# initialise hue controller (triggers timed actions)
hue_controller = hue.HueController(bridge, config.RULES, daylight_sensor, presence_sensor)

# set lights to come on when we get home
welcome_lights = ['Hall 1', 'Hall 2', 'Dining table']

occupied_before = False

while True:
	# tick controller to check if any actions should be triggered
	hue_controller.tick()
	
	# take an action if occupied status changes (and it's after sunset)
	occupied_now = presence_sensor.occupied()
	if occupied_before != occupied_now:	
		if	occupied_now:
			print('[%s] Welcome home!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
			if daylight_sensor.query(datetime.datetime.now()):
				print('It\'s daylight...')
				for light in welcome_lights:
					bridge.get(light).on()
			else:
				print('It\'s dark...')
				for light in bridge:
					light.on()
		else:
			print('[%s] Bye!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
			for light in bridge:
				light.off()
	
	occupied_before = occupied_now
	
	# wait a couple of seconds before restarting scan
	time.sleep(config.DELAY)
