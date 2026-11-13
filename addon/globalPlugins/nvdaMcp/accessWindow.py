# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""The MCP Access window: the session's status, the conversation with the helper, and a field to answer.

One place for everything while sharing, instead of a command for each thing.
"""

import threading
from collections.abc import Callable

import addonHandler
import ui
import wx
from gui import guiHelper
from logHandler import log

from .accessShare import AccessShareError, ShareSession

addonHandler.initTranslation()


class AccessWindow(wx.Dialog):
	"""Not modal, so the user can go back to their work and return with the same command."""

	def __init__(self, parent: wx.Window, share: ShareSession, stopSharing: Callable[[], None]) -> None:
		# Translators: The title of the MCP Access window, where the user talks with their helper.
		super().__init__(parent, title=_("NVDA MCP Access"))
		self.share = share
		self._stopSharing = stopSharing
		sizer = wx.BoxSizer(wx.VERTICAL)
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.status = helper.addItem(
			wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE | wx.TE_NO_VSCROLL)
		)
		self.history = helper.addLabeledControl(
			# Translators: The label of the list of messages in the MCP Access window.
			_("&Messages:"),
			wx.ListBox,
			size=(560, 220),
		)
		self.message = helper.addLabeledControl(
			# Translators: The label of the field for a message to the helper in the MCP Access window.
			_("&Your message (Enter sends):"),
			wx.TextCtrl,
			style=wx.TE_PROCESS_ENTER,
		)
		self.message.Bind(wx.EVT_TEXT_ENTER, self.onSend)
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# Translators: A button in the MCP Access window that sends the message to the helper.
		self.sendButton = buttons.addButton(self, label=_("&Send"))
		self.sendButton.Bind(wx.EVT_BUTTON, self.onSend)
		# Translators: A button in the MCP Access window that ends sharing this computer.
		self.stopButton = buttons.addButton(self, label=_("S&top sharing"))
		self.stopButton.Bind(wx.EVT_BUTTON, self.onStop)
		# Translators: A button that closes the MCP Access window; sharing goes on.
		closeButton = buttons.addButton(self, id=wx.ID_CLOSE, label=_("&Close"))
		closeButton.Bind(wx.EVT_BUTTON, lambda event: self.Hide())
		helper.addDialogDismissButtons(buttons)
		self.SetEscapeId(wx.ID_CLOSE)
		self.Bind(wx.EVT_CLOSE, lambda event: self.Hide())
		sizer.Add(helper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.SetSizerAndFit(sizer)
		self.refresh()

	def refresh(self) -> None:
		"""Show the session as it is now. Runs on the main thread."""
		share = self.share
		if not share.isRunning:
			# Translators: Status in the MCP Access window after sharing ended.
			status = _("Sharing has ended. Share again for a new code.")
		elif share.isConnected:
			# Translators: Status in the MCP Access window. {helper} is their name; {check} the session check.
			status = _("Connected with {helper}. Session check: {check}.").format(
				helper=share.helperName, check=share.fingerprint
			)
		else:
			# Translators: Status in the MCP Access window while the code waits for a helper.
			status = _("Waiting for a helper. Code: {code}").format(code=share.code)
		self.status.SetValue(status)
		helperName = share.helperName or ""
		lines = []
		for message in share.messages:
			if message["from"] == "helper":
				# Translators: A message from the helper in the MCP Access window. {helper} is their name.
				lines.append(_("{helper}: {text}").format(helper=helperName, text=message["text"]))
			else:
				# Translators: A message the user sent, in the MCP Access window.
				lines.append(_("You: {text}").format(text=message["text"]))
		if lines != list(self.history.GetStrings()):
			self.history.Set(lines)
			if lines:
				self.history.SetSelection(len(lines) - 1)
		self.sendButton.Enable(share.isConnected)
		self.message.Enable(share.isConnected)
		self.stopButton.Enable(share.isRunning)

	def show(self) -> None:
		self.refresh()
		self.Show()
		self.Raise()
		(self.message if self.share.isConnected else self.history).SetFocus()

	def onSend(self, event: wx.CommandEvent) -> None:
		text = self.message.GetValue()
		if not text.strip() or not self.share.isConnected:
			return
		self.message.Clear()
		share = self.share

		def send() -> None:
			try:
				share.sendMessage(text)
			except (AccessShareError, OSError) as error:
				log.debugWarning("Could not send a message to the MCP Access helper", exc_info=True)
				# Translators: Reported when a message to the MCP Access helper could not be sent.
				wx.CallAfter(ui.message, _("The message could not be sent: {error}").format(error=error))
				return
			# Translators: Reported after a message to the MCP Access helper was sent.
			wx.CallAfter(ui.message, _("Message sent"))
			wx.CallAfter(self.refresh)

		threading.Thread(target=send, name="nvdaMcpAccessMessage", daemon=True).start()

	def onStop(self, event: wx.CommandEvent) -> None:
		self._stopSharing()
		self.Hide()
