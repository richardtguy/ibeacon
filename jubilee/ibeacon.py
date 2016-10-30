# Built-in modules
import time
import datetime
import json
import threading
import os
import signal
import sys
import subprocess
import logging

# Installed modules
import paho.mqtt.client as mqtt

# Package modules
from . import timeout

__version__ = '1.2.0'

logger = logging.getLogger(__name__)

DEVNULL = open(os.devnull, 'wb')	# /dev/null
PLATFORM = os.uname()[0]

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
	
	def __init__(self, welcome_callback=None, last_one_out_callback=None, hci='hci0', scan_timeout=datetime.timedelta(seconds=300)):
		self.hci = hci
		self.scan_timeout = scan_timeout
		# set callback functions (if supplied as arguments)
		self.welcome_callback = welcome_callback
		self.last_one_out_callback = last_one_out_callback
		
		self.registered_beacons = []
		
		# thread lock
		self.lock = threading.Lock()
			
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
		self.on = True

		# start ibeacon scanner in subprocess and read output (blocking, so new thread)
		self.scan_thread = threading.Thread(target=self._scanner)
		self.scan_thread.start()

		# start loop for presence sensor in new thread
		self.thread = threading.Thread(target=self._loop)
		self.thread.start()

	def stop(self):
		logger.info("Stopping Presence Sensor...")
		self.on = False
		self.scan_thread.join()
		self.thread.join()
		logger.debug("Presence Sensor stopped")

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

	def _scanner(self):
		# start scanning for bluetooth packets in subprocess
		logger.debug("Starting scan...")
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
			message = self.parse_p.stdout.readline()
			self._handle_message(message)
	
	def _loop(self):
		logger.debug("Starting loop...")
		while self.on:
			# if each beacon not seen for > SCAN_TIMEOUT then set 'in' to False. Call 
			# last_one_out_callback() first time no beacons found after timeout.
			now = datetime.datetime.now()
			beacons_found = 0
			with self.lock:
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
	
	def _handle_message(self, message):
		# parse beacon IDs from message and fetch beacon from registered list
		msg = json.loads(message.decode('utf-8'))
		beacon_ID = {}
		for key in PresenceSensor.BEACON_ID_KEYS:
			beacon_ID[key] = msg[key]
		beacon = self._get_beacon(beacon_ID)
		# if beacon is registered
		if (beacon != None):
			# update last seen datetime and set 'in' to True
			with self.lock: beacon['last_seen'] = datetime.datetime.now()
			logger.debug("Beacon %s seen at %s" % (beacon['ID'], beacon['last_seen'].strftime('%Y-%m-%d %H:%M:%S')))
			if beacon['in'] == False:
				beacon['in'] = True
				self.welcome_callback(beacon['owner'])

	def _get_beacon(self, beacon):
		for b in self.registered_beacons:
			if b['ID'] == beacon:
				return b
		return None
