#!/usr/bin/python3

# import built-in modules
import datetime, time, threading, signal, sys, random, subprocess, logging, json
# import local modules
import ibeacon, hue, config, fliclib, log

# set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, filename='lights.log')

# set up flic log
log = log.TerminalLog()

print("Starting light controller, press [Ctrl+C] to exit.")

# interlock to ensure that only one thread can access shared resources at a time
lock = threading.Lock()

# signal handler to exit gracefully on Ctrl+C
def exit_handler(signal, frame):
	print('Exiting...', end=' ')
	presence_sensor.stop()
	scan_p.terminate()
	flic_client.close()
	flic_thread.join()
	print('OK')
	sys.exit(0)
signal.signal(signal.SIGINT, exit_handler)

# generate random ID
def get_ID(alphabet='abcdefghijklmnopqrstuvwxyz0123456789', length=8):
	ID = ''
	for c in range(length):
		rand_index = random.randrange(len(alphabet))
		char = alphabet[rand_index]
		ID = ID + char
	return ID

# these lights always come on when one of us gets home
welcome_lights = ['Hall 1', 'Hall 2', 'Dining table', 'Kitchen cupboard']

# these functions are called by the PresenceSensor on last-one-out or first-one-in events
# if using PresenceSensor.start() to loop in a child thread, these will be called from a
# child process, so should be protected by a lock to prevent simultaneous access to the
# Bridge and HueLight objects with the HueController on the main thread.
def welcome_home(beacon_owner):
	with lock:
		print(('[%s] Welcome home %s!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), beacon_owner)))
		if daylight_sensor.query():
			for light in welcome_lights:
				bridge.get(light).on()
		else:
			for light in bridge:
				light.on()

def bye():
	with lock:
		print(("[%s] There's no-one home, turning lights off..." % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))))
		for light in bridge:
			light.off()

# these functions are called by the Flic client when a button is pressed, a new button is found etc.
def click_handler(channel, click_type, was_queued, time_diff):
	log.info(channel.bd_addr + " " + str(click_type))
	logger.info(channel.bd_addr + " " + str(click_type))
	if str(click_type) == 'ClickType.ButtonSingleClick':
		try:
			with lock:
				log.info("Switching on lights associated with button " + channel.bd_addr)
				logger.info("Switching on lights associated with button " + channel.bd_addr)
				for light in groups[channel.bd_addr]['group']:
					bridge.get(light).on()
		except KeyError:
			log.warning("Light not found for button " + str(channel.bd_addr))
			logger.info("Light not found for button " + str(channel.bd_addr))			
	elif str(click_type) == 'ClickType.ButtonHold':
		# turn off all lights
		with lock:
			log.info("Turning off all lights...")
			logger.info("Turning off all lights...")
			for light in bridge:
				light.off()
	elif str(click_type) == 'ClickType.ButtonDoubleClick':
		# not used
		pass

	return

def got_button(bd_addr):
	cc = fliclib.ButtonConnectionChannel(bd_addr)
	# Assign function to call when a button is clicked
	cc.on_button_single_or_double_click_or_hold = click_handler
	cc.on_connection_status_changed = \
		lambda channel, connection_status, disconnect_reason: \
			logger.info(channel.bd_addr + " " + str(connection_status) + (" " + str(disconnect_reason) if connection_status == fliclib.ConnectionStatus.Disconnected else ""))
	flic_client.add_connection_channel(cc)

def got_info(items):
	logger.info('Checking verified flic buttons')
	for bd_addr in items["bd_addr_of_verified_buttons"]:
		logger.info(bd_addr)		
		got_button(bd_addr)

# start ibeacon scanner in subprocess (To-do: wait until scanner is connected before proceeding)
# generate practically unique message topic for pub/sub ibeacon advertisements
topic_ID = 'ibeacon/' + get_ID(length=5)
scan_p = subprocess.Popen(['sudo', 'python', 'start_scanner.py', '--topic', topic_ID])

# initialise Hue bridge
bridge = hue.Bridge(hue_uname=config.HUE_USERNAME, hue_IP=config.HUE_IP_ADDRESS, lightify_IP=config.LIGHTIFY_IP)

# load flic button groups from file
with open('flic_button_groups.json') as f:
	json_data = f.read()
groups = json.loads(json_data)

# create flic client and start in new thread
flic_client = fliclib.FlicClient("localhost")
flic_client.get_info(got_info)
flic_client.on_new_verified_button = got_button
logger.info('Connecting Flic buttons...')
flic_thread = threading.Thread(target=flic_client.handle_events)
flic_thread.start()

# initialise daylight sensor (daylight times from sunrise-sunset.org API)
daylight_sensor = hue.DaylightSensor(config.LATITUDE, config.LONGITUDE)

# initialise presence sensor and register beacons
presence_sensor = ibeacon.PresenceSensor(welcome_callback=welcome_home, last_one_out_callback=bye, topic=topic_ID, scan_timeout=config.SCAN_TIMEOUT)
beacon1 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54480"}
beacon2 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54481"}
logger.info((presence_sensor.register_beacon(beacon1, "Richard")))
logger.info((presence_sensor.register_beacon(beacon2, "Michelle")))
presence_sensor.start()	# starts looping in a new thread

# initialise lights controller (triggers timed actions)
controller = hue.Controller(bridge, config.RULES, daylight_sensor, presence_sensor)

while True:
	# tick controller to check if any actions should be triggered
	# use lock to ensure that any actions triggered are resolved before the Controller
	# releases control to the PresenceSensor (or other child threads)
	with lock: controller.loop_once()
	time.sleep(1)
