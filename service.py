#!/usr/bin/env python
import re, sys, os, json
import xbmc, xbmcgui, xbmcaddon
from twisted.internet import reactor
from twisted.internet import task
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver
from datetime import datetime

xbmcAddon = xbmcaddon.Addon()
xbmcDialog = xbmcgui.Dialog()
notificationTimeout = int(int(xbmcAddon.getSetting("notification.duration"))*1000)
notificationIcon = os.path.join(xbmcAddon.getAddonInfo("path"), "resources", "media", "icon_ring.png")
ncid_client = None

class Caller:
    caller = "Unknown"
    number = None

    def __init__(self, caller, number):
        self.caller = caller
        self.number = number

    def getDict(self):
        return {
            'caller': self.caller,
            'number': self.number
        }


class Event:
    def __init__(self):
        self.handlers = set()

    def handle(self, handler):
        self.handlers.add(handler)
        return self

    def unhandle(self, handler):
        try:
            self.handlers.remove(handler)
        except:
            raise ValueError("Handler is not handling this event, so cannot unhandle it.")
        return self

    def fire(self, *args, **kargs):
        for handler in self.handlers:
            handler(*args, **kargs)

    def getHandlerCount(self):
        return len(self.handlers)

    __iadd__ = handle
    __isub__ = unhandle
    __call__ = fire
    __len__ = getHandlerCount


class NcidClientFactory(ReconnectingClientFactory):
    initialDelay = 20
    maxDelay = 30

    def __init__(self, onCallIncoming=None):
        self.onCallIncoming = onCallIncoming
        self.hangup_ok = False

    def startedConnecting(self, connector):
        print("Connecting to NCID Server...")

    def buildProtocol(self, addr):
        print("Connected to NCID Server")
        self.resetDelay()
        return NcidLineReceiver(onCallIncoming=self.onCallIncoming)

    def clientConnectionLost(self, connector, reason):
        if not self.hangup_ok:
            print("Connection to NCID Server lost\n (%s)\nretrying..." % reason.getErrorMessage())
            ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        print("Connecting to NCID Server failed\n (%s)\nretrying..." % reason.getErrorMessage())
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


class NcidLineReceiver(LineReceiver):
    def __init__(self, onCallIncoming):

        self.onCallIncoming = onCallIncoming
        self.resetValues()

    def resetValues(self):
        self.number = None
        self.caller = None
        self.date = '01011970'
        self.time = '0001'
        self.line = ''

    def notifyAndReset(self):
        caller = Caller(self.caller, self.number)
        if self.onCallIncoming:
            print("Invoking Callback...")
            self.onCallIncoming(caller)
        self.resetValues()

    def lineReceived(self, line):
        print("[NcidLineReceiver] lineReceived: %s" % line)
        #200 NCID Server: ARC_ncidd 0.01
        #CIDLOG: *DATE*21102010*TIME*1454*LINE**NMBR*089999999999*MESG*NONE*NAME*NO NAME*
        #CIDLOG: *DATE*21102010*TIME*1456*LINE**NMBR*089999999999*MESG*NONE*NAME*NO NAME*
        #CID: *DATE*22102010*TIME*1502*LINE**NMBR*089999999999*MESG*NONE*NAME*NO NAME*

        #Callog entries begin with CIDLOG, "current" events begin with CID
        #we don't want to do anything with log-entries
        if line.startswith("CID:"):
            line = line[6:]
            print("[NcidLineReceiver.lineReceived] filtered Line: %s" % line)
        else:
            return

        items = line.split('*')

        for i in range(0, len(items)):
            item = items[i]

            if item == 'DATE':
                self.date = items[i + 1]
            elif item == 'TIME':
                self.time = items[i + 1]
            elif item == 'LINE':
                self.line = items[i + 1]
            elif item == 'NMBR':
                self.number = items[i + 1]
            elif item == 'NAME':
                self.caller = items[i + 1]

        date = datetime.strptime("%s - %s" % (self.date, self.time), "%m%d%Y - %H%M")
        self.date = date

        if not self.number:
            print("[NcidLineReceiver] lineReceived: no number")
            match = re.search(r"\*NMBR\*(.+?)\*MESG\*", line)
            if match:
                self.number = match.group(1)
            else:
                self.number = "0"
        else:
            #self.number = stripCbCPrefix(self.number, config.plugins.NcidClient.country.value)
            #print("[NcidLineReceiver] lineReceived phonebook.search: %s" % self.number)
            #self.caller = phonebook.search(self.number)
            #print("[NcidLineReceiver] lineReceived phonebook.search reault: %s" % self.caller)
            if not self.caller:
                self.caller = "Unknown"

        self.notifyAndReset()


