#!/usr/bin/python3

# import built-in modules
import datetime, time, threading, signal, sys, random, subprocess, logging, json
# import installed modules
import requests, soco
# import local modules
from jubilee import ibeacon, lights, uid
import config, fliclib

def run():
	# set up logging
	logger = logging.getLogger(__name__)
	logging_level = sys.argv[1].upper()
	logging.basicConfig(
		filename=config.LOG_FILENAME,
		level=logging_level,
		format='%(asctime)-12s | %(levelname)-8s | %(name)s | %(message)s',
		datefmt='%d/%m/%y, %H:%M:%S'
	)
	
	print("Starting light controller, press [Ctrl+C] to exit.")
	logger.info("Starting light controller...")
		
	# signal handler to exit gracefully on Ctrl+C
	def exit_handler(signal, frame):
		print('Exiting...', end='')
		logger.info('Exiting...')		
		presence_sensor.stop()
		remote.stop()
		scan_p.terminate()
		flic_client.close()
		flic_thread.join()
		print(' OK')
		logger.info(' OK')
		sys.exit(0)
	signal.signal(signal.SIGINT, exit_handler)
	
	# these lights always come on when one of us gets home
	welcome_lights = ['Hall 1', 'Hall 2', 'Dining table', 'Kitchen cupboard']
	
	# these functions are called by the PresenceSensor on last-one-out or first-one-in events
	def welcome_home(beacon_owner):
		logger.info('Welcome home %s!' % (beacon_owner))
		if daylight_sensor.query():
			bridge.light_on(welcome_lights)
		else:
			bridge.light_on([])
	
	def bye():
		logger.info("There's no-one home, turning lights off...")
		bridge.light_off([])
		if sonos != None:
			logger.info("Turning speakers off...")
			for speaker in sonos:
				speaker.stop()
		
	
	# these functions are called by the Flic client when a button is pressed, a new button is found etc.
	def click_handler(channel, click_type, was_queued, time_diff):
		logger.info(channel.bd_addr + " " + str(click_type))
		if str(click_type) == 'ClickType.ButtonSingleClick':
			if channel.bd_addr in groups.keys():
				logger.info("Switching on lights associated with button " + channel.bd_addr)
				bridge.light_on(groups[channel.bd_addr]['group'])
			else:
				logger.debug('%s Button not registered with any lights' % (channel.bd_addr))				
		elif str(click_type) == 'ClickType.ButtonHold':
			# turn off all lights
			logger.info("Turning off all lights...")
			bridge.light_off([])
			for speaker in sonos:
				speaker.stop()
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
		print(' OK')
		logger.info(bd_addr + ' OK')
	
	def got_info(items):
		print('Connecting Flic buttons')
		for bd_addr in items["bd_addr_of_verified_buttons"]:
			print(bd_addr, end=' ...')
			got_button(bd_addr)
	
	# start ibeacon scanner in subprocess (To-do: wait until scanner is connected before proceeding)
	# generate practically unique message topic for pub/sub ibeacon advertisements
	topic_ID = 'ibeacon/' + uid.get_UID(length=5)
	scan_p = subprocess.Popen(['sudo', 'python', 'start_scanner.py', '--topic', topic_ID])
	
	# initialise lights bridge
	bridge = lights.Bridge(hue_uname=config.HUE_USERNAME, hue_IP=config.HUE_IP_ADDRESS, lightify_IP=config.LIGHTIFY_IP)
	
	# load flic button groups from file
	with open('flic_button_groups.json') as f:
		json_data = f.read()
	groups = json.loads(json_data)
	
	# create flic client and start in new thread
	flic_client = fliclib.FlicClient("localhost")
	logger.info('Connecting Flic buttons...')
	flic_client.get_info(got_info)
	flic_client.on_new_verified_button = got_button
	flic_thread = threading.Thread(target=flic_client.handle_events)
	flic_thread.start()
	
	# initialise daylight sensor (daylight times from sunrise-sunset.org API)
	daylight_sensor = lights.DaylightSensor(config.LATITUDE, config.LONGITUDE)
	print('Sunrise and sunset times... OK')
	
	# initialise presence sensor and register beacons
	print('Starting presence sensor...', end='')
	logger.info('Starting presence sensor...')
	presence_sensor = ibeacon.PresenceSensor(welcome_callback=welcome_home, last_one_out_callback=bye, topic=topic_ID, scan_timeout=config.SCAN_TIMEOUT)
	beacon1 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54480"}
	beacon2 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54481"}
	logger.info((presence_sensor.register_beacon(beacon1, "Richard")))
	logger.info((presence_sensor.register_beacon(beacon2, "Michelle")))
	presence_sensor.start()	# starts looping in a new thread
	print(' OK')

	# initialise lights controller (triggers timed actions)
	print('Starting light controller...', end='')
	controller = lights.Controller(bridge, config.RULES, daylight_sensor, presence_sensor)
	print(' OK')

	# initialise remote lights controller
	print('Starting remote controller...', end='')
	remote = lights.Remote(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_UNAME, config.MQTT_PWORD, bridge)
	remote.start()
	print(' OK')
	
	# initialise Sonos speakers
	print('Connecting to Sonos speakers...', end='')
	sonos = soco.discover()
	if sonos != None:
		for speaker in sonos:
			logger.info('Discovered speaker: %s' % (speaker.player_name))
		print(' OK')
	else:
		print(' No speakers found')
	
	while True:
		# loop controller to check if any actions should be triggered
		controller.loop_once()
		time.sleep(1)

if __name__ == "__main__":
	try:
		run()
	except Exception:
		print('Fatal error! (%s)' % (sys.exc_info()[1]))
		# notify IFTTT that script has crashed and reraise exception
		r = requests.get('https://maker.ifttt.com/trigger/lights_app_crashed/with/key/'+config.IFTTT_KEY)
		raise
