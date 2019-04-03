import wx
# from sys import path


def debug(msg):
    # TODO: make actual debug function
    print(msg)


# Dialogs ---------------------------------------------------------------------
# TODO: convert to classes
# def showModalDialog(title, message, style):
#     dialog = wx.MessageDialog(self, message, title, style)
#     result = dialog:ShowModal()
#     dialog.Destroy()
#     return result
#
#
# def showInputDialog(title, message, default, style):
#     dialog = wx.TextEntryDialog(self, message, title, default, style)
#     dialog.ShowModal()
#     result = dialog:GetValue()
#     dialog.Destroy()
#     return result
#
#
# def ErrorDialog(message):
#     showModalDialog("ERROR", message, wx.OK + wx.ICON_ERROR)
#     return False
#
#
# def InfoDialog(message):
#     return showModalDialog("", message, wx.OK)
#
#
# def InputDialog(title, message, default):
#     default = default or ""
#     return showInputDialog(title, message, default, wx.OK + wx.CANCEL)


def FileDialog(msg, ext=None, save=False):
    ''' Show file save/open dialog with optional extension filter '''
    if save:
        style = wx.FD_SAVE
    else:
        style = wx.FD_OPEN
    dlg = wx.FileDialog(None, msg, wildcard='*'+ext, style=style)
    if dlg.ShowModal() == wx.ID_OK:
        fn = dlg.GetPath()
        if ext and not fn[-4:] in (ext, ext.lower(), ext.upper()):
            fn += ext
    else:
        fn = False
    return fn


class FullscreenFrame(wx.Frame):
    ''' Frame that simulates fullscreen on Show() '''

    def __init__(self, parent):
        super().__init__(parent, pos=(0, 0), style=0)

        def OnKey(event):
            ''' Exit fullscreen on ESC and inform parent frame '''
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                parent.fullscreen = False
                self.Hide()

        window = wx.Window(self)    # Required to process EVT_KEY_DOWN
        window.Bind(wx.EVT_KEY_DOWN, OnKey)

    def Show(self, show=True):
        super().Show(show)
        if show:
            super().Maximize()


class Gui(wx.Frame):
    ''' Simple GUI with a left sidebar, bottom bar, and image'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pad, self.pad_outer = 3, 10

    # Assemble GUI --------------------------------------------------------
    def set_padding(self, pad, pad_outer):
        self.pad, self.pad_outer = pad, pad_outer

    def assemble(self, layout=None, pad=None, pad_outer=None):
        pad = pad or self.pad
        pad_outer = pad_outer or self.pad_outer
        layout = self.layout or layout

        def add_module(parent, module, padding):
            parent.Add(module)
            parent.AddSpacer(padding)

        def construct_sizer(orientation, modules, padding):
            parent = wx.BoxSizer(orientation)
            if len(modules) > 0:
                if orientation == wx.VERTICAL:
                    parent.AddSpacer(pad_outer)
                for m in modules[:-1]:
                    add_module(parent, m, padding)
                add_module(parent, modules[-1], pad_outer)
            return parent

        # Initiallize GUI elements
        for func in layout['init_funcs']:
            func()

        # Assemble GUI elements
        left_szr = construct_sizer(wx.VERTICAL, layout['left'], pad)
        bot_szr = construct_sizer(wx.HORIZONTAL, layout['bottom'], pad)
        layout['right'].append(bot_szr)
        right_szr = construct_sizer(wx.VERTICAL, layout['right'], pad_outer)

        # Assemble GUI
        gui_szr = wx.BoxSizer(wx.HORIZONTAL)
        gui_szr.AddSpacer(pad_outer)
        add_module(gui_szr, left_szr, pad_outer)
        add_module(gui_szr, right_szr, pad_outer)
        self.SetSizerAndFit(gui_szr)
