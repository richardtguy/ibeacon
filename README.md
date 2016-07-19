# ibeacon
Presence monitoring using iBeacons and Raspberry Pi to control smart lights at home.

##Overview
The goal of this project was to implement a practical system to switch on the Philips Hue lights in our house when either my girlfriend or I get home, and switch them off again when we're out.

Although this can be done using the Philips Hue mobile app and 3rd-party services like IFTTT, they can be slow to respond (we've fumbled for the lightswitch in the dark for a while before the IFTTT app on my phone finally connected to the wifi and realised we're home) and neither really cope with the concept that more than one person might live in the same household (without some pretty ugly hacking).

A more practical and elegant solution is to use [bluetooth beacon key fobs](https://www.beaconzone.co.uk/ibeacon/PC037-E) I picked up for £11 each.  In this project, I've used a Raspberry Pi 3 with a Bluetooth LE USB dongle (the built-in bluetooth controller is busy [managing the flic buttons we use as manual light switches](https://github.com/richardtguy/flic-hue)...) to listen for the advertisment packets from the beacons, and so keep track of who's at home.  If it hasn't heard from either beacon after a minute or so, it switches all the lights off - simple!

We like to change the lighting scenes depending on the time of day (warm whites in the evening, cooler shades during the day).  In order to control the lights based on whether or not we're at home and sunrise and sunset times, I needed to expand the basic interface to the Hue bridge I implemented for the flic buttons.  This code runs on the Rasberry Pi and controls the lights directly via the API on the Hue bridge based on a set of rules defined read from a file on startup.  Now we can schedule lights to come on at certain times, but only if there's someone home.  And when we get home the lights come on in the appropriate scene for the time of day.

The project is implemented using Python (and a shell script adapted from one I found [here](http://developer.radiusnetworks.com/ibeacon/idk/ibeacon_scan) by Radius Networks to parse the beacon advertisement packets).  The Python classes are documented below.

Potential improvements:
- It  might be possible to integrate the presence sensor directly with the Hue bridge, so that rules implemented on the bridge itself could be aware of whether there's anyone home.  This would avoid having to run a controller to execute daily lighting schedules on the Pi.
- Battery life of the beacons is likely to be an issue (<12 months), with unreliable detection when they get low leading to the lights cycling on and off...  I'll experiment with the advertisement frequency and the length of time to scan for beacons - higher frequency means more responsive and reliable detection, but shorter battery life.  Beacons are also available that broadcast their own battery level - I might implement a notification by email when they need a new battery.

##Usage
- Start MQTT message broker on `localhost` (OSX: `/usr/local/sbin/mosquitto`, Linux: `sudo /etc/init.d/mosquitto start`)

- Start scanning for ibeacon advertisements.
`$ sudo python start_scanner.py`

- An example implementation, including use of daylight and timer rules and a presence sensor, is included in `controller.py`
`$ python controller.py`

##Documentation

###class ibeacon.Scanner(*IP='localhost', port='1883', hci='hci0'*)
On Linux the `hcitools` command `lescan` is used to start scanning for bluetooth packets (using the `--duplicates` option to catch repeated advertisements from the same beacons).  The script then runs `hcidump --raw`, and pipes the output through a bash script that parses the raw stream into ibeacon advertisements in JSON format.  The scanner publishes the adverts to an MQTT message broker on the topic `ibeacon/adverts`.  The IP address and port of the broker, which may be supplied as arguments, default to `localhost:1883`.  An experimental binary is provided on OSX to scan and parse the packets into the same format, but response times are currently much slower than on Linux. 

####ibeacon.Scanner.scan_forever()
Start the scanner by calling the method `scan_forever()`.  This method is blocking.

###class ibeacon.PresenceSensor(*first_one_in_callback=None, last_one_out_callback=None, IP='localhost', port='1883', scan_timeout=60*)
The `PresenceSensor` class provides a simple API to query whether the house is currently occupied, based on whether advertisement packets have recently been received from registered iBeacons associated with each member of the household.  The `query()` method returns `True` if the house is occupied (i.e. if any of the registered beacons are present), or `False` if none of the registered beacons have been detected for longer than the specified timeout.

The PresenceSensor subscribes to the `ibeacon/adverts` topic to receive ibeacon advertisements from the Scanner object via n MQTT message broker.  The IP address and port for the broker may be supplied as arguments.

In addition, callback functions `PresenceSensor.last-one-out` and `PresenceSensor.first-one-in` may be specified.  When the house is occupied, PresenceSensor.last_one_out is called when none of the registered beacons have been detected for longer than the specified `scan_timeout` in seconds, and the first-one-in callback is called immediately when the first registered beacon is subsequently detected.

####ibeacon.PresenceSensor.query()
Return True is house is occupied, False if none of the registered beacons have been detected for more than `self.scan_timeout` seconds (default = 60 seconds).

####ibeacon.PresenceSensor.register_beacon(*beacon, owner*)
Add a beacon to the list of registered beacons in the household, by supplying the IDs of a new beacon as a dictionary with keys `UUID`, `MajorID` & `MinorID` and the owner of the beacon as a string.

####ibeacon.PresenceSensor.deregister_beacon(*beacon*)
Remove the given beacon from the list of registered beacons in the household.

###class hue.DaylightSensor(*lat, lng*)
The DaylightSensor class provides a simple API to query whether a time supplied as an argument is within daylight hours. On initialisation, the constructor method queries the [sunrise-sunset.org](http://www.sunrise-sunset.org) API to obtain the sunset and sunrise times (UTC) for today at the location specifided by the latitute and longitude coordinates supplied as arguments.  The daylight times are updated every 24 hours.

####hue.DaylightSensor.query(*time*)
The argument `time` should be supplied as a `datetime` object in UTC (defaults to now if omitted).  If it has been more than 24 hours since daylight times were last refreshed from [sunrise-sunset.org](http://www.sunrise-sunset.org), these are refreshed.  Then returns `True` if the date supplied as an argument is during daylight hours, `False` otherwise.


HueLight, HueBridge, and HueController classes are implemented to provide a simplified interface to the [Philips Hue API](http://www.developers.meethue.com/philips-hue-api).

###class hue.HueLight(*name, ID*)
The HueLight class represents a single lamp connected to the bridge.  Instances of the HueLight class may be created and used seperately or (more conveniently) created for each light stored in the bridge by the constructor of a HueBridge object.  Various methods are implemented in order to control the lamp.

####hue.HueLight.on()
Switches the lamp on.  (Colour, brightness and other settings are unaffected.)

####hue.HueLight.off()
Switches the lamp off.  (Colour, brightness and other settings are unaffected.)

####hue.HueLight.dim()
Switches the lamp on and adjusts the brightness to a minimum setting.

####hue.HueLight.save_state()
Saves the current status of the lamp returned from the bridge into `self.state`.  May be used to e.g. reset lamp back to its previous on/off state after recalling a scene.  After calling this method `self.state['on']` is `True` if lamp was on, `False` if lamp was off when the method was called.

###class hue.HueBridge(*username, IP*)
Implements a simplified API for controlling lights connected to a Philips Hue bridge.  The constructor queries the bridge to obtain a list of connected lights.  These are stored in a dictionary self.lights, with light names as keys and corresponding HueLight objects as values.

A whitelisted username on the bridge, and the IP address of the bridge must be supplied as arguments.

Various methods are available to interact with the bridge and connected lights.  Lights can be accessed individually by name in HueBridge.lights, or collectively by iterating over the bridge.  E.g. to switch off all lights connected to the bridge, simply use:
```python
for light in bridge:
	light.off()
```

####hue.HueBridge.get(light_name)
Returns the HueLight object with the corresponding name `light_name`.  The light can then e.g. be switched on using `HueBridge.get(light_name).get().on()`.

####hue.HueBridge.recall\_scene(scene\_id)
Recalls a scene stored on the bridge with the given id.  Note that the scene is applied to all lamps connected to the bridge, and current on/off states are preserved.

###class hue.HueController(*bridge, rules, daylight_sensor, presence_sensor=None*)
The HueController class controls light settings based on a set of rules.  `bridge` and `daylight_sensor` objects must be passed as arguments when the HueController instance is created.  Optionally a `presence_sensor` object may be passed to make the bridge aware of whether or not anyone is home.  

The bridge should be a `hue.HueBridge` object connected to an actual Hue bridge.  Implementation details of the daylight and presence sensors are unimportant, but both should expose a `query()` method that returns True during hours of daylight and False at night for the daylight sensor and True if the house is occupied, False if not for the presence sensor. 

A single method is implemented as interface to the HueController.  Call the `loop_once()` method periodically to implement any rules for which the trigger time has been passed since the last call to `loop_once()`.  The class handles conversion between trigger times specified in local (UK) time and system time.

####hue.HueController.loop_once()
Action any rules for which the trigger time has passed since the last call to `loop_once()`.  Call this method periodically in a loop.

###Rules
Rules for triggering actions are read from a JSON formatted file when the HueController object is constructed.  The path to the file must be passed to the HueController object as an argument. No checking of the format or content of the rules is performed.

| Field | Description |
|:---|:---|
| `trigger` | Either `daylight` in which case the action is triggered at sunrise or sunset, or `timer` where the action is triggered at a specified time. |
| `time` | If `trigger` is set to `daylight`, `time` should be either sunrise or sunset.  The local sunrise/sunset times are obtained from the DaylightSensor object passed to the HueController. If the `trigger` is `timer`, then a local (UK) time should be specified in HH:MM format.|
| `action` | `on`/`off` to switch selected lights on or off at the specified time, or `scene` to recall a scene on the bridge. |
| `lights` (required if `action` is `on` or `off`) | The specified action is applied to the lights listed by name.  E.g. `["Hall 1", "Hall 2"]` Specifying an empty list `[]` applies the rule to all lights connected to the bridge. |
| `scene` (required if `action` is `scene`) | The id of the scene stored on the bridge to be recalled. | 
| `days` (optional) | Days of the week on which to apply rule supplied as a bitmask i.e. 1111100 for weekdays. |

The example rule below is applied only on Wednesdays, and switches all lights connected to the bridge on at sunset.

```json
{
	"1": {
		"trigger": "daylight",
		"time": "sunset",
		"action": "on",
		"lights": [],
		"days": "0010000"
	}
}
```

