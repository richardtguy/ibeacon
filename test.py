#!/usr/local/bin/python3

# import built-in modules
import datetime, time, threading, signal, sys, random, subprocess, logging, json
# import installed modules
import requests
# import local modules
from jubilee import presence, lights, uid
import config, fliclib

if __name__ == "__main__":
	# set up logging
	logger = logging.getLogger(__name__)
	try:
		logging_level = sys.argv[1].upper()
	except IndexError:
		logging_level = 'INFO'
	logging.basicConfig(
		filename='test.log',
		level=logging_level,
		format='%(asctime)-12s | %(levelname)-8s | %(name)s | %(message)s',
		datefmt='%d/%m/%y, %H:%M:%S'
	)
	

	# initialise lights bridge
	lightify = lights.LightifyGateway(config.LIGHTIFY_IP)
	lightify.all_on()
	time.sleep(2)
	lightify.all_off()
	time.sleep(2)
	lightify.all_on()
		