# Built-in modules
import time, datetime, json, threading, os, signal, sys, subprocess, logging
from io import StringIO

# Installed modules
import paho.mqtt.client as mqtt

# Local modules
import timeout

__version__ = '1.0.1+'

logger = logging.getLogger(__name__)

DEVNULL = open(os.devnull, 'wb')	# /dev/null
PLATFORM = os.uname()[0]

class Scanner():
	"""
	Scan for ibeacon avertisement packets and publish to MQTT message broker
	Binaries and scripts are provided for linux (using bluez stack) or mac osx
	"""
	def __init__(self, IP='localhost', port=1883, hci='hci0', topic='ibeacon/adverts'):
		self.IP = IP
		self.port = port
		self.hci = hci
		self.topic = topic
				
		# create MQTT client
		self.mqttc = mqtt.Client()
		self.mqttc.on_connect = self._on_connect
		self.mqttc.on_disconnect = self._on_disconnect
		
		# signal handler to catch Ctrl-C
		signal.signal(signal.SIGINT, self._exit_handler)
		
	def scan_forever(self):		
		logger.info("Starting iBeacon scanner...")
		self.on = True

		# connect to message broker
		self.mqttc.connect(self.IP, self.port, keepalive=300)
		
		# start scanning for bluetooth packets in subprocess
		if os.uname()[0] == 'Linux':
			self.lescan_p = subprocess.Popen(['sudo', 'hcitool', '-i', self.hci, 'lescan', '--duplicates'], stdout=DEVNULL, stderr=DEVNULL)

		# start subprocesses in shell to dump and parse raw bluetooth packets		
		if PLATFORM == 'Linux':
			logger.debug("Running on Linux...")
			hcidump_args = ['hcidump', '--raw', '-i', self.hci]
			parse_args = ['./ibeacon_parse.sh']
			self.hcidump_p = subprocess.Popen(hcidump_args, stdout=subprocess.PIPE, stderr=DEVNULL)
			self.parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stdin=self.hcidump_p.stdout, stderr=DEVNULL)

		elif PLATFORM == 'Darwin':
			logger.debug("Running on OSX...")
			parse_args = ['./ibeacon_scan']
			self.parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stderr=DEVNULL)
		else:
			logger.error("Platform not supported")

		while self.on:
			# read next ibeacon advertisement packet (blocking if nothing to read)
			try:
				advert = self._readline()
				# publish ibeacon advertisement to MQTT broker
				self.mqttc.publish(self.topic, advert)
			except timeout.TimeoutException:
				pass
			self.mqttc.loop()			
	
	@timeout.timeout(30)	
	def _readline(self):
		# blocks if no advert available to read, so wrap with timeout to ensure MQTT client loop is called regularly
		advert = self.parse_p.stdout.readline()
		return advert
	
	def _on_connect(self, client, userdata, flags, rc):
		logger.info("Scanner connected to message broker with result code " + str(rc))
		logger.info("Publishing to %s" % (self.topic))
			
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			logger.warning('Unexpected disconnection! (%s)' % (rc))
			time.sleep(5)
			logger.warning('Reconnecting scanner...')
			self.mqttc.reconnect()
		else:
			logger.info('Scanner disconnected from message broker')		
	
	def _stop(self):
		logger.info('Stopping scanner...')
		self.on = False
		self.mqttc.disconnect()
		if PLATFORM == 'Linux':
			self.lescan_p.terminate()
			self.hcidump_p.terminate()
			self.lescan_p.wait()
			self.hcidump_p.wait()
		self.parse_p.terminate()
		self.parse_p.wait()
		logger.info('Scanner stopped')
	
	def _exit_handler(self, signal, frame):
		self._stop()
		sys.exit(0)


