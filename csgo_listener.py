from http.server import BaseHTTPRequestHandler, HTTPServer
import time
import json
import math
from phue import Bridge

### CONFIG VARIABLES ###
flash_duration = 0.2  # Seconds between setting brightness to max, then to min, then back to what it was originally
philiphs_gateway_ip = '192.168.1.133'  # Local IP address of Philips Hue Gateway - find in your router intercate
csgo_reporting_port = 5959  # The port you specified in the "gamestate_integration_YOURNAME.cfg" - used to communicate with CSGO
csgo_reporting_token = "Q89v5tcxVQ8u"  # The token CSGO uses to prove it is CSGO and not some super-hacker pretending to be CSGO. Has to be the same as in the CSGO gamestate config
lightsToControl = ['Olli soverom lys', 'stue lys', 'inngang lys']
csgo_player_name = "Fruktsalat"  # Not currently used
bomb_planted_brightness_low = 254  # Reduce light maximum with this ammount when bomb is planted
bomb_planted_brightness_pulse = 75  # Pulsate with this brightness difference when bomb is planted
bomb_planted_transition_time = 2

### Hue Setup ###
b = Bridge(philiphs_gateway_ip)
# If the app is not registered and the button is not pressed, press the button and call connect() (this only needs to be run a single time)
b.connect()
# Get the bridge state (This returns the full dictionary that you can explore)
b.get_api()

print(json.dumps(b.get_api()['lights'], indent=4, sort_keys=True))

'''
Philips hue python library documentation: https://github.com/studioimaginaire/phue
All actual logic is performed in the "parse_payload" function down below. Payload is the object we get from CSGO 
'''


### Custom functions ###
def flash():
    # Sets lights to bright, then dark, then back to original
    previous_brightnesses = {}

    for light_name in lightsToControl:
        previous_brightnesses[light_name] = getBrightnessUsingName(light_name)
        setBrightnessUsingName(light_name, 254)
    time.sleep(flash_duration)

    for light_name in lightsToControl:
        setBrightnessUsingName(light_name, 0)
    time.sleep(flash_duration)

    for light_name in lightsToControl:
        setBrightnessUsingName(light_name, previous_brightnesses[light_name])


def setColorTemperatureUsingName(name, ct):
    b.set_light(name, 'ct', ct)


def getColorTemperatureUsingName(name):
    return b.get_light(name)['state']['ct']


def setBrightnessUsingName(name, bri):
    b.set_light(name, 'bri', bri)


def getBrightnessUsingName(name):
    return b.get_light(name)['state']['bri']


def getLightsToControl():
    lights = []
    for light in lightsToControl:
        lights.append(b.get_light(light))
        print(lights)
    return lights


def handleHealth(payload):
    # Sets all lights be have the same brightness as your HP in counterstrike. I don't use this as it was a bit annoying
    if 'player' in payload and 'state' in payload['player']:
        if payload['player']['name'] == csgo_player_name:
            health = payload['player']['state']['health']
            for light in b.lights:
                val = math.floor(health * 2.54)
                if val != light.brightness:
                    print(val)
                    if val == 0:
                        val = 254
                    light.brightness = math.floor(val)


flash()


class MyServer(HTTPServer):
    def __init__(self, server_address, token, RequestHandler):
        self.auth_token = token

        super(MyServer, self).__init__(server_address, RequestHandler)

        # You can store states over multiple requests in the server
        self.round_phase = None
        self.lastPhase = None
        self.ct_before_freezetime = {}
        for light_name in lightsToControl:
            self.ct_before_freezetime[light_name] = getColorTemperatureUsingName(light_name)
        self.bombIsPlanted = False
        self.plantedLightIsHigh = False
        self.brightnessBeforeBombPlant = {}
        self.bombPlantedNextLightChangeTime = time.time()
        for light_name in lightsToControl:
            self.brightnessBeforeBombPlant[light_name] = getBrightnessUsingName(light_name)
        self.bombTimer = 40
        self.bombPlantedStart = 0
        self.lastBombTimePrint = time.time()
        self.roundStart = time.time()
        self.hasSetNewBrightNess = False
        self.nextValueSaveTime = time.time()