class NcidClient:
    def __init__(self, host="localhost", port=3333, onCallIncoming=None):
        self.host = host
        self.port = port
        self.desc = None
        self.onCallIncoming = onCallIncoming
        self.connect()


    def connect(self):
        self.abort()
        factory = NcidClientFactory(onCallIncoming=self.onCallIncoming)
        self.desc = (factory, reactor.connectTCP(self.host, self.port, factory))


    def shutdown(self):
        self.abort()

    def abort(self):
        if self.desc is not None:
            self.desc[0].hangup_ok = True
            self.desc[0].stopTrying()
            self.desc[1].disconnect()
            self.desc = None


def parseBoolString(theString):
    """
    parses a string like 'True' to bool value
    @type theString: str
    @param theString: String to convert
    """
    return theString[0].upper() == 'T'


def handleIncomingCall(caller):
    """
    handles the incoming call in the reactor loop
    @type caller: Caller
    @param caller: The Caller Object
    """
    if caller.caller == "Unknown":
        caller.caller = xbmcaddon.getLocalizedString(30602)

    callerstring = xbmcAddon.getLocalizedString(30601) % caller.caller 
    xbmc.executebuiltin("XBMC.Notification(%s,%s,%s,%s)" % ('"'+callerstring+'"',
        caller.number,
        int(notificationTimeout),
        notificationIcon
    ))

    activePlayers = json.loads(xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}'))


    if parseBoolString(xbmcAddon.getSetting("general.pause_playback.enabled")):
        for player in activePlayers["result"]:
            xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Player.PlayPause", "params": { "playerid": %s, "play": false }, "id": 1}' % player["playerid"])

    if parseBoolString(xbmcAddon.getSetting("general.lower_volume.enabled")):
        targetVolume = int(xbmcAddon.getSetting("general.lower_volume.to"))
        currentVolume = json.loads(xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Application.GetProperties", "params": { "properties": ["volume"] }, "id": 1}'))
        if int(currentVolume["result"]["volume"]) >= targetVolume:
            xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Application.SetVolume", "params": { "volume": %s }, "id": 1}' % targetVolume)

    if parseBoolString(xbmcAddon.getSetting("general.mute_volume.enabled")):
        mutedState  = json.loads(xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Application.GetProperties", "params": { "properties": ["muted"] }, "id": 1}'))
        if not mutedState['result']['muted']:
            xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Application.SetMute", "params": { "mute": true }, "id": 1}')



def shouldWeExit():
    if xbmc.abortRequested == True:
        xbmc.log("shouldWeExit() - Indeed, we better stop reactor now...", xbmc.LOGDEBUG)
        reactor.stop()


def bootServices():
    #xbmc.log("Starting Fritzbox Client", xbmc.LOGDEBUG)
    ncid_client = NcidClient(host=xbmcAddon.getSetting("client.ncid.host"),
                                    port=int(xbmcAddon.getSetting("client.ncid.port")),
                                    onCallIncoming=handleIncomingCall)
    l = task.LoopingCall(shouldWeExit)
    l.start(0.5)
    reactor.run(installSignalHandlers=0)


if __name__ == "__main__":
    bootServices()
