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
	try:
		logging_level = sys.argv[1].upper()
	except NameError:
		logging_level = 'INFO'		
	logging.basicConfig(
		filename='presence.log',
		level=logging_level,
		format='%(asctime)-12s | %(levelname)-8s | %(name)s | %(message)s',
		datefmt='%d/%m/%y, %H:%M:%S'
	)
	
	
	# these functions are called by the PresenceSensor on last-one-out or first-one-in events
	def welcome_home(beacon_owner):
		logger.info('Welcome home %s!' % (beacon_owner))
	
	def bye():
		logger.info("There's no-one home, turning lights off...")

	# initialise presence sensor and register beacons
	print('Starting presence sensor...', end='')
	logger.info('Starting presence sensor...')
	presence_sensor = ibeacon.PresenceSensor(welcome_callback=welcome_home, last_one_out_callback=bye)
	beacon1 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54480"}
	beacon2 = {"UUID": "FDA50693-A4E2-4FB1-AFCF-C6EB07647825", "Major": "10004", "Minor": "54481"}
	logger.info((presence_sensor.register_beacon(beacon1, "Richard")))
	logger.info((presence_sensor.register_beacon(beacon2, "Michelle")))
	presence_sensor.start()
	print(' OK')

	time.sleep(10)
	logger.info('Stopping presence sensor...')
	presence_sensor.stop()


if __name__ == "__main__":
	run()