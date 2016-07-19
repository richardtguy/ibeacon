# Built-in modules
import time, datetime, json, threading, os, signal, sys, subprocess

# Installed modules
import paho.mqtt.client as mqtt

# Local modules
import timeout

__version__ = '1.0.1'

DEVNULL = open(os.devnull, 'wb')	# /dev/null
PLATFORM = os.uname()[0]

class Scanner():
	"""
	Scan for ibeacon avertisement packets and publish to MQTT message broker
	Binaries and scripts are provided for linux (using bluez stack) or mac osx
	"""
	def __init__(self, IP='localhost', port='1883', hci='hci0'):
		self.IP = IP
		self.port = port
		self.hci = hci
				
		# create MQTT client
		self.mqttc = mqtt.Client()
		self.mqttc.on_connect = self._on_connect
		self.mqttc.on_disconnect = self._on_disconnect
		
		# signal handler to catch Ctrl-C
		signal.signal(signal.SIGINT, self._exit_handler)
		
	def scan_forever(self):		
		print("Starting iBeacon scanner, press [Ctrl+C] to exit.")
		self.on = True

		# connect to message broker
		self.mqttc.connect(self.IP, self.port, keepalive=30)
		
		# start scanning for bluetooth packets in subprocess
		if os.uname()[0] == 'Linux':
			self.lescan_p = subprocess.Popen(['sudo', 'hcitool', '-i', self.hci, 'lescan', '--duplicates'], stdout=DEVNULL)

		# start subprocesses in shell to dump and parse raw bluetooth packets		
		if PLATFORM == 'Linux':
			print("Running on Linux...")
			hcidump_args = ['hcidump', '--raw', '-i', self.hci]
			parse_args = ['./ibeacon_parse.sh']
			self.hcidump_p = subprocess.Popen(hcidump_args, stdout=subprocess.PIPE)
			self.parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stdin=self.hcidump_p.stdout, stderr=DEVNULL)

		elif PLATFORM == 'Darwin':
			print("Running on OSX...")
			parse_args = ['./ibeacon_scan']
			self.parse_p = subprocess.Popen(parse_args, stdout=subprocess.PIPE, stderr=DEVNULL)
		else:
			print("Platform not supported")

		while self.on:
			# read next ibeacon advertisement packet (blocking if nothing to read)
			try:
				advert = self._readline()
				# publish ibeacon advertisement to MQTT broker
				self.mqttc.publish("ibeacon/adverts", advert)
			except timeout.TimeoutException:
				pass
			self.mqttc.loop()			
	
	@timeout.timeout(10)	
	def _readline(self):
		# blocks if no advert available to read, so wrap with timeout to ensure MQTT client loop is called regularly
		advert = self.parse_p.stdout.readline()
		return advert
	
	def _on_connect(self, client, userdata, flags, rc):
		print("Connected to message broker with result code " + str(rc))
			
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			print('Unexpected disconnection! (%s)' % (rc))
			time.sleep(5)
			print('Reconnecting...')
			self.mqttc.reconnect()
		else:
			print('Disconnected from message broker')		
	
	def _stop(self):
		print('Stopping scanner...')
		self.on = False
		self.mqttc.disconnect()
		if PLATFORM == 'Linux':
			self.lescan_p.terminate()
			self.hcidump_p.terminate()
			self.lescan_p.wait()
			self.hcidump_p.wait()
		self.parse_p.terminate()
		self.parse_p.wait()
		print('Stopped')
	
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
	- Callback functions may be set for last-one-out and first-one-in events.
	- PresenceSensor.query() method returns True if one or more registered beacons is 
	  found, False otherwise
	"""
	# define required iBeacon ID keys
	BEACON_ID_KEYS = ("UUID", "Major", "Minor")
	
	def __init__(self, first_one_in_callback=None, last_one_out_callback=None, IP='localhost', port='1883', scan_timeout=datetime.timedelta(seconds=30)):
		self.IP = IP
		self.port = port
		self.scan_timeout = scan_timeout
		
		# set callback functions (if supplied as arguments)
		self.first_one_in_callback = first_one_in_callback
		self.last_one_out_callback = last_one_out_callback
		
		self.registered_beacons = []		
		self.occupied = False

		# initialise MQTT client
		self.mqttc = mqtt.Client()
		self.mqttc.on_connect = self._on_connect
		self.mqttc.on_disconnect = self._on_disconnect		
		self.mqttc.on_message = self._message_handler
			
	def register_beacon(self, beacon, owner):
		# add beacon to list of registered beacons
		for key in PresenceSensor.BEACON_ID_KEYS:
			if key not in beacon.keys(): 
				return "Failed to register beacon (missing or invalid ID)"
		if self._get_beacon(beacon) == None:
			self.registered_beacons.append({"owner": owner, "ID": beacon, "last_seen": datetime.datetime.now()})
			return "Registered beacon %s to owner %s" % (beacon, owner)

	def deregister_beacon(self, beacon):
		self.registered_beacons.remove(self._get_beacon(beacon))
		return "Deregistered beacon %s" % (beacon)

	def start(self):
		print("Starting Presence Sensor...")
		self.mqttc.connect(self.IP, port=self.port)
		self.on = True
		# start non-blocking loop for presence sensor
		self.thread = threading.Thread(target=self._loop)
		self.thread.start()
	
	def stop(self):
		print("Stopping Presence Sensor...")
		self.on = False
		self.thread.join()
		# disconnect client object from MQTT server
		self.mqttc.disconnect()

	def query(self):
		return self.occupied
	
	def _loop(self):
		while self.on:
			# loop MQTT client (blocking) to periodically check for messages
			self.mqttc.loop()	
			# if no registered_key_fobs seen for > SCAN_TIMEOUT then set occupied = False and call last_one_out_callback()
			now = datetime.datetime.now()
			beacons_found = 0
			for b in self.registered_beacons:
				if now - b['last_seen'] < self.scan_timeout:
					beacons_found += 1
			if (beacons_found == 0) and (self.occupied):
					self.occupied = False
					self.last_one_out_callback()
			time.sleep(0.1)

	def _on_connect(self, client, userdata, flags, rc):
		print("Connected to message broker with result code " + str(rc))
		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		self.mqttc.subscribe("ibeacon/adverts")
		
	def _on_disconnect(self, client, userdata, rc):
		if rc != 0:
			print('Unexpected disconnection! (%s)' % (rc))
		print('Disconnected from message broker')		
	
	def _message_handler(self, client, userdata, message):
		# parse beacon IDs from message and fetch beacon from registered list
		msg = json.loads(message.payload)
		beacon_ID = {}
		for key in PresenceSensor.BEACON_ID_KEYS:
			beacon_ID[key] = msg[key]
		beacon = self._get_beacon(beacon_ID)
		# if beacon is registered
		if (beacon != None):
			# update last seen datetime
			beacon['last_seen'] = datetime.datetime.now()
			print("Beacon %s seen at %s" % (beacon['ID'], beacon['last_seen'].strftime('%Y-%m-%d %H:%M:%S')))
			if self.occupied == False:
				self.occupied = True
				self.first_one_in_callback()

	def _get_beacon(self, beacon):
		for b in self.registered_beacons:
			if b['ID'] == beacon:
				return b
		return None
