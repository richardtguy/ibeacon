import hue, config, time

print('Testing initialise connection to Lightify Gateway')
bridge = hue.Bridge(lightify_uname=config.LIGHTIFY_USERNAME, lightify_pword=config.LIGHTIFY_PASSWORD, lightify_serial=config.LIGHTIFY_SERIAL)

#bridge.save_scene_locally('daytime')
bridge.recall_local_scene('evening')
time.sleep(2)
bridge.recall_local_scene('daytime')

