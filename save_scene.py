#!/usr/bin/python3

import sys
from jubilee import lights, uid
import config	

if __name__ == "__main__":
	# initialise lights bridge
	bridge = lights.Bridge(hue_uname=config.HUE_USERNAME, hue_IP=config.HUE_IP_ADDRESS, lightify_IP=config.LIGHTIFY_IP)
	
	# save current light states to scene
	bridge.save_scene_locally(sys.argv[1])
