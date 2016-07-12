import ibeacon, hue, config
import datetime, time

# interlock to ensure that only one thread can access shared resources at a time
lock = threading.Lock()

# signal handler to exit gracefully on Ctrl+C
def exit_handler(signal, frame):
	print('Exiting...')
	presence_sensor.stop()
	sys.exit(0)
signal.signal(signal.SIGINT, exit_handler)


# these functions are called by the PresenceSensor on last-one-out or first-one-in events
# if using PresenceSensor.start() to loop in a child thread, these will be called from a
# child process, so should be protected by a lock to prevent simultaneous access to the
# HueBridge and HueLight objects with the HueController on the main thread.
def welcome_home():
	with lock:
		print('[%s] Welcome home!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
		if daylight_sensor.query(datetime.datetime.now()):
			for light in welcome_lights:
				bridge.get(light).on()
		else:
			for light in bridge:
				light.on()

def bye():
	with lock:
		print('[%s] Bye!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
		for light in bridge:
			light.off()

# initialise Hue bridge
bridge = hue.HueBridge(username=config.HUE_USERNAME, IP=config.HUE_IP_ADDRESS)

# initialise daylight sensor (daylight times from sunrise-sunset.org API)
daylight_sensor = hue.DaylightSensor(config.LATITUDE, config.LONGITUDE)

# initialise presence sensor and register beacons
presence_sensor = ibeacon.PresenceSensor(first_one_in_callback=welcome_home, last_one_out_callback=bye, scan_timeout=config.SCAN_TIMEOUT)
beacon1 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54480"}
beacon2 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54481"}
print(presence_sensor.register_beacon(beacon1, "Richard"))
print(presence_sensor.register_beacon(beacon2, "Michelle"))
presence_sensor.start()	# starts looping in a new thread

# initialise hue controller (triggers timed actions)
hue_controller = hue.HueController(bridge, config.RULES, daylight_sensor, presence_sensor)

# set lights to come on when we get home
welcome_lights = ['Hall 1', 'Hall 2', 'Dining table']

while True:
	# tick controller to check if any actions should be triggered
	# use lock to ensure that any actions triggered are resolved before the HueController
	# releases control to the PresenceSensor (or other child threads)
	with lock: hue_controller.loop_once()
