# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Lets an MCP server, and through it an AI assistant, work with NVDA.

The plugin captures what NVDA speaks and runs a loopback-only bridge
that the ``nvda-mcp`` server connects to. See the add-on's readme for setup.
"""

import os
import threading
import webbrowser

import addonHandler
import api
import config
import controlTypes
import globalPluginHandler
import globalVars
import ui
import wx
from gui import guiHelper, mainFrame, nvdaControls
from gui.guiHelper import wxCallOnMain
from gui.message import DefaultButtonSet, DialogType, MessageDialog, ReturnCode
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
from logHandler import log
from scriptHandler import script
from speech.extensions import pre_speech
from speech.types import SpeechSequence

from . import accessShare
from .actionLog import ActionLog
from .bridge import PROTOCOL_VERSION, Bridge
from .configSpec import CONFIG_SECTION, CONFIG_SPEC
from .contextText import MAX_LIST_ITEMS, contextText
from .devTools import DevTools
from .nvdaActions import NvdaActions
from .setupCommands import (
	CLIENTS,
	COMMAND_CLIENTS,
	FILE_CLIENTS,
	SetupError,
	configFilePath,
	installInFile,
	runSetupCommand,
	setupText,
)
from .speechLog import SpeechLog, sequenceToText

addonHandler.initTranslation()

# Translators: The name of the category of this add-on's commands in the Input Gestures dialog.
SCRCAT_NVDA_MCP = _("NVDA MCP")
DONATE_URL = "https://paypal.me/rafli23115"


def _connectionFilePath() -> str:
	"""Where the bridge publishes its port and token. The nvda-mcp server reads this file."""
	return os.path.join(globalVars.appArgs.configPath, "nvdaMcp", "connection.json")


def _actionLogPath() -> str:
	return os.path.join(globalVars.appArgs.configPath, "nvdaMcp", "actions.log")


def _addonVersion() -> str:
	return addonHandler.getCodeAddon().version


def _clientLabels() -> dict[str, str]:
	return {
		# Translators: An MCP client in the NVDA MCP settings panel's list of clients to set up.
		"claudeCode": _("Claude Code"),
		# Translators: An MCP client in the NVDA MCP settings panel's list of clients to set up.
		"codex": _("Codex CLI"),
		# Translators: An MCP client in the NVDA MCP settings panel's list of clients to set up.
		"claudeDesktop": _("Claude Desktop"),
		# Translators: An MCP client in the NVDA MCP settings panel's list of clients to set up.
		# Antigravity is Google's AI coding application.
		"antigravity": _("Antigravity"),
		# Translators: An MCP client in the NVDA MCP settings panel's list of clients to set up.
		"cursor": _("Cursor"),
		# Translators: In the NVDA MCP settings panel's list of clients to set up:
		# other clients, configured by pasting JSON settings into their settings file.
		"json": _("Other clients (JSON settings)"),
	}


def _ensureConfigSection() -> None:
	# installTasks registers the section for the next start.
	# This covers add-ons copied in by hand during development, which skip installTasks.
	# It also fills in settings added since the installed version registered the section.
	if CONFIG_SECTION not in config.conf.spec:
		config.conf.spec[CONFIG_SECTION] = CONFIG_SPEC
		return
	sectionSpec = config.conf.spec[CONFIG_SECTION]
	for key, spec in CONFIG_SPEC.items():
		if key not in sectionSpec:
			sectionSpec[key] = spec


class NvdaMcpSettingsPanel(SettingsPanel):
	# Translators: The title of this add-on's panel in NVDA's settings dialog.
	title = _("NVDA MCP")

	def makeSettings(self, settingsSizer: wx.BoxSizer) -> None:
		sectionConfig = config.conf[CONFIG_SECTION]
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.enabledCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel.
			wx.CheckBox(self, label=_("&Let MCP clients, such as AI assistants, connect to NVDA")),
		)
		self.enabledCheckBox.SetValue(sectionConfig["enabled"])
		self.allowControlCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel.
			wx.CheckBox(self, label=_("Allow MCP clients to &press keys")),
		)
		self.allowControlCheckBox.SetValue(sectionConfig["allowControl"])
		self.confirmControlCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel.
			wx.CheckBox(self, label=_("&Ask before the first key press after NVDA starts")),
		)
		self.confirmControlCheckBox.SetValue(sectionConfig["confirmControl"])
		self.allowedAppsEdit = helper.addLabeledControl(
			# Translators: A text field in the NVDA MCP settings panel.
			_("Only let MCP clients control these &applications (comma separated, empty for all):"),
			wx.TextCtrl,
		)
		self.allowedAppsEdit.SetValue(sectionConfig["allowedApps"])
		self.logActionsCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel.
			wx.CheckBox(self, label=_("&Keep a log of every action MCP clients take")),
		)
		self.logActionsCheckBox.SetValue(sectionConfig["logActions"])
		self.allowBrowserInspectionCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel. Remote debugging is a setting of Chrome and Brave.
			wx.CheckBox(
				self,
				label=_("Let MCP clients read the &HTML of web pages through the browser's remote debugging"),
			),
		)
		self.allowBrowserInspectionCheckBox.SetValue(sectionConfig["allowBrowserInspection"])
		self.allowScreenCaptureCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel. The pictures are sent to the AI assistant.
			wx.CheckBox(self, label=_("Let MCP clients take pictures of controls on the &screen")),
		)
		self.allowScreenCaptureCheckBox.SetValue(sectionConfig["allowScreenCapture"])
		self.historySizeSpin = helper.addLabeledControl(
			# Translators: A spin control in the NVDA MCP settings panel.
			_("Number of spoken &messages to remember:"),
			nvdaControls.SelectOnFocusSpinCtrl,
			min=50,
			max=5000,
			initial=sectionConfig["speechHistorySize"],
		)
		self.blockAccessControlCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel. Without it, a helper connected through
			# MCP Access may ask to press keys, and NVDA asks the user once per session.
			wx.CheckBox(self, label=_("&Never let MCP Access helpers press keys")),
		)
		self.blockAccessControlCheckBox.SetValue(sectionConfig["blockAccessControl"])
		self.blockAccessCaptureCheckBox = helper.addItem(
			# Translators: A checkbox in the NVDA MCP settings panel. Without it, a helper connected through
			# MCP Access may ask to take pictures of the screen, and NVDA asks the user once per session.
			wx.CheckBox(self, label=_("Never let MCP Access helpers take p&ictures of the screen")),
		)
		self.blockAccessCaptureCheckBox.SetValue(sectionConfig["blockAccessCapture"])
		self.accessRelayEdit = helper.addLabeledControl(
			# Translators: A text field in the NVDA MCP settings panel. MCP Access lets a helper's AI assistant
			# work with this computer's NVDA from far away, through a relay server at this address.
			_("MCP Access &relay address:"),
			wx.TextCtrl,
		)
		self.accessRelayEdit.SetValue(sectionConfig["accessRelay"])
		labels = _clientLabels()
		self.clientChoice = helper.addLabeledControl(
			# Translators: A list in the NVDA MCP settings panel, choosing the program to set up.
			_("Set up this MCP &client:"),
			wx.Choice,
			choices=[labels[client] for client in CLIENTS],
		)
		self.clientChoice.SetSelection(0)
		self.clientChoice.Bind(wx.EVT_CHOICE, self.onClientChoice)
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# Translators: A button in the NVDA MCP settings panel that sets up the chosen MCP client.
		self.setUpButton = buttons.addButton(self, label=_("Set &up now"))
		self.setUpButton.Bind(wx.EVT_BUTTON, self.onSetUp)
		# Translators: A button in the NVDA MCP settings panel.
		copyButton = buttons.addButton(self, label=_("C&opy setup command"))
		copyButton.Bind(wx.EVT_BUTTON, self.onCopySetup)
		helper.addItem(buttons)
		# Translators: A button in the NVDA MCP settings panel that opens the author's PayPal page in a web browser.
		donateButton = helper.addItem(wx.Button(self, label=_("&Donate to support NVDA MCP (opens PayPal)")))
		donateButton.Bind(wx.EVT_BUTTON, lambda event: webbrowser.open(DONATE_URL))

	def onClientChoice(self, event: wx.CommandEvent) -> None:
		# Other clients have no known settings file, so they can only be set up by pasting.
		self.setUpButton.Enable(CLIENTS[self.clientChoice.GetSelection()] != "json")

	def onSetUp(self, event: wx.CommandEvent) -> None:
		client = CLIENTS[self.clientChoice.GetSelection()]
		label = _clientLabels()[client]
		version = _addonVersion()
		if client in FILE_CLIENTS:
			path = configFilePath(client)
			# Translators: Asked before NVDA MCP adds itself to an MCP client's settings file.
			# {client} is the client, such as Claude Desktop; {path} is the settings file.
			question = _(
				"NVDA MCP will add itself to {client}'s settings, in {path}. "
				"Its other settings stay as they are, and a copy of the current file is kept with .bak added "
				"to its name. Continue?"
			).format(client=label, path=path)
		else:
			# Translators: Asked before NVDA MCP runs an MCP client's setup command.
			# {client} is the client, such as Claude Code; {command} is the command.
			question = _("NVDA MCP will run this command to set up {client}:\n{command}\nContinue?").format(
				client=label, command=setupText(client, version)
			)
		# Translators: The title of the dialog asking to set up an MCP client.
		title = _("Set up {client}").format(client=label)
		dialog = MessageDialog(self, question, title, buttons=DefaultButtonSet.YES_NO)
		dialog.setDefaultFocus(ReturnCode.NO)
		dialog.setFallbackAction(ReturnCode.NO)
		if dialog.ShowModal() != ReturnCode.YES:
			return
		if client in FILE_CLIENTS:
			try:
				installInFile(path, version)
			except SetupError as error:
				self._reportSetUpError(label, str(error))
				return
			self._reportSetUp(label)
			return
		# Translators: Reported while an MCP client's setup command runs.
		ui.message(_("Setting up {client}...").format(client=label))

		def run() -> None:
			try:
				runSetupCommand(client, version)
			except SetupError as error:
				wx.CallAfter(self._reportSetUpError, label, str(error))
				return
			wx.CallAfter(self._reportSetUp, label)

		threading.Thread(target=run, name="nvdaMcpSetUp", daemon=True).start()

	def _reportSetUp(self, label: str) -> None:
		# Translators: Reported after NVDA MCP set up an MCP client. {client} is the client, such as Cursor.
		ui.message(_("{client} is set up. Restart {client} so it starts NVDA MCP.").format(client=label))

	def _reportSetUpError(self, label: str, error: str) -> None:
		MessageDialog(
			self,
			# Translators: Shown when setting up an MCP client failed. {error} says why, in English.
			_(
				"{client} could not be set up. {error}\nYou can copy the setup command and add it by hand."
			).format(client=label, error=error),
			# Translators: The title of the message shown when setting up an MCP client failed.
			_("NVDA MCP setup failed"),
			dialogType=DialogType.ERROR,
		).ShowModal()

	def onCopySetup(self, event: wx.CommandEvent) -> None:
		client = CLIENTS[self.clientChoice.GetSelection()]
		if not api.copyToClip(setupText(client, _addonVersion())):
			return
		if client not in COMMAND_CLIENTS:
			# Translators: Reported after copying an MCP client's JSON settings in the NVDA MCP settings panel.
			ui.message(_("Settings copied. Paste them into the client's MCP settings file."))
		else:
			# Translators: Reported after copying a setup command in the NVDA MCP settings panel.
			ui.message(_("Setup command copied. Paste it into a command prompt and press Enter."))

	def onSave(self) -> None:
		sectionConfig = config.conf[CONFIG_SECTION]
		sectionConfig["enabled"] = self.enabledCheckBox.IsChecked()
		sectionConfig["allowControl"] = self.allowControlCheckBox.IsChecked()
		sectionConfig["confirmControl"] = self.confirmControlCheckBox.IsChecked()
		sectionConfig["allowedApps"] = self.allowedAppsEdit.GetValue().strip()
		sectionConfig["logActions"] = self.logActionsCheckBox.IsChecked()
		sectionConfig["allowBrowserInspection"] = self.allowBrowserInspectionCheckBox.IsChecked()
		sectionConfig["allowScreenCapture"] = self.allowScreenCaptureCheckBox.IsChecked()
		sectionConfig["speechHistorySize"] = self.historySizeSpin.GetValue()
		sectionConfig["blockAccessControl"] = self.blockAccessControlCheckBox.IsChecked()
		sectionConfig["blockAccessCapture"] = self.blockAccessCaptureCheckBox.IsChecked()
		sectionConfig["accessRelay"] = self.accessRelayEdit.GetValue().strip() or accessShare.DEFAULT_RELAY

	def postSave(self) -> None:
		if _plugin is not None:
			_plugin.applyConfig()


_plugin: "GlobalPlugin | None" = None


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self) -> None:
		super().__init__()
		global _plugin
		self._bridge: Bridge | None = None
		self._share: accessShare.ShareSession | None = None
		if globalVars.appArgs.secure:
			# Never expose the secure desktop (sign-in, UAC) to another process.
			return
		_ensureConfigSection()
		self._speechLog = SpeechLog(config.conf[CONFIG_SECTION]["speechHistorySize"])
		self._actions = NvdaActions(self._speechLog, ActionLog(_actionLogPath()))
		self._devTools = DevTools(self._speechLog, self._actions)
		self._devTools.register()
		pre_speech.register(self._onPreSpeech)
		NVDASettingsDialog.categoryClasses.append(NvdaMcpSettingsPanel)
		_plugin = self
		self.applyConfig()

	def terminate(self) -> None:
		global _plugin
		if _plugin is self:
			pre_speech.unregister(self._onPreSpeech)
			self._devTools.unregister()
			NVDASettingsDialog.categoryClasses.remove(NvdaMcpSettingsPanel)
			self._stopSharing()
			self._stopBridge()
			_plugin = None
		super().terminate()

	def applyConfig(self) -> None:
		"""Start or stop the bridge and resize the speech log to match the configuration."""
		sectionConfig = config.conf[CONFIG_SECTION]
		self._speechLog.resize(sectionConfig["speechHistorySize"])
		if not sectionConfig["allowControl"]:
			self._actions.revokeControlApproval()
		if sectionConfig["enabled"] and self._bridge is None:
			self._startBridge()
		elif not sectionConfig["enabled"]:
			self._stopSharing()
			self._stopBridge()

	def _startBridge(self) -> None:
		handlers = {**self._actions.handlers(), **self._devTools.handlers()}
		bridge = Bridge(handlers, _connectionFilePath(), onError=log.error, addonVersion=_addonVersion())
		try:
			bridge.start()
		except OSError:
			log.exception("NVDA MCP bridge could not start")
			return
		self._bridge = bridge
		log.info(f"NVDA MCP bridge listening on 127.0.0.1:{bridge.port}")

	def _stopBridge(self) -> None:
		if self._bridge is not None:
			self._bridge.stop()
			self._bridge = None

	def _onPreSpeech(self, speechSequence: SpeechSequence, **kwargs) -> None:
		self._speechLog.add(sequenceToText(speechSequence))

	@script(
		# Translators: Describes a command in the Input Gestures dialog.
		description=_("Copies what NVDA sees here, to paste into a chat with any AI assistant"),
		category=SCRCAT_NVDA_MCP,
	)
	def script_copyContext(self, gesture) -> None:
		actions = getattr(self, "_actions", None)
		if actions is None:
			return
		status = actions._getStatus({})
		focus = actions._getFocus({})
		try:
			tree = actions._getTree({"maxDepth": 6, "maxNodes": 200, "maxChildren": MAX_LIST_ITEMS})
		except Exception:  # noqa: BLE001 - the copy is still useful without the window's controls
			log.debugWarning("NVDA MCP could not read the window for the copy", exc_info=True)
			tree = None
		speech = [entry.text for entry in self._speechLog.since(0, 100)]
		# States nearly every control has, or that only say a list item is scrolled out of view.
		hiddenStates = frozenset(
			state.displayString
			for state in (
				controlTypes.State.FOCUSABLE,
				controlTypes.State.SELECTABLE,
				controlTypes.State.INVISIBLE,
				controlTypes.State.OFFSCREEN,
			)
		)
		if api.copyToClip(contextText(status, focus, tree, speech, hiddenStates)):
			# Translators: Reported after copying what NVDA sees, to paste into an AI chat.
			ui.message(_("Copied what NVDA sees here. It can include private text from this window."))

	@script(
		# Translators: Describes a command in the Input Gestures dialog. MCP Access lets someone the user trusts
		# help them from far away, with an AI assistant that works through this computer's NVDA.
		description=_("Shares this computer with a helper through MCP Access, or says who is connected"),
		category=SCRCAT_NVDA_MCP,
	)
	def script_shareComputer(self, gesture) -> None:
		if not self._isRunning():
			return
		share = self._share
		if share is not None and share.isRunning:
			if share.helperName:
				# Translators: Reported by the share command while a helper is connected.
				ui.message(_("{helper} is connected through MCP Access").format(helper=share.helperName))
			else:
				# Translators: Reported by the share command while a code waits for a helper.
				ui.message(_("Waiting for a helper. The code is {code}").format(code=_spokenCode(share.code)))
			return
		self._share = accessShare.ShareSession(
			config.conf[CONFIG_SECTION]["accessRelay"],
			self._bridge.dispatch,
			self._approveHelper,
			lambda event, details: wx.CallAfter(self._onShareEvent, event, details),
			computerName=os.environ.get("COMPUTERNAME") or "NVDA",
			addonVersion=_addonVersion(),
			protocolVersion=PROTOCOL_VERSION,
		)
		# Translators: Reported while NVDA MCP connects to the MCP Access relay.
		ui.message(_("Connecting to MCP Access..."))
		self._share.start()

	@script(
		# Translators: Describes a command in the Input Gestures dialog.
		description=_("Stops sharing this computer through MCP Access"),
		category=SCRCAT_NVDA_MCP,
	)
	def script_stopSharing(self, gesture) -> None:
		if self._share is None or not self._share.isRunning:
			# Translators: Reported when the user stops sharing but nothing is shared.
			ui.message(_("This computer is not being shared"))
			return
		self._stopSharing()

	def _stopSharing(self) -> None:
		if self._share is not None:
			self._share.stop()

	def _onShareEvent(self, event: str, details: dict) -> None:
		"""What the sharing session reports, said to the user. Runs on the main thread."""
		if event == "waiting":
			api.copyToClip(details["code"])
			ui.message(
				# Translators: Reported after NVDA MCP made an MCP Access code. {minutes} is a number.
				_(
					"MCP Access code copied to the clipboard. Send it only to someone you trust: "
					"whoever has it can ask to see this computer. It works for {minutes} minutes."
				).format(minutes=details["minutes"]),
			)
		elif event == "connected":
			self._logAccess("mcpAccessConnected", details["helper"])
			ui.message(
				# Translators: Reported when a helper connects through MCP Access.
				_("{helper} is connected through MCP Access. Use the stop sharing command to end it.").format(
					helper=details["helper"]
				),
			)
		elif event == "ended":
			if details.get("helper"):
				self._logAccess("mcpAccessEnded", details["helper"], reason=details["reason"])
			ui.message(_accessEndedMessage(details))

	def _logAccess(self, action: str, helper: str, **details) -> None:
		# Who connected is always logged, even with the action log turned off for MCP clients on this computer.
		try:
			self._actions._actionLog.record(action, None, helper=helper, **details)
		except OSError:
			log.error("NVDA MCP could not write its action log", exc_info=True)

	def _approveHelper(self, helperName: str, fingerprint: str) -> bool:
		"""Ask the user whether the helper may connect. Called from the sharing thread; waits for the answer."""
		return wxCallOnMain(_askAccessApproval, helperName, fingerprint)

	def _isRunning(self) -> bool:
		if self._bridge is None:
			# Translators: Reported when an NVDA MCP command is used but the add-on is not running.
			ui.message(_("NVDA MCP is off. Turn it on in NVDA Settings, NVDA MCP category."))
			return False
		return True

	@script(
		# Translators: Describes a command in the Input Gestures dialog.
		description=_("Reports whether NVDA MCP is running and whether it may press keys"),
		category=SCRCAT_NVDA_MCP,
		speakOnDemand=True,
	)
	def script_reportStatus(self, gesture) -> None:
		if not self._isRunning():
			return
		if config.conf[CONFIG_SECTION]["allowControl"]:
			# Translators: Reported by the status command when key presses are allowed.
			controlText = _("may press keys")
		else:
			# Translators: Reported by the status command when key presses are not allowed.
			controlText = _("read only")
		# Translators: Reported by the status command. {port} is a network port number, {control} describes permissions.
		ui.message(
			_("NVDA MCP running on port {port}, {control}").format(
				port=self._bridge.port, control=controlText
			)
		)

	@script(
		# Translators: Describes a command in the Input Gestures dialog.
		description=_("Stops MCP clients from pressing keys until you approve again"),
		category=SCRCAT_NVDA_MCP,
	)
	def script_revokeControl(self, gesture) -> None:
		if not self._isRunning():
			return
		self._actions.revokeControlApproval()
		# Translators: Reported after the user revokes permission to press keys.
		ui.message(_("Key press permission revoked"))

	@script(
		# Translators: Describes a command in the Input Gestures dialog.
		description=_("Opens the log of actions MCP clients have taken"),
		category=SCRCAT_NVDA_MCP,
	)
	def script_openActionLog(self, gesture) -> None:
		path = _actionLogPath()
		if not os.path.exists(path):
			# Translators: Reported when the user opens the action log before any action was recorded.
			ui.message(_("No actions have been logged yet"))
			return
		os.startfile(path)


def _spokenCode(code: str) -> str:
	"""The code with spaces between its characters, so speech reads it letter by letter."""
	return ", ".join(" ".join(group) for group in code.split("-"))


# The person being helped has this long to answer; the helper's server stops waiting soon after.
ACCESS_APPROVAL_SECONDS = 110


def _askAccessApproval(helperName: str, fingerprint: str) -> bool:
	"""Ask, with No focused, whether a helper may see and use this computer through NVDA."""
	# Translators: Title of the dialog asking whether to let a helper connect through MCP Access.
	# {helper} is the name the helper's program gives itself; NVDA cannot verify it.
	title = _("NVDA MCP: let {helper} see this computer?").format(helper=helperName)
	dialog = MessageDialog(
		mainFrame,
		# Translators: Asks whether to let a helper connect through MCP Access.
		# {helper} is the name the helper's program gives itself; {check} is a short code both sides see.
		_(
			"Someone with your MCP Access code, calling themselves {helper}, wants to see this computer through "
			"NVDA, with an AI assistant: what is on the screen, what NVDA says, and the text of windows. "
			"If they want to press keys or take pictures of the screen, NVDA asks you first.\n\n"
			"Allow this only if you asked this person for help. Never tell them a password. "
			"Session check: {check}. You can stop sharing at any time.\n\n"
			"Allow {helper} to connect?"
		).format(helper=helperName, check=fingerprint),
		title,
		dialogType=DialogType.WARNING,
		buttons=DefaultButtonSet.YES_NO,
	)
	dialog.setDefaultFocus(ReturnCode.NO)
	dialog.setFallbackAction(ReturnCode.NO)
	timer = wx.CallLater(ACCESS_APPROVAL_SECONDS * 1000, dialog.Close)
	mainFrame.prePopup()
	try:
		answer = dialog.ShowModal()
	finally:
		timer.Stop()
		mainFrame.postPopup()
	return answer == ReturnCode.YES


def _accessEndedMessage(details: dict) -> str:
	"""What to say when an MCP Access session ends, in the user's language where the reason is known."""
	helper = details.get("helper") or ""
	kind = details.get("kind")
	if kind == "stopped":
		# Translators: Reported when the user stops sharing through MCP Access.
		return _("MCP Access sharing stopped")
	if kind == "helperLeft":
		# Translators: Reported when the helper ends an MCP Access session. {helper} is their name.
		return _("{helper} ended the MCP Access session").format(helper=helper)
	if kind == "declined":
		# Translators: Reported after the user answered No to a helper connecting through MCP Access.
		return _("MCP Access: the helper was not allowed to connect")
	if kind == "expired":
		# Translators: Reported when nobody used an MCP Access code in time.
		return _("The MCP Access code expired before anyone used it. Share again for a new code.")
	if kind == "timeLimit":
		# Translators: Reported when an MCP Access session reaches its time limit.
		return _("MCP Access sharing ended after two hours. Share again if you still need help.")
	if kind == "insecure":
		# Translators: Reported when MCP Access stops because a message could not be verified.
		return _("MCP Access stopped because the connection was not secure")
	if kind == "relayClosed":
		# Translators: Reported when the connection to the MCP Access relay is lost.
		return _("MCP Access sharing ended: the connection to the relay was lost")
	# Translators: Reported when sharing through MCP Access ends. {reason} says why, in English.
	return _("MCP Access sharing ended. {reason}").format(reason=details.get("reason", ""))
