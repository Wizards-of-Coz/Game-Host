import cozmo
import asyncio
import threading
import random
from smsmessenger import SMSMessenger
from enum import Enum

NUM_MAFIA = 2
NUM_INNOCENT = 4
NUM_PLAYER = 6

NIGHT_DECISION_TIME = 15

PRIVATE_MESSAGES = {
    "Role Detail" : "%s, your role is: %s",
    "Detective Response": "The player you checked is %s"
}

class Role(Enum):
    CITIZEN = 0,
    DOCTOR = 1,
    DETECTIVE = 2,
    MAFIOSO = 3,
    BARMAN = 4 

ROLE_NAME = {
    Role.CITIZEN: "citizen",
    Role.MAFIOSO: "mafioso",
    Role.DOCTOR: "doctor",
    Role.DETECTIVE: "detective",
    Role.BARMAN: "barman"
}

class T1State(Enum):
    PREPARE = 0,
    NIGHT = 1,
    DAY = 2

ANNOUNCEMENTS = {
    "Role Start": "Start to assign roles",
    Role.CITIZEN: "Night is coming. Close your eyes",
    Role.BARMAN: "Barman, open your eyes,,, Cancel doctor, detective, or not?",
    Role.DOCTOR: "Doctor, open your eyes,,, who do you want to protect?",
    Role.DETECTIVE: "Detective, open your eyes,,, who do you want to check?",
    Role.MAFIOSO: "Mafia, open your eyes,,, who do you want to kill?",
    T1State.DAY: "Night is over, open your eyes. %s, died last night.",
    "Vote": "Discuss, and vote to lynch one suspect.",
    "Win": "%s win the game"
}

END_STATE = {
    Role.BARMAN: "Barman, close your eyes.",
    Role.DOCTOR: "Doctor, close your eyes.",
    Role.DETECTIVE: "Detective, close your eyes.",
    Role.MAFIOSO: "Mafia, close your eyes.",
}

MAFIA_POOL = [Role.MAFIOSO, Role.MAFIOSO, Role.BARMAN]
INNOCENT_POOL = [Role.CITIZEN, Role.CITIZEN, Role.CITIZEN, Role.CITIZEN, Role.DOCTOR, Role.DETECTIVE]

class Player:
    name = None
    number = None
    role = None
    alive = None
    
    def __init__(self, name, number):
        self.name = name
        self.number = number
        self.alive = True


