# jubilee-lights
Control smart lights at home using a Raspberry Pi with bluetooth buttons, presence monitoring, timers and daylight rules, and remote (internet) control.

##Overview
This project implements a practical system to control the Philips Hue and Osram Lightify lights in our house using a Raspberry Pi 3 running Raspbian.  Key features include:
- *Bluetooth buttons*: Switch groups of lights on or off using Flic bluetooth buttons.
- *Presence monitoring*: Use bluetooth beacon key fobs to switch the lights on when either of us gets home, and switch them off again when we're out.
- *Timers*: Switch lights on, off and recall scenes at set times of the day.
- *Daylight*: Switch lights on, off and recall scenes at sunrise or sunset.

I've used [Flic bluetooth buttons from Shortcut Labs](https://flic.io).  Server and client libraries for Linux are available [here](https://github.com/50ButtonsEach/fliclib-linux-hci).  Verified buttons communicate with a Raspberry Pi via a server application which passes click events to a client.  The client application switches lights on or off depending on the click type (single click or hold).  Buttons are associated with groups of lights as defined in a JSON formatted file `flic_button_groups.json`.

For the presence monitoring, I've used a Raspberry Pi 3 with a Bluetooth LE USB dongle to listen for the advertisment packets from some [bluetooth beacon key fobs](https://www.beaconzone.co.uk/ibeacon/PC037-E), and so keep track of who's at home.  If it hasn't heard from either beacon after five minutes, it switches all the lights off.

We like to change the lighting scenes depending on the time of day (warm whites in the evening, cooler shades during the day).  In order to control the lights based on whether or not we're at home and sunrise and sunset times, I implemented an interface to the Hue bridge and Lightify Gateway.  This code controls the lights based on a set of rules read from a file on startup.  The Raspberry Pi communicates with the Hue Bridge via the [official API](http://www.developers.meethue.com/philips-hue-api), and with the Lightify Gateway via the binary protocol documented very unofficially [here](http://sarajarvi.org/lightify-haltuun/en.php).

We can schedule lights to come on at certain times, but only if there's someone home.  And when we get home the lights come on in the appropriate scene for the time of day.

