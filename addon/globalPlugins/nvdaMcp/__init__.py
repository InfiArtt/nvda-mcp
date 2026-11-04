# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Lets an MCP server, and through it an AI assistant, work with NVDA.

The plugin captures what NVDA speaks and runs a loopback-only bridge
that the ``nvda-mcp`` server connects to. See the add-on's readme for setup.
"""

import os
import webbrowser

import addonHandler
import api
import config
import globalPluginHandler
import globalVars
import ui
import wx
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
from logHandler import log
from scriptHandler import script
from speech.extensions import pre_speech
from speech.types import SpeechSequence

from .actionLog import ActionLog
from .bridge import Bridge
from .configSpec import CONFIG_SECTION, CONFIG_SPEC
from .devTools import DevTools
from .nvdaActions import NvdaActions
from .setupCommands import CLIENTS, setupText
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
		# Translators: In the NVDA MCP settings panel's list of clients to set up:
		# clients configured with a JSON settings file instead of a command.
		"json": _("Claude Desktop, Cursor and others (JSON settings)"),
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
		labels = _clientLabels()
		self.clientChoice = helper.addLabeledControl(
			# Translators: A list in the NVDA MCP settings panel, choosing the program to set up.
			_("Set up this MCP &client:"),
			wx.Choice,
			choices=[labels[client] for client in CLIENTS],
		)
		self.clientChoice.SetSelection(0)
		# Translators: A button in the NVDA MCP settings panel.
		copyButton = helper.addItem(wx.Button(self, label=_("C&opy setup command")))
		copyButton.Bind(wx.EVT_BUTTON, self.onCopySetup)
		# Translators: A button in the NVDA MCP settings panel that opens the author's PayPal page in a web browser.
		donateButton = helper.addItem(wx.Button(self, label=_("&Donate to support NVDA MCP (opens PayPal)")))
		donateButton.Bind(wx.EVT_BUTTON, lambda event: webbrowser.open(DONATE_URL))

	def onCopySetup(self, event: wx.CommandEvent) -> None:
		client = CLIENTS[self.clientChoice.GetSelection()]
		if not api.copyToClip(setupText(client, _addonVersion())):
			return
		if client == "json":
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

	def postSave(self) -> None:
		if _plugin is not None:
			_plugin.applyConfig()


_plugin: "GlobalPlugin | None" = None


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self) -> None:
		super().__init__()
		global _plugin
		self._bridge: Bridge | None = None
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