class PartyGameHost:
    def __init__(self):
        # thread lock
        self._lock = threading.Lock()
        
        self._msgr = SMSMessenger()
        self._msgReceived = False
        self._msgBuffer = []
        self._senderBuffer = []


        # state handlers
        self._stateMsgProcessor = {
            T1State.PREPARE: self.processMsgPrepare,
            T1State.NIGHT: self.processMsgNight,
            T1State.DAY: self.processMsgDay
        }

        # state main loop
        self._stateMainLoop = {
            T1State.PREPARE: self.mainLoopPrepare,
            T1State.NIGHT: self.mainLoopNight,
            T1State.DAY: self.mainLoopDay
        }

        # night msg handlers
        self._nightMsgProcessor = {
            Role.CITIZEN: self.processMsgNightOpen,
            Role.MAFIOSO: self.processMsgMafioso,
            Role.BARMAN: self.processMsgBarman,
            Role.DOCTOR: self.processMsgDoctor,
            Role.DETECTIVE: self.processMsgDetective
        }

        # night main loops
        self._nightMainLoop = {
            Role.CITIZEN: self.mainLoopNightOpen,
            Role.MAFIOSO: self.mainLoopMafioso,
            Role.BARMAN: self.mainLoopBarman,
            Role.DOCTOR: self.mainLoopDoctor,
            Role.DETECTIVE: self.mainLoopDetective
        }


    def initializeGame(self):
        print("Initializing game")
        
        # player data
        self._playerNumbers = []
        self._players = {}
        self._roleRecords = {}
        self._mafiaCount = NUM_MAFIA
        self._innocentCount = NUM_INNOCENT

        # hierarchical state machine
        self._currState = T1State.PREPARE
        self._nightState = None

        # night state variables
        self._announced = False
        self._victim = None
        self._protected = None
        self._blocked = None
        self._detected = None
        self._executed = None

        print("Initializing finish, waiting for players join")

        

    def receiveMessage(self, msg, sender=None):
        if msg:
            with self._lock:
                self._msgReceived = True
                self._msgBuffer.append(msg)
                self._senderBuffer.append(sender)

    async def announce(self, msg):
        self._announced = True
        await self._robot.say_text(msg, play_excited_animation=True, duration_scalar=1.3).wait_for_completed()
        if self._currState == T1State.NIGHT and self._blocked in self._roleRecords and self._blocked == self._nightState and self._nightState != Role.CITIZEN:
            # privately inform the player about blocking
            name = self._roleRecords[self._blocked]
            number = self._players[name].number
            self._msgr.sendMessage(number, "Your ability is canceled by barman tonight")

    async def cozmoSpeak(self, msg):
        await self._robot.say_text(msg, play_excited_animation=True, duration_scalar=1.3).wait_for_completed()
        
    async def processMsgPrepare(self):
        (msg,sender) = self.fetchFromBuffer()

        # get concrete message to work on
        if msg:
            (command,_,name) = msg.partition(",")
            command = command.strip()
            name = name.strip()
            if command == "Join" and name not in self._players:
                self._players[name] = Player(name, sender)
                print(len(self._players), " players joined")

    # common code to get message from buffer
    def fetchFromBuffer(self):
        msg = None
        sender = None
        with self._lock:
            if self._msgReceived:
                msg = self._msgBuffer.pop(0)
                sender = self._senderBuffer.pop(0)
                if not self._msgBuffer:
                    self._msgReceived = False

        return (msg, sender)

    async def mainLoopPrepare(self):
        # enough players to start game
        if len(self._players) == NUM_PLAYER:
            await self.assignRoles()
            
            # change state to start game
            await self.changeState(T1State.NIGHT, Role.CITIZEN)

    async def processMsgNight(self):
        (msg,sender) = self.fetchFromBuffer()

        if msg:
            self._nightMsgProcessor[self._nightState](msg, sender)

    async def mainLoopNight(self):
        if not self._announced:
            await self.announce(ANNOUNCEMENTS[self._nightState])
        
        await self._nightMainLoop[self._nightState]()

    async def processMsgDay(self):
        (msg,sender) = self.fetchFromBuffer()

        if msg:
            (command,_,name) = msg.partition(",")
            command = command.strip()
            name = name.strip()

            if command == "Vote" and name in self._players and self._players[name].alive:
                self._executed = name

    async def mainLoopDay(self):
        if not self._announced:
            self._executed = None
            protected = self._protected == self._victim
            victim = "Nobody"
            if not protected:
                victim = self._victim
                self.killPlayer(victim)
                    
            msg = ANNOUNCEMENTS[T1State.DAY] % victim
            await self.announce(msg)
            if self._innocentCount > self._mafiaCount and self._mafiaCount > 0:
                await self.announce(ANNOUNCEMENTS["Vote"])

        if self._executed:
            name = self._executed
            self.killPlayer(name)
            
            if self._innocentCount > self._mafiaCount and self._mafiaCount > 0:
                # change state to night state
                await self.changeState(T1State.NIGHT, Role.CITIZEN)

        if self._innocentCount <= self._mafiaCount or self._mafiaCount == 0:
            innocentWins = self._mafiaCount == 0
            winner = "innocent" if innocentWins else "mafia"
            await self.announce(ANNOUNCEMENTS["Win"] % winner)
            await asyncio.sleep(1)
            self.initializeGame()

    def killPlayer(self, name):
        print("Player %s is dead" % name)
        self._players[name].alive = False
        role = self._players[name].role
        if role == Role.MAFIOSO or role == Role.BARMAN:
            self._mafiaCount -= 1
        else:
            self._innocentCount -= 1

        if role in self._roleRecords:
            del self._roleRecords[role]
    
    async def assignRoles(self):
        # announce
        await self.announce(ANNOUNCEMENTS["Role Start"])
        
        # randomly pick assignments
        mafiaNames = random.sample(self._players.keys(), NUM_MAFIA)
        innocentNames = list(filter(lambda n: n not in mafiaNames, self._players.keys()))
        mafiaRoles = random.sample(MAFIA_POOL, NUM_MAFIA)
        innocentRoles = random.sample(INNOCENT_POOL, NUM_INNOCENT)

        # record and inform assignments
        for i in range(0, NUM_MAFIA):
            name = mafiaNames[i]
            role = mafiaRoles[i]
            self.sendRoleAssignmentMessage(name, role)

        for i in range(0, NUM_INNOCENT):
            name = innocentNames[i]
            role = innocentRoles[i]
            self.sendRoleAssignmentMessage(name, role)

    def sendRoleAssignmentMessage(self, name, role):
        player = self._players[name]
        player.role = role
        self._roleRecords[role] = name
        msg = PRIVATE_MESSAGES["Role Detail"] % (name, ROLE_NAME[role])
        print(msg)
        self._msgr.sendMessage(player.number, msg)

    def processMsgNightOpen(self, msg, sender):
        pass

    def processMsgMafioso(self, msg, sender):
        (command,_,name) = msg.partition(",")
        command = command.strip()
        name = name.strip()

        if command == "Kill" and name in self._players and self._players[name].alive:
            self._victim = name

    def processMsgBarman(self, msg, sender):
        (command,_,job) = msg.partition(",")
        command = command.strip()
        job = job.strip()

        if command == "Cancel":
            if job.lower() == "doctor":
                self._blocked = Role.DOCTOR
            elif job.lower() == "detective":
                self._blocked = Role.DETECTIVE
            else:
                self._blocked = Role.CITIZEN
            

    def processMsgDoctor(self, msg, sender):
        (command,_,name) = msg.partition(",")
        command = command.strip()
        name = name.strip()

        if command == "Protect" and self._blocked != self._nightState and name in self._players and self._players[name].alive:
            self._protected = name

    def processMsgDetective(self, msg, sender):
        (command,_,name) = msg.partition(",")
        command = command.strip()
        name = name.strip()

        if command == "Detect" and self._blocked != self._nightState and name in self._players and self._players[name].alive:
            self._detected = name

    async def mainLoopNightOpen(self):
        self._victim = None
        self._protected = None
        self._blocked = None
        self._detected = None
        await self.changeState(T1State.NIGHT, Role.MAFIOSO)

    async def mainLoopMafioso(self):
        if self._victim:
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.NIGHT, Role.BARMAN)

    async def mainLoopBarman(self):
        # if this role doesn't exist
        if self._nightState not in self._roleRecords:
            await asyncio.sleep(10)
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.NIGHT, Role.DOCTOR)
        
        elif self._blocked:
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.NIGHT, Role.DOCTOR)

    async def mainLoopDoctor(self):
        # if ability is canceled or this role doesn't exist
        if self._blocked == self._nightState or self._nightState not in self._roleRecords:
            await asyncio.sleep(10)
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.NIGHT, Role.DETECTIVE)
        
        elif self._protected:
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.NIGHT, Role.DETECTIVE)

    async def mainLoopDetective(self):
        # if ability is canceled or this role doesn't exist
        if self._blocked == self._nightState or self._nightState not in self._roleRecords:
            await asyncio.sleep(10)
            await self.cozmoSpeak(END_STATE[self._nightState])
            await self.changeState(T1State.DAY, None)
        
        elif self._detected:
            # make detecting result
            role = self._players[self._detected].role
            innocent = None
            if role == Role.MAFIOSO or role == Role.BARMAN:
                innocent = False
            else:
                innocent = True
            resultMsg = "Innocent" if innocent else "Mafia"
            msg = PRIVATE_MESSAGES["Detective Response"] % resultMsg
            
            # send detecting result
            name = self._roleRecords[self._nightState]
            number = self._players[name].number
            self._msgr.sendMessage(number, msg)

            await self.announce(END_STATE[self._nightState])
            await self.changeState(T1State.DAY, None)

    async def changeState(self, state, nightState):
        print("Change to state: ", state, ", ", nightState)
        self._currState = state
        self._nightState = nightState
        self._announced = False
        with self._lock:
            self._msgBuffer = []
            self._senderBuffer = []
            self._msgReceived = False
        await asyncio.sleep(0.5)
        

    async def run(self, coz_conn:cozmo.conn.CozmoConnection):
        self._robot = await coz_conn.wait_for_robot()
        print("Cozmo running")

        # Add observer
        self._msgr.addObserver(self.receiveMessage)
        
        # Start SMS server
        t1 = threading.Thread(target=self._msgr.run, args=[], daemon=True)
        print("Server thread is daemon ", t1.isDaemon())
        t1.start()

        self.initializeGame()
        while True:
            await self._stateMsgProcessor[self._currState]()
            await self._stateMainLoop[self._currState]()
            await asyncio.sleep(0.1)

    
if __name__ == "__main__":
    host = PartyGameHost()
    cozmo.setup_basic_logging()
    cozmo.connect(host.run)