class MyRequestHandler(BaseHTTPRequestHandler):

    def getBombPlantHighCommandForLight(self, light):
        value = self.server.brightnessBeforeBombPlant[
                    light] - bomb_planted_brightness_low
        if value < 0:
            value = 0
        value += bomb_planted_brightness_pulse
        if value > 254:
            value = 254
        return {'transitiontime': bomb_planted_transition_time * 10, 'on': True,
                'bri': value}

    def getBombPlantLowCommandForLight(self, light):
        value = self.server.brightnessBeforeBombPlant[
                    light] - bomb_planted_brightness_low
        if value < 0:
            value = 0
        return {'transitiontime': bomb_planted_transition_time * 10, 'on': True,
                'bri': value}

    def do_POST(self):
        length = int(self.headers['Content-Length'])
        body = self.rfile.read(length).decode('utf-8')

        self.parse_payload(json.loads(body))

        self.send_header('Content-type', 'text/html')
        self.send_response(200)
        self.end_headers()

    def is_payload_authentic(self, payload):
        if 'auth' in payload and 'token' in payload['auth']:
            return payload['auth']['token'] == server.auth_token
        else:
            return False

    def parse_payload(self, payload):
        # Ignore unauthenticated payloads
        if not self.is_payload_authentic(payload):
            return None

        round_phase = self.get_round_phase(payload)
        if 'round' in payload and 'bomb' in payload['round']:
            if (self.server.bombPlantedStart + 39) > time.time() and self.server.lastBombTimePrint < time.time() - 1:
                print(
                    "Bomb explodes in: ", math.floor(time.time() - (self.server.bombPlantedStart + 39)) * -1, "seconds")
                self.server.lastBombTimePrint = time.time()
            if (not self.server.bombIsPlanted) and payload['round']['bomb'] == 'planted':
                self.server.bombPlantedStart = time.time()
                for light in lightsToControl:
                    b.set_light(light, self.getBombPlantLowCommandForLight(light))
                    setColorTemperatureUsingName(light, 9999)
                self.server.plantedLightIsHigh = False
                self.server.bombIsPlanted = True
                self.server.bombPlantedNextLightChangeTime = time.time() + bomb_planted_transition_time

            elif payload['round']['bomb'] == 'planted' and (self.server.bombPlantedNextLightChangeTime < time.time()):
                if not self.server.plantedLightIsHigh:
                    for light in lightsToControl:
                        b.set_light(light, self.getBombPlantHighCommandForLight(light))
                    self.server.plantedLightIsHigh = True
                    self.server.bombPlantedNextLightChangeTime = time.time() + bomb_planted_transition_time
                else:
                    for light in lightsToControl:
                        b.set_light(light, self.getBombPlantLowCommandForLight(light))
                    self.server.plantedLightIsHigh = False
                    self.server.bombPlantedNextLightChangeTime = time.time() + bomb_planted_transition_time

            elif self.server.bombIsPlanted and payload['round']['bomb'] != 'planted':
                for light in lightsToControl:
                    setBrightnessUsingName(light, self.server.brightnessBeforeBombPlant[light])
                self.server.bombIsPlanted = False

        if round_phase != self.server.round_phase:
            self.server.round_phase = round_phase
            print('New round phase: %s' % round_phase)

            if round_phase == 'over' or (round_phase == 'freezetime' and self.server.lastPhase != 'over'):
                flash()
                for light_name in lightsToControl:
                    setBrightnessUsingName(light_name, self.server.brightnessBeforeBombPlant[light_name])
            elif round_phase == 'freezetime':
                for light_name in lightsToControl:
                    setColorTemperatureUsingName(light_name, 0)
            else:
                if round_phase == 'live':
                    self.server.nextValueSaveTime = time.time() + bomb_planted_transition_time*3
                    self.server.hasSetNewBrightNess = False
                for light_name in lightsToControl:
                    setColorTemperatureUsingName(light_name, self.server.ct_before_freezetime[light_name])
                    setBrightnessUsingName(light_name, self.server.brightnessBeforeBombPlant[light_name])
            self.server.lastPhase = round_phase
        if time.time() > self.server.nextValueSaveTime and round_phase == 'live' and not self.is_bomb_planted(payload):
            print("saving brightness and temperature")
            for light in lightsToControl:
                self.server.brightnessBeforeBombPlant[light] = getBrightnessUsingName(light)
                self.server.ct_before_freezetime[light] = getColorTemperatureUsingName(light)
            self.server.nextValueSaveTime = time.time() + bomb_planted_transition_time * 3

        # handleHealth(payload)

    def is_bomb_planted(self, payload):
        if 'round' in payload and 'bomb' in payload['round']:
            print("bomb is planted")
            return True

    def get_round_phase(self, payload):
        if 'round' in payload and 'phase' in payload['round']:
            return payload['round']['phase']
        else:
            return None

    def print_bomb_stuff(self, payload):
        if 'bomb' in payload:
            print(payload)

    def log_message(self, format, *args):
        """
        Prevents requests from printing into the console
        """
        return


server = MyServer(('localhost', csgo_reporting_port), csgo_reporting_token, MyRequestHandler)
print(time.asctime(), '-', 'CS:GO GSI Quick Start server starting')

try:
    server.serve_forever()
except (KeyboardInterrupt, SystemExit):
    pass

server.server_close()
print(time.asctime(), '-', 'CS:GO GSI Quick Start server stopped')