The project is implemented using Python 3 (and a shell script adapted from one I found [here](http://developer.radiusnetworks.com/ibeacon/idk/ibeacon_scan) by Radius Networks to parse the beacon advertisement packets).  The Python classes are documented below.

##Example usage
- Start MQTT message broker on `localhost` (OSX: `/usr/local/sbin/mosquitto`, Linux: `sudo /etc/init.d/mosquitto start`)

- Start Flic button server: `sudo ./flicd -f flic.sqlite3`

- An example implementation, including use of daylight and timer rules, Flic buttons, a presence sensor, and remote control, is included in `run.py`.  Run this in a new terminal.
`$ sudo python run.py`

Note that, depending on which features you're using, various configuration parameters are required.  In the example, these are supplied in a configuration file, `config.py`.

##Documentation

###class jubilee.ibeacon.Scanner(*IP='localhost', port='1883', hci='hci0'*)
On Linux the `hcitools` command `lescan` is used to start scanning for bluetooth packets (using the `--duplicates` option to catch repeated advertisements from the same beacons).  The script then runs `hcidump --raw`, and pipes the output through a bash script that parses the raw stream into ibeacon advertisements in JSON format.  The scanner publishes the adverts to an MQTT message broker on the topic `ibeacon/adverts`.  The IP address and port of the broker, which may be supplied as arguments, default to `localhost:1883`.  An experimental binary is provided on OSX to scan and parse the packets into the same format, but response times are currently much slower than on Linux. 

####jubilee.ibeacon.Scanner.scan\_forever()
Start the scanner by calling the method `scan_forever()`.  This method is blocking, so should typically be run in a separate thread.

###class jubilee.ibeacon.PresenceSensor(*first\_one\_in\_callback=None, last\_one\_out\_callback=None, IP='localhost', port='1883', scan\_timeout=300*)
The PresenceSensor subscribes to the `ibeacon/adverts` topic to receive ibeacon advertisements from the Scanner object via an MQTT message broker.  The IP address and port for the broker may be supplied as arguments, or default to port 1883 on the localhost.

The `PresenceSensor` class provides a simple API to query whether members of the household are currently in or out, based on whether advertisement packets have recently been received from registered iBeacons associated with each member of the household.  The `query(beacon_owner)` method returns `True` if `beacon_owner` is in, or `False` if the iBeacon registered to them has not been detected for longer than the specified timeout.  The `query()` may also be called without any arguments.  In this case, it returns `True` if any of the registered members of the household are present, or `False` if no-one is home.

In addition, callback functions `PresenceSensor.last_one_out` and `PresenceSensor.welcome` may be specified.  When the house is occupied, `PresenceSensor.last_one_out` is called if none of the registered beacons have been detected for longer than the specified `scan_timeout` in seconds.  The `welcome_back` callback is called immediately when a registered beacon is detected after a period of longer than the specified timeout (i.e. the owner has returned after a period of absence).

####jubilee.ibeacon.PresenceSensor.query(*beacon_owner*)
Returns True if the iBeacon registered to `beacon_owner` has not been detected for more than `self.scan_timeout` seconds (default=300 seconds).  If no argument is supplied, `query()` returns True if house is occupied, False if none of the registered beacons have been detected for more than the specified timeout.

####jubilee.ibeacon.PresenceSensor.register_beacon(*beacon, owner*)
Add a beacon to the list of registered beacons in the household, by supplying the IDs of a new beacon as a dictionary with keys `UUID`, `MajorID` & `MinorID` and the owner of the beacon as a string.

####jubilee.ibeacon.PresenceSensor.deregister_beacon(*beacon*)
Remove the given beacon from the list of registered beacons in the household.

###class jubilee.lights.DaylightSensor(*lat, lng*)
The DaylightSensor class provides a simple API to query whether a time supplied as an argument is within daylight hours. On initialisation, the constructor method queries the [sunrise-sunset.org](http://www.sunrise-sunset.org) API to obtain the sunset and sunrise times (UTC) for today at the location specifided by the latitute and longitude coordinates supplied as arguments.  The daylight times are updated every 24 hours.

####jubilee.lights.DaylightSensor.query(*time*)
The argument `time` should be supplied as a `datetime` object in UTC (defaults to now if omitted).  If it has been more than 24 hours since daylight times were last refreshed from [sunrise-sunset.org](http://www.sunrise-sunset.org), these are refreshed.  Then returns `True` if the date supplied as an argument is during daylight hours, `False` otherwise.


Bridge, Controller and Remote classes are implemented to provide a simplified interface to the Philips Hue and Osram Lightify lamps.  Colour, brightness and other settings are saved locally as scenes and pushed to each lamp by calling its `on()` method.  HueLight and LightifyLight objects handle the detailed implementation of the two protocols, and provide a common API.

###class jubilee.lights.HueLight(*name, ID, UID=None*)
The HueLight class represents a single lamp connected to the bridge and handles details of the HTTP REST API used to communicate with the Hue Bridge.

Instances of the HueLight class may be created and used separately or (more conveniently) created for each light stored in the bridge by the constructor of a Bridge object.  Various methods are implemented in order to control the lamp.  If no unique ID (UID) is supplied, a new one is created using the function uid.get\_UID().  UIDs are used rather than names to keep track of lights in scenes in order to avoid problems if there are Philips and Osram lights with the same name connected to the same Bridge object.

####jubilee.lights.HueLight.on(*transition=4*)
Switches the lamp on to the most recently saved settings for colour and brightness. Specify the transition time in units of 0.1 seconds.

####jubilee.lights.HueLight.off(*transition=4*)
Switches the lamp off.

####jubilee.lights.HueLight.dim()
Switches the lamp on and adjusts the brightness to a minimum setting.

####jubilee.lights.HueLight.save\_state()
Gets the current colour, brightness and other settings for the lamp from the bridge and saves to the instance variable self.\_\_state.

####jubilee.lights.HueLight.update\_state(*state*)
Saves the state object supplied as an argument to the instance variable self.\_\_state.  May be used to e.g. set the lamp settings when recalling a scene.  The syntax for the state object is manufacturer-dependent, so it is best always to retrieve this by calling Huelight.save\_state() with the lamp already set to the desired settings.

###class jubilee.lightify.LightifyLight(*addr, host, name=None, port=4000, uid=None*)
The my\_lightify.LightifyLight class has an identical API, and handles details of the proprietary binary protocol used to communicate with the Gateway.

###class jubilee.lights.Bridge(*username, IP*)
Implements a simplified API for controlling lights connected to a Hue bridge and/or Osram Lightify Gateway.  The constructor loads details of saved lights from a file `saved_lights.json` or, if this file is not present, queries the bridge and/or gateway to obtain a new list of connected lights.  These are stored in a dictionary `self.lights`, with light names as keys and corresponding HueLight or LightifyLight objects as values.

For the Philips Hue Bridge, a whitelisted username on the bridge, and the IP address of the bridge must be supplied as arguments.  For the Osram Lightify Gateway, the IP address of the gateway must be supplied.  Both must be connected to the local network.

Various methods are available to interact with the bridge and connected lights.  Lights can be accessed individually by name in Bridge.lights, or collectively by iterating over the bridge.  E.g. to switch off all lights connected to the bridge, simply use:
```python
for light in bridge:
	light.off()
```

####jubilee.lights.Bridge.get(*light\_name*)
Returns the HueLight object with the corresponding name `light_name`.  The light can then e.g. be switched on using `HueBridge.get(light_name).on()`.

####jubilee.lights.Bridge.recall\_local\_scene(*scene_name, transition=4*)
Recalls a scene stored in a local file, `saved_scenes.json`.  Note that the scene is applied to all lamps connected to the bridge.  The new settings are pushed to any lights that are currently on.

####jubilee.lights.Bridge.save\_scene\_locally(*scene_name*)
Saves the current settings of all lights to a local file `saved_scenes.json`.

###class jubilee.lights.Controller(*bridge, rules, daylight\_sensor, presence\_sensor=None*)
The Controller class controls light settings based on a set of rules.  `bridge` and `daylight_sensor` objects must be passed as arguments when the HueController instance is created.  Optionally a `presence_sensor` object may be passed to make the controller aware of whether or not anyone is home.  

The bridge should be a `jubilee.lights.Bridge` object.  Implementation details of the daylight and presence sensors are unimportant, but both should expose a `query()` method that returns True during hours of daylight and False at night for the daylight sensor and True if the house is occupied, False if not for the presence sensor. 

A single method is implemented as interface to the Controller.  Call the `loop_once()` method periodically to implement any rules for which the trigger time has been passed since the last call to `loop_once()`.  The class handles conversion between trigger times specified in local (UK) time and system time.

####jubilee.lights.Controller.loop\_once()
Action any rules for which the trigger time has passed since the last call to `loop_once()`.  Call this method periodically in a loop.

###class jubilee.lights.Remote(*host, port, uname, pword, bridge, topic='lights'*)
The jubilee.lights.Remote class implements a very simple interface to control the lights via the internet by connecting to a cloud-based MQTT message broker (e.g. [CloudMQTT](https://www.cloudmqtt.com)).  The Remote object connects to the MQTT broker using the supplied credentials and subscribes to the supplied topic.  It then parses messages received using the syntax for rules as described below.  Valid actions are 'on', 'off' or 'scene', and lists of light names may be supplied (or an empty list `[]` for all lights).  Of course, a separate client application is needed to publish action messages via the message broker.  I used [IoT MQTT Dashboard](https://play.google.com/store/apps/details?id=com.thn.iotmqttdashboard&hl=en_GB) for testing.

####jubilee.lights.Remote.start()
In a new thread, connect to the MQTT message broker, listen for new messages and handle actions.

####jubilee.lights.Remote.stop()
Disconnect from the MQTT message broker.


###Rules
Rules for triggering actions are read from a JSON formatted file when the Controller object is constructed.  The path to the file must be passed to the Controller object as an argument. No checking of the format or content of the rules is performed.

| Field | Description |
|:---|:---|
| `trigger` | Either `daylight` in which case the action is triggered at sunrise or sunset, or `timer` where the action is triggered at a specified time. |
| `time` | If `trigger` is set to `daylight`, `time` should be either sunrise or sunset.  The local sunrise/sunset times are obtained from the DaylightSensor object passed to the HueController. If the `trigger` is `timer`, then a local (UK) time should be specified in HH:MM format.|
| `action` | `on`/`off` to switch selected lights on or off at the specified time, or `scene` to recall a scene on the bridge. |
| `transition` (optional) | The time over which the lights should fade on or off, in 1/10th seconds. |
| `lights` (required if `action` is `on` or `off`) | The specified action is applied to the lights listed by name.  E.g. `["Hall 1", "Hall 2"]` Specifying an empty list `[]` applies the rule to all lights connected to the bridge. |
| `scene` (required if `action` is `scene`) | The id of the scene stored on the bridge to be recalled. | 
| `days` (optional) | Days of the week on which to apply rule supplied as a bitmask i.e. 1111100 for weekdays. |

The example rule below is applied only on Wednesdays, and switches all lights connected to the bridge on at sunset, over a period of 30 seconds.

```json
{
	"1": {
		"trigger": "daylight",
		"time": "sunset",
		"action": "on",
		"transition": 300,
		"lights": [],
		"days": "0010000"
	}
}
```

Actions handled by the remote control (received as messages from the MQTT broker) use a similar syntax.  The example below switches off the kitchen table light.

```json
{
	"action" : {
		"action": "off",
		"lights": ["Kitchen table"]
	}
}
```