class PresenceSensor():
	"""
	Implement a sensor to monitor if house is occupied using iBeacon key fobs
	- An instance of Scanner object must be started with scan_forever() first to publish 
	  ibeacon advertisement packlets to MQTT message broker.
	- PresenceSensor then subscribes
	  to the topic ibeacon/adverts and keeps track of which beacons have been detected 
	  recently.
	- Callback functions may be set for last-one-out and welcome events.
	- PresenceSensor.query(beacon_owner) method returns True if beacon registered to
	  beacon_owner is found, False otherwise
	"""
	# define required iBeacon ID keys
	BEACON_ID_KEYS = ("UUID", "Major", "Minor")
	
	def __init__(self, welcome_callback=None, last_one_out_callback=None, IP='localhost', port=1883, topic='ibeacon/adverts', scan_timeout=datetime.timedelta(seconds=300)):
		self.IP = IP
		self.port = port
		self.scan_timeout = scan_timeout
		self.topic = topic
		
		# set callback functions (if supplied as arguments)
		self.welcome_callback = welcome_callback
		self.last_one_out_callback = last_one_out_callback
		
		self.registered_beacons = []

		# initialise MQTT client
		self.mqttc = mqtt.Client()
		self.mqttc.on_connect = self._on_connect
		self.mqttc.on_disconnect = self._on_disconnect		
		self.mqttc.on_message = self._message_handler
			
	def register_beacon(self, beacon, owner):
		# add beacon to list of registered beacons
		for key in PresenceSensor.BEACON_ID_KEYS:
			if key not in list(beacon.keys()): 
				return "Failed to register beacon (missing or invalid ID)"
		if self._get_beacon(beacon) == None:
			self.registered_beacons.append({"owner": owner, "ID": beacon, "last_seen": datetime.datetime.now(), "in": False})
			return "Registered beacon %s to owner %s" % (beacon, owner)

	def deregister_beacon(self, beacon):
		self.registered_beacons.remove(self._get_beacon(beacon))
		return "Deregistered beacon %s" % (beacon)

	def start(self):
		logger.info("Starting Presence Sensor...")
		self.mqttc.connect(self.IP, port=self.port)
		self.on = True
		# start non-blocking loop for presence sensor
		self.thread = threading.Thread(target=self._loop)
		self.thread.start()
	
	def stop(self):
		logger.info("Stopping Presence Sensor...")
		self.on = False
		self.thread.join()
		# disconnect client object from MQTT server
		self.mqttc.disconnect()

	def query(self, beacon_owner=None):
		if beacon_owner is None:
			occupied = False
			for b in self.registered_beacons:
				if b['in']: occupied = True
			return occupied
		else:
			for b in self.registered_beacons:
				if b['owner'] == beacon_owner:
					return b['in']
	
	def _loop(self):
		while self.on:
			# loop MQTT client once (blocking) to periodically check for messages
			self.mqttc.loop()
			# if each beacon not seen for > SCAN_TIMEOUT then set 'in' to False. Call 
			# last_one_out_callback() first time no beacons found after timeout.
			now = datetime.datetime.now()
			beacons_found = 0
			for b in self.registered_beacons:
				if now - b['last_seen'] > self.scan_timeout:
					if b['in']: logger.info(('[%s] Bye %s!' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), b['owner'])))
					b['in'] = False
				else:
					beacons_found += 1
			if (beacons_found == 0) and (beacons_found_last_loop > 0):
					self.last_one_out_callback()
			beacons_found_last_loop = beacons_found
			time.sleep(0.1)

	def _on_connect(self, client, userdata, flags, rc):
		logger.info(("Presence Sensor connected to message broker with result code " + str(rc)))
		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		logger.info(('Subscribing to %s' % (self.topic)))
		self.mqttc.subscribe(self.topic)
		
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			logger.warning('Unexpected disconnection! (%s)' % (rc))
		logger.info('Presence Sensor disconnected from message broker')		
	
	def _message_handler(self, client, userdata, message):
		# parse beacon IDs from message and fetch beacon from registered list
		msg = json.loads(message.payload.decode('utf-8'))
		beacon_ID = {}
		for key in PresenceSensor.BEACON_ID_KEYS:
			beacon_ID[key] = msg[key]
		beacon = self._get_beacon(beacon_ID)
		# if beacon is registered
		if (beacon != None):
			# update last seen datetime and set 'in' to True
			beacon['last_seen'] = datetime.datetime.now()
			logger.debug("Beacon %s seen at %s" % (beacon['ID'], beacon['last_seen'].strftime('%Y-%m-%d %H:%M:%S')))
			if beacon['in'] == False:
				beacon['in'] = True
				self.welcome_callback(beacon['owner'])

	def _get_beacon(self, beacon):
		for b in self.registered_beacons:
			if b['ID'] == beacon:
				return b
		return None
