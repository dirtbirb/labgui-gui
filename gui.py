import cv2
import numpy as np
import queue
import threading
import time
import wx


# Constants -------------------------------------------------------------------

# Basic
PX_PAD = 25
PX_PAD_INNER = 3
PX_PAD_OUTER = 10

# wx.Size
SZ_IMAGE = wx.Size(1280, 800)
SZ_THUMB = wx.Size(128, 80)
SZ_BTN = wx.Size(2*PX_PAD, 2*PX_PAD)
SZ1 = wx.Size(2*PX_PAD, PX_PAD)
SZ2 = wx.Size(3*PX_PAD, PX_PAD)
SZ3 = wx.Size(4*PX_PAD, PX_PAD)
HT1 = wx.Size(-1, PX_PAD)               # -1 = default
WD1 = wx.Size(2*PX_PAD, -1)
WD2 = wx.Size(3*PX_PAD, -1)
WD3 = wx.Size(4*PX_PAD, -1)

# wx.GBSpan (for wx.GridBagSizer)
SP1 = wx.GBSpan(1, 1)
SP2 = wx.GBSpan(1, 2)
SP3 = wx.GBSpan(1, 3)

# wx misc
ALIGN_CENTER_RIGHT = wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
CLR_BG = wx.Colour(0, 0, 0).MakeDisabled()


# Helper functions ------------------------------------------------------------

def attrib_name(name):
    ''' Turn a string into an acceptable attribute name '''
    return name.lower().replace(' ', '_')


def is_color(img):
    ''' Return True if image contains a color channel, False otherwise '''
    return len(img.shape) == 3


def make_binding(obj, func):
    def textctrl_binding(event):
        val = obj.GetValue()
        try:
            val = float(val)
        except ValueError:  # HACK: Reject '' or any non-numeric string
            val = None
        # Set parameter if given, update GUI with current value
        ret = func(val)
        if ret is False:
            ret = ''
        else:
            ret = str(ret)
        obj.SetValue(ret)

    def item_container_binding(event):
        # Set parameter if given, update GUI with current value
        obj.SetSelection(func(obj.GetSelection()))

    if isinstance(obj, wx.TextCtrl):
        binding = textctrl_binding
    elif isinstance(obj, wx.ItemContainerImmutable):
        binding = item_container_binding
    else:
        raise TypeError("Can't make binding for {}".format(type(obj)))
    return binding


def to_float(value):
    ''' Try to convert string to float; return string if failed '''
    try:
        value = float(value)
    except ValueError:
        pass
    return value


def top_px(img, n=1):
    ''' Return top nth pixel from an image '''
    if n == 1:
        ret = img.max()
    else:
        ret = np.partition(img.flatten(), -n)[-n]
    return ret


def top_px_avg(img, n=3):
    ''' Return average of top n pixels from an image '''
    if n == 1:
        ret = img.max()
    else:
        ret = np.partition(img.flatten(), -n)[-n:].mean()
    return ret


# Devices ---------------------------------------------------------------------

def test_image(shape=SZ_IMAGE[::-1]):
    ''' Generate random uint8 image of given shape '''
    return np.random.randint(0, 256, shape, np.uint8)


class GuiDevice(object):
    ''' Mixin class to add GUI panel functionality to a device.
        Inherited by GUI submodules. '''

    def __init__(self, panels={}):
        super().__init__()
        self.panels = panels
        self.available = True
        self.running = False

    def make_panel(self, parent, panel_name):
        return self.panels[panel_name](parent, self)

    def make_panels(self, parent):
        built_panels = []
        for panel_name in self.panels:
            built_panels.append(self.make_panel(parent, panel_name))
        return built_panels

    def start(self):
        self.running = True

    def close(self):
        self.running = False


class HybridDevice(GuiDevice):
    ''' Container for multiple interacting GuiDevices. '''

    def __init__(self, devices=[], panels={}):
        super().__init__(panels)
        self.devices = devices
        for device in self.devices:
            self.available &= device.available

    def start(self):
        running = True
        for device in self.devices:
            running &= device.start()
        if not running:
            self.close()
        else:
            self.running = running

    def close(self):
        for device in self.devices:
            device.close()
        self.running = False


class GuiSensor(GuiDevice):
    def __init__(self, img_queue, panels={}):
        self.img_queue = img_queue
        super().__init__(panels)


class TestSensor(GuiSensor):
    ''' Test device, fills img_queue with random image data '''

    TIMEOUT = 1

    def __init__(self, img_queue):
        super().__init__(img_queue)
        self.img_thread = None
        self.start()

    def start(self):
        def img_loop():
            while self.running:
                try:
                    self.img_queue.put(test_image(), timeout=self.TIMEOUT)
                except queue.Full:
                    pass

        self.running = True
        self.img_thread = threading.Thread(target=img_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

    def close(self):
        self.running = False
        self.img_thread = None


# wx.Dialog -------------------------------------------------------------------

# # TODO
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
    if dlg.ShowModal() == wx.ID_OK:     # If clicked "Save" or "Open"
        fn = dlg.GetPath()
        if ext and not fn[-4:].lower() == ext.lower():
            fn += ext
    else:                               # If clicked "Cancel"
        fn = False
    return fn


# wx.Sizer --------------------------------------------------------------------

class GuiItem():
    ''' Item and layout information for use in wx.GridBagSizer construction.
        Provides defaults and handles wx.GBPosition. '''

    def __init__(self, item, position, span=SP1, flag=0):
        self.item = item
        self.position = wx.GBPosition(position)
        self.span = span
        self.flag = flag


class GuiSizer(wx.GridBagSizer):
    ''' wx.GridBagSizer that accepts list of GuiItems to build itself. '''

    def __init__(self, items=None, hpad=None, vpad=None):
        super().__init__(hpad or PX_PAD_INNER, vpad or PX_PAD_INNER)
        if items is not None:
            self.AddList(items)

    def AddList(self, items):
        for item in items:
            self.Add(item.item, item.position, item.span, item.flag)


# wx.Panel --------------------------------------------------------------------

class GuiPanel(wx.Panel):
    ''' Panel containing GUI elements that can be read/set like attributes
        Also can be passed a device object for GUI to interact with. '''

    def __init__(self, parent, device=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.controls = []      # GUI elements for reset/update/validate
        self.device = device
        self.MakeSizerAndFit(self.MakeLayout())
        self.validate()

    def __getattribute__(self, name):
        ''' Retrieve value of GUI elements instead of elements themselves. '''
        # If attribute "name" is a wx object...
        elem = object.__getattribute__(self, name)
        if isinstance(elem, wx.Object):
            # Return content of TextCtrl, as float if possible
            # Return state of ToggleButton (HACK: as float, but whatever)
            if isinstance(elem, (wx.TextCtrl, wx.ToggleButton)):
                return to_float(elem.GetValue())
            # Return index of Choice, ComboBox, RadioBox
            # HACK: This prevents GetStringSelection, use GetElement for that
            elif isinstance(elem, wx.ItemContainerImmutable):
                return elem.GetSelection()
            # Return text value of StaticText, as float if possible
            elif isinstance(elem, wx.StaticText):
                return to_float(elem.GetLabel())
        # Return anything else as normal
        return elem

    def __setattr__(self, name, value):
        ''' Set value of GUI elements instead of overwriting elements. '''
        # If attribute "name" already exists...
        if hasattr(self, name):
            # If attribute "name" is a wx object...
            elem = object.__getattribute__(self, name)
            if isinstance(elem, wx.Object):
                # "value" is new state of ToggleButton
                if isinstance(elem, wx.ToggleButton):
                    elem.SetValue(value)
                    return
                # "value" is new string to display for TextCtrl
                elif isinstance(elem, wx.TextCtrl):
                    elem.SetValue(str(value))
                    return
                # "value" is new selection for Choice, ComboBox, RadioBox
                elif isinstance(elem, wx.ItemContainerImmutable):
                    if isinstance(value, int):
                        elem.SetSelection(value)
                    else:
                        elem.SetStringSelection(str(value))
                    return
                # "value" is new string to display for StaticText
                elif isinstance(elem, wx.StaticText):
                    elem.SetLabel(str(value))
                    return
        # Set anything else as normal
        object.__setattr__(self, name, value)

    def GetElement(self, name):
        ''' Bypass custom __getattribute__ to return a wx object. '''
        return object.__getattribute__(self, name)

    def MakeLabel(self):
        ''' Build and return a wx.StaticText from the panel name. '''
        return wx.StaticText(self, label=self.GetName())

    def MakeLayout(self):
        ''' Return list of elements and positions for MakeSizeAndFit.
            Override this to edit the panel layout. '''
        return []

    def MakeSizerAndFit(self, items):
        ''' Similar to SetSizerAndFit, but creates a GuiSizer first. '''
        self.SetSizerAndFit(GuiSizer(items))

    def reset(self, event=None):
        ''' Reset GuiPanel elements to default state. '''
        for control in self.controls:
            if isinstance(control, wx.TextCtrl):
                control.SetValue('')
            elif isinstance(control, wx.ToggleButton):
                control.SetValue(False)
            # elif isinstance(control, wx.ItemContainerImmutable):
            #     control.SetSelection(0)

    def update(self, event=None):
        ''' Refresh GuiPanel elements by triggering their event handlers. '''
        self.reset()
        for control in self.controls:
            if isinstance(control, wx.TextCtrl):
                evt = wx.EVT_TEXT_ENTER
            elif isinstance(control, wx.ToggleButton):
                evt = wx.EVT_TOGGLEBUTTON
            # elif isinstance(control, wx.RadioBox):
            #     evt = wx.EVT_RADIOBOX
            else:
                continue
            event = wx.PyCommandEvent(evt.typeId, control.GetId())
            control.GetEventHandler().ProcessEvent(event)

    def validate(self, event=None):
        ''' Verify device and check for valid input in GuiPanel elements. '''
        if self.device and not self.device.available:
            self.Disable()


class HybridPanel(GuiPanel):
    ''' Container panel to combine multiple GuiPanels. '''

    def __init__(self, parent, device=None, panels={}, **kwargs):
        self.panels = panels
        super().__init__(parent, device, **kwargs)

    def MakeLayout(self):
        layout = []
        for panel in self.panel_info:
            built_panel = panel(self, device=self.device)
            self.__setattr__(
                attrib_name(built_panel.GetName() + "_panel"), built_panel)
            layout.append(built_panel)
        return layout

    def MakeSizerAndFit(self, layout, orientation=wx.VERTICAL):
        panel_sizer = wx.BoxSizer(orientation)
        for item in layout:
            panel_sizer.Add(item)
            panel_sizer.AddSpacer(PX_PAD)
        self.SetSizerAndFit(panel_sizer)

    def reset(self, event=None):
        ''' Pass reset events to child GuiPanels '''
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                child.reset(event)

    def update(self, event=None):
        ''' Pass update events to child GuiPanels '''
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                child.update(event)

    def validate(self, event=None):
        ''' Pass validate events to child GuiPanels '''
        for child in self.GetChildren():
            if isinstance(child, GuiPanel):
                child.validate(event)


class ViewPanel(GuiPanel):
    ''' View options
        Unlike other panels, this panel is tightly integrated with BasicGui.
        Many functions use GetParent() to manipulate BasicGui directly. '''

    def __init__(self, parent, img_queue, name='View', **kwargs):
        super().__init__(parent, name=name, **kwargs)
        # Panel management
        self.parent = parent        # Directly manipulate parent frame
        self.device_panels = []     # Panels loaded by last sensor
        parent.Bind(wx.EVT_CLOSE, self.OnClose)     # HACK: must bind to frame
        # Fullscreen
        self.full_frame = FullscreenFrame(
            self, img_queue, parent.img_processes['dc'])
        self.Bind(wx.EVT_SET_FOCUS, self.OnFocus)   # HACK: doesn't work?
        # Save video
        self.video_writer = None    # cv2.VideoWriter
        parent.img_processes['full'].append(self.save_frame)
        # FPS (frames per second) counter
        self.frames = 0
        fps_thread = threading.Thread(target=self.__fps_loop)
        fps_thread.daemon = True
        fps_thread.start()

    def __fps_loop(self):
        ''' Target process for FPS counter thread '''
        def update(f):
            self.fps = f
        wait = self.parent.img_show.wait
        while True:
            wait()
            f0 = self.frames
            time.sleep(1)
            wx.CallAfter(update, str(self.frames - f0))     # Thread-safe

    def MakeLayout(self):
        # Make GUI elements
        source = wx.Choice(self, size=WD2)
        source.SetSelection(0)
        play_btn = wx.ToggleButton(self, label='Play', size=SZ1)
        full_btn = wx.ToggleButton(self, label='Full', size=SZ1)
        save_img_btn = wx.Button(self, label='Save', size=SZ1)
        save_vid_btn = wx.ToggleButton(self, label='Record', size=SZ1)
        fps_lbl = wx.StaticText(self, label='FPS ')
        fps = wx.StaticText(self, label='-', size=WD1)

        # Bind elements to functions
        play_btn.Bind(wx.EVT_TOGGLEBUTTON, self.play)
        full_btn.Bind(wx.EVT_TOGGLEBUTTON, self.fullscreen)
        save_img_btn.Bind(wx.EVT_BUTTON, self.save_img)
        save_vid_btn.Bind(wx.EVT_TOGGLEBUTTON, self.save_vid)
        source.Bind(wx.EVT_CHOICE, self.select_source)

        # Expose elements as attributes
        self.source = source
        self.play_btn = play_btn
        self.full_btn = full_btn
        self.save_img_btn = save_img_btn
        self.save_vid_btn = save_vid_btn
        self.fps = fps

        # Return layout for assembly
        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(source, (1, 0), SP2, wx.EXPAND),
            GuiItem(play_btn, (2, 0), flag=wx.EXPAND),
            GuiItem(full_btn, (2, 1), flag=wx.EXPAND),
            GuiItem(save_img_btn, (3, 0), flag=wx.EXPAND),
            GuiItem(save_vid_btn, (3, 1), flag=wx.EXPAND),
            GuiItem(fps_lbl, (4, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(fps, (4, 1)),
            ]
        return layout

    def OnClose(self, event):
        ''' Make sure any open device closes cleanly '''
        if self.device:
            self.device.close()
        event.Skip()    # Continue processing Close event

    def OnFocus(self, event):
        ''' Disable full_btn if focus is no longer on fullscreen_window '''
        self.full_btn = False
        event.Skip()

    def reset(self, event=None):
        if self.full_btn:
            self.full_btn = False
            self.fullscreen()
        if self.play_btn:
            self.play_btn = False
            self.play()
        if self.save_vid_btn:
            self.save_vid_btn = False
            self.save_vid()
        for panel in self.device_panels:
            panel.reset()

    def update(self, event=None):
        for panel in self.device_panels:
            panel.update()

    # Manage sources -------------------------------
    def add_source(self, name, obj, set_source=False):
        # Append name to GUI, append obj to ClientData for that selection
        source_select = self.GetElement('source')
        source_select.Append(name, obj)
        if set_source:
            self.set_source()

    def add_sources(self, sources, set_source=False):
        if isinstance(sources, list):   # Add each from the list
            for s in sources:
                self.add_source(*s)
        else:
            self.add_source(sources)    # If not actually a list
        if set_source:
            self.set_source()

    def del_source(self, index):
        self.GetElement('source').Delete(index)

    def select_source(self, event=None):
        parent = self.parent
        layout = parent.layout
        img_queue = parent.img_queue
        source_index = self.source
        # Reset ToggleButtons (not source selection)
        self.reset()
        # Remove old panels
        for old_panel in self.device_panels:
            old_panel.Destroy()
            for i, gui_panel in enumerate(layout['bottom']):
                if isinstance(old_panel, type(gui_panel)):
                    layout['bottom'].pop(i)
        self.device_panels = []
        # Remove old device
        if self.device:                     # Remove device
            self.device.close()
            self.device = None
            parent.img_processes = {        # Reset image processes
                'full': [self.save_frame],
                'resized': [],
                'dc': []}
        while not img_queue.empty():        # Purge any queued frames
            img_queue.get(False)
        # Create new device
        new_device = self.GetElement('source').GetClientData(source_index)
        try:
            self.device = new_device(img_queue)
        except Exception as e:
            print("Error: couldn't create sensor object. Details:\n", e)
            self.del_source(source_index)   # Remove device from list on fail
            return
        # Add new panels
        self.device_panels = self.device.make_panels(parent)
        for i, new_panel in enumerate(self.device_panels):
            layout['bottom'].insert(i+1, new_panel)
        # Reassemble GUI
        parent.Assemble()

    def set_source(self, i=0):
        self.GetElement('source').SetSelection(i)
        self.select_source()

    # Manage display -------------------------------
    def fullscreen(self, event=None):
        ''' Show/hide fullscreen frame '''
        self.full_frame.Show(self.full_btn)

    def play(self, event=None):
        flag = self.parent.img_show
        if self.play_btn:
            flag.set()
        else:
            flag.clear()

    def save_img(self, event=None):
        ''' Save still image via dialog '''
        parent = self.parent
        if parent and hasattr(parent, 'image') and parent.image is not None:
            img = parent.image.copy()
            fn = FileDialog('Save image', '.png', save=True)
            if fn:
                cv2.imwrite(fn, img, (cv2.IMWRITE_PNG_COMPRESSION, 5))

    def save_frame(self, img):
        if self.video_writer:
            if not is_color(img):
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            self.video_writer.write(img)
        return img

    def save_vid(self, event=None):
        ''' Start/stop recording, with save dialog '''
        flag = self.GetParent().img_show
        flag.clear()    # Pause capture
        if self.play_btn and self.save_vid_btn:
            fn = FileDialog('Save video', '.avi', save=True)
            if fn:                  # Start recording
                codec = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')
                fps = 10
                shape = self.GetParent().image.shape[:2][::-1]
                self.video_writer = cv2.VideoWriter(fn, codec, fps, shape)
            else:                   # Cancel recording
                self.save_vid_btn = False
        else:                       # Finish recording
            time.sleep(0.5)     # Wait for img pipeline (unnecessary?)
            if self.video_writer:
                self.video_writer.release()
            self.video_writer = None
        flag.set()      # Continue capture


# Sensor templates

# class MetricsPanel(GuiPanel):
#     ''' Metrics readout panel
#         Update values (not display!) by editing dict 'values'
#         Update display with most recent values with update()
#         Update list of values to be displayed with build()
#         Start regular updates by passing an Event flag to start()
#         Stop regular updates with stop() '''
#
#     def __init__(self, *args, name='Metrics', **kwargs):
#         if 'values' in kwargs:
#             self.values = kwargs.pop('values')
#         else:
#             self.values = {}
#         super().__init__(*args, name=name, **kwargs)
#         self.build()
#         self.updating = False
#
#     def build(self):
#         self.display = {}
#         new_items = [GuiItem(self.MakeLabel(), (0, 0), SP2)]
#         for name in self.values:
#             # Replace 'None' with '-' just to keep it clean
#             v = self.values[name]
#             if v is None:
#                 v = '-'
#             else:
#                 v = str(v)
#             # Build display
#             i = len(new_items)
#             label = wx.StaticText(self, label=name + ': ')
#             value = wx.StaticText(self, label=v)
#             new_items.extend([
#                 GuiItem(label, (i, 0), flag=ALIGN_CENTER_RIGHT),
#                 GuiItem(value, (i, 1))])
#             self.display[name] = value
#         self.MakeSizerAndFit(*new_items)
#
#     def update(self):
#         for name in self.values:
#             if name in self.display:
#                 self.display[name].SetValue(str(self.values[name]))
#
#     def start(self, update_flag):
#         def __update_loop(self):
#             while True:
#                 update_flag.wait()
#                 self.update()
#                 update_flag.clear()
#
#         self.updating = threading.Thread(
#             target=self.__update_loop, args=(update_flag, ))
#         self.updating.daemon = True
#         self.updating.start()
#
#     def stop(self):
#         if self.updating:
#             self.updating.terminate()
#         self.updating = False


class RoiPanel(GuiPanel):
    ''' ROI (Region Of Interest) control '''

    def __init__(self, *args, name='ROI', **kwargs):
        super().__init__(*args, name=name, **kwargs)

    def MakeLayout(self):
        offset_lbl = wx.StaticText(self, label='Offset')
        size_lbl = wx.StaticText(self, label='Size')
        x_lbl = wx.StaticText(self, label='x')
        x = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        w = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        y_lbl = wx.StaticText(self, label='y')
        y = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        h = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        apply = wx.Button(self, label='Set', size=SZ1)
        load = wx.Button(self, label='Load', size=SZ1)

        x.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        y.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        w.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        h.Bind(wx.EVT_TEXT_ENTER, self.set_roi)
        apply.Bind(wx.EVT_BUTTON, self.set_roi)
        # load.Bind(wx.EVT_BUTTON, self.set_roi)
        load.Disable()

        self.apply = apply
        self.load = load
        self.x = x
        self.w = w
        self.y = y
        self.h = h
        self.controls.extend([apply, load, x, w, y, h])
        self.reset()

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            GuiItem(offset_lbl, (1, 1), flag=wx.ALIGN_CENTER_HORIZONTAL),
            GuiItem(size_lbl, (1, 2), flag=wx.ALIGN_CENTER_HORIZONTAL),
            GuiItem(x_lbl, (2, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(x, (2, 1)),
            GuiItem(w, (2, 2)),
            GuiItem(y_lbl, (3, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(y, (3, 1)),
            GuiItem(h, (3, 2)),
            GuiItem(apply, (4, 1)),
            GuiItem(load, (4, 2))]
        return layout

    def reset(self, event=None):
        self.x = 0.0
        self.y = 0.0
        self.w = 1.0
        self.h = 1.0
        self.apply = False

    def set_roi(self, event=None):
        self.validate()
        if not self.device or not self.device.running:
            return
        self.x, self.y, self.w, self.h = self.device.roi(
            (self.x, self.y, self.w, self.h))

    def update(self, event=None):
        apply = self.apply
        self.reset()
        self.apply = apply

    def validate(self, event=None):
        try:
            self.x = np.clip(self.x, 0, 1)
            self.y = np.clip(self.y, 0, 1)
            self.w = np.clip(self.w, self.x, 1)
            self.h = np.clip(self.h, self.y, 1)
        except (ValueError, TypeError):
            self.reset()


class TextCtrlPanel(GuiPanel):
    ''' Provides build_settings as a helper method to create control panels
        from a list of settings. '''

    def build_textctrls(self, textctrls, start=(0, 0)):
        ''' Build column of functional wx.TextCtrls from a list of parameters.
            textctrls: List of parameter tuples for which to build controls:
                (label, units, function)
            start: (row, column) tuple of first element
            Sets panel attributes, binds functions, and returns GUI layout:
                [(StaticText label, TextCtrl value, StaticText units)...] '''

        if not isinstance(textctrls, (tuple, list)):
            raise TypeError(
                "TextSettingsPanel.build_textctrls requires a tuple or list.")

        i, j = start
        layout, controls = [], []
        for param, units, func in textctrls:
            # Create GUI layout
            label = wx.StaticText(self, label=param)
            field = wx.TextCtrl(
                self, size=SZ2, value='', style=wx.TE_PROCESS_ENTER)
            units = wx.StaticText(self, label=units)
            # Add GUI layout
            layout.extend([
                GuiItem(label, (i, j), flag=ALIGN_CENTER_RIGHT),
                GuiItem(field, (i, j+1), flag=wx.EXPAND),
                GuiItem(units, (i, j+2), flag=wx.ALIGN_CENTER_VERTICAL)])
            # Bind function to ctrl
            field.Bind(wx.EVT_TEXT_ENTER, make_binding(field, func))
            # Expose ctrl as panel attribute
            self.__setattr__(attrib_name(param), field)
            controls.append(field)
            i += 1
        self.controls.extend(controls)
        return layout


class CapturePanel(TextCtrlPanel):
    ''' Basic capture settings panel, example use of TextCtrlPanel '''

    def __init__(self, *args, name='Capture', **kwargs):
        super().__init__(*args, name=name, **kwargs)

    def MakeLayout(self):
        textctrls = [
            ('Exposure', 'us', self.device.exposure),
            ('Gain', '', self.device.gain),
            ('Framerate', 'fps', self.device.fps)
            ]
        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            *self.build_textctrls(textctrls, (1, 0))
            ]
        return layout


# Image processing

class ColorPanel(GuiPanel):
    ''' Color processing '''

    RED = np.uint8((0, 0, 255))
    RNG8 = np.arange(0, 256)    # Pixel values for range_img

    def __init__(self, *args, name='Color', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.gamma_lut = None
        self.sat_map = None
        self.GetParent().img_processes['resized'].append(self.process_img)

    def MakeLayout(self):
        colormaps = (
            'force gray',
            'no mapping',
            'autumn',
            'bone',
            'cool',
            'hot',
            'HSV',
            'jet',
            'ocean',
            'pink',
            'rainbow',
            'sping',
            'summer',
            'winter')
        colormap = wx.Choice(self, choices=colormaps)
        colormap.SetSelection(1)     # no colormap
        range_btn = wx.ToggleButton(self, label='Range', size=SZ2)
        range_val = wx.TextCtrl(
            self, value='255', size=SZ1, style=wx.TE_PROCESS_ENTER)
        gamma_btn = wx.ToggleButton(self, label='Gamma', size=SZ2)
        gamma_val = wx.TextCtrl(
            self, value='2.2', size=SZ1, style=wx.TE_PROCESS_ENTER)
        sat_btn = wx.ToggleButton(self, label='Highlight', size=SZ2)
        sat_val = wx.TextCtrl(
            self, value='255', size=SZ1, style=wx.TE_PROCESS_ENTER)

        range_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_range)
        range_val.Bind(wx.EVT_TEXT_ENTER, self.set_range)
        gamma_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_gamma)
        gamma_val.Bind(wx.EVT_TEXT_ENTER, self.set_gamma)
        sat_btn.Bind(wx.EVT_TOGGLEBUTTON, self.set_sat)
        sat_val.Bind(wx.EVT_TEXT_ENTER, self.set_sat)

        self.colormap = colormap
        self.range_btn = range_btn
        self.range_val = range_val
        self.gamma_btn = gamma_btn
        self.gamma_val = gamma_val
        self.sat_btn = sat_btn
        self.sat_val = sat_val
        self.controls.extend([
            colormap, range_btn, range_val, gamma_btn, gamma_val, sat_btn,
            sat_val])

        self.set_gamma()

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(colormap, (1, 0), SP2, wx.EXPAND),
            GuiItem(range_btn, (2, 0)),
            GuiItem(range_val, (2, 1)),
            GuiItem(gamma_btn, (3, 0)),
            GuiItem(gamma_val, (3, 1)),
            GuiItem(sat_btn, (4, 0)),
            GuiItem(sat_val, (4, 1))
            ]
        return layout

    def set_range(self, event=None):
        ''' Validate dynamic range value '''
        if self.range_btn:
            try:
                v = np.clip(int(self.range_val), 0, 255)
            except ValueError:
                v = 255
            self.range_val = v

    def set_gamma(self, event=None):
        ''' Validate gamma value and create look-up table (LUT) '''
        if self.gamma_btn:
            # Validate
            try:
                gamma = np.clip(self.gamma_val, 1.0, 10.0)
            except ValueError:
                gamma = 2.2
            # Create look-up table (LUT)
            self.gamma_lut = np.uint8(
                np.arange(0, 1, 1/256) ** (1/gamma) * 255 + 0.5)
            # Update displayed value
            self.gamma_val = gamma

    def set_sat(self, event=None):
        ''' Validate dynamic range value '''
        if self.sat_btn:
            try:
                v = np.clip(int(self.sat_val), 0, 255)
            except ValueError:
                v = 255
            self.sat_val = v

    def colormap_img(self, img):
        ''' Apply selected colormap by index '''
        colormap = self.colormap - 2
        if colormap > -1:                           # Colormap
            img = cv2.applyColorMap(img, colormap)
        elif colormap == -2 and is_color(img):      # Force gray
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

    def range_img(self, img):
        ''' Stretch dynamic range to be from 0 to self.range_val '''
        if self.range_btn:
            img -= img.min()
            if self.sat_btn and isinstance(self.sat_map, np.ndarray):
                mx = img[~self.sat_map].max()       # Ignore saturated pixels
            else:
                mx = img.max()
            img = cv2.LUT(
                img, np.uint8(self.RNG8 * self.range_val / mx))
        return img

    def gamma_img(self, img):
        ''' Apply gamma curve using lookup table '''
        if self.gamma_btn:
            img = cv2.LUT(img, self.gamma_lut)
        return img

    def find_sat_img(self, img):
        ''' Find and save locations of pixels above given threshold '''
        if self.sat_btn:
            self.sat_map = img >= self.sat_val
            if is_color(img):
                self.sat_map = np.logical_or.reduce(self.sat_map, 2)
        return img

    def apply_sat_img(self, img):
        ''' Make previously-saved pixels red '''
        if self.sat_btn and isinstance(self.sat_map, np.ndarray):
            if not is_color(img):
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img[self.sat_map] = self.RED
        return img

    def process_img(self, img):
        ''' Run all image processes from this panel in order '''
        processes = (
            self.find_sat_img,
            self.range_img,
            self.gamma_img,
            self.colormap_img,
            self.apply_sat_img)
        for process in processes:
            img = process(img)
        return img


class FlatFieldPanel(GuiPanel):
    ''' Flat field controls '''

    def __init__(self, *args, name='Flat field', **kwargs):
        self.ff = None      # Flat frame
        super().__init__(*args, name=name, **kwargs)
        self.GetParent().img_processes['full'].append(self.process_img)

    def MakeLayout(self):
        thumb = ImageWindow(self, size=SZ_THUMB)
        save = wx.Button(self, label='Update', size=SZ2)
        apply = wx.ToggleButton(self, label='Apply', size=SZ2)

        save.Bind(wx.EVT_BUTTON, self.save)
        apply.Bind(wx.EVT_TOGGLEBUTTON, self.validate)

        self.save = save
        self.apply = apply
        self.thumb = thumb
        self.controls.extend([save, apply, thumb])

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP2),
            GuiItem(thumb, (1, 0), SP2, wx.ALIGN_CENTER),
            GuiItem(save, (2, 0)),
            GuiItem(apply, (2, 1))
            ]
        return layout

    def save(self, event=None):
        ''' Update flat field and thumbnail '''
        # Save camera image
        self.ff = self.GetParent().image.copy()

        # Update thumbnail on gui
        thumb = cv2.resize(self.ff, tuple(SZ_THUMB))
        if is_color(thumb):
            thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        else:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2RGB)
        self.thumb.image = thumb
        self.thumb.Refresh()

    def validate(self, event=None):
        if self.ff is None:
            self.apply = False

    def flatfield_img(self, img):
        if self.apply:
            # Cancel if image size or color depth has changed
            if self.ff.shape != img.shape:
                self.apply = False
            else:
                img = np.where(img > self.ff, img - self.ff, 0)
        return img

    def process_img(self, img):
        return self.flatfield_img(img)


class TargetPanel(GuiPanel):
    ''' Target overlay '''

    def __init__(self, *args, name='Target', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.img_size = SZ_IMAGE  # Updated in process_img / process_dc

        # These can't be initialized at the class level...
        self.target_pen = wx.Pen((0, 200, 0), 2)  # Lime green
        self.target_brush = wx.Brush((0, 0, 0), wx.BRUSHSTYLE_TRANSPARENT)
        self.reset()
        self.GetParent().img_processes['dc'].append(self.process_dc)

    def MakeLayout(self):
        targets = ('no target', 'crosshair', 'box', 'circle')
        target = wx.Choice(self, choices=targets)
        size_lbl = wx.StaticText(self, label='Size ')
        size = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        reset_btn = wx.Button(
            self, label='Reset', size=SZ1, style=wx.BU_EXACTFIT)
        orig_lbl = wx.StaticText(self, label='Origin ')
        x = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        y = wx.TextCtrl(self, size=SZ1, style=wx.TE_PROCESS_ENTER)
        px_lbl = wx.StaticText(self, label='x, y ')
        px_x = wx.StaticText(self, style=wx.ALIGN_RIGHT)
        px_y = wx.StaticText(self, style=wx.ALIGN_RIGHT)

        reset_btn.Bind(wx.EVT_BUTTON, self.reset)
        for elem in (x, y, size):
            elem.Bind(wx.EVT_TEXT_ENTER, self.set_size)

        self.target = target
        self.size = size
        self.x = x
        self.y = y
        self.px_x = px_x
        self.px_y = px_y
        self.reset_btn = reset_btn
        self.controls.extend([target, size, x, y, px_x, px_y, reset_btn])

        layout = [
            GuiItem(self.MakeLabel(), (0, 0), SP3),
            GuiItem(target, (1, 0), SP3, wx.EXPAND),
            GuiItem(size_lbl, (2, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(size, (2, 1), flag=wx.EXPAND),
            GuiItem(reset_btn, (2, 2), flag=wx.EXPAND),
            GuiItem(orig_lbl, (3, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(x, (3, 1), flag=wx.EXPAND),
            GuiItem(y, (3, 2), flag=wx.EXPAND),
            GuiItem(px_lbl, (4, 0), flag=ALIGN_CENTER_RIGHT),
            GuiItem(px_x, (4, 1), flag=ALIGN_CENTER_RIGHT | wx.EXPAND),
            GuiItem(px_y, (4, 2), flag=ALIGN_CENTER_RIGHT | wx.EXPAND)
            ]
        return layout

    def reset(self, event=None):
        self.target = 0
        self.x = '0.5'
        self.y = '0.5'
        self.size = '20'
        self.set_size()

    def set_size(self, event=None):
        # TODO: Save/update config

        # Validate input
        for v in (self.x, self.y, self.size):
            if isinstance(v, str):
                self.reset()
                return

        # Update size in pixels
        if self.x < 1:
            self.px_x = int(self.img_size[0] * self.x)
        else:
            self.px_x = int(self.x)
        if self.y < 1:
            self.px_y = int(self.img_size[1] * self.y)
        else:
            self.px_y = int(self.y)

    def target_dc(self, dc):
        self.img_size = dc.Size
        target = self.target
        if self.target:
            # Set brushes
            dc.SetPen(self.target_pen)
            dc.SetBrush(self.target_brush)

            # Validate input
            try:
                x, y = float(self.x), float(self.y)
            except ValueError:
                self.reset()
                return

            # Convert sizes to pixels appropriate to given DC
            # TODO: do this for raw pixel entries too
            if x < 1:
                x_c = self.img_size[0] * x
            else:
                x_c = x
            if y < 1:
                y_c = self.img_size[1] * y
            else:
                y_c = y
            r = self.size

            # Draw target
            if target == 1:
                dc.DrawLineList((
                    (x_c, y_c-r, x_c, y_c-5),
                    (x_c, y_c+r, x_c, y_c+5),
                    (x_c-r, y_c, x_c-5, y_c),
                    (x_c+r, y_c, x_c+5, y_c)))
            elif target == 2:
                r2 = 2 * r
                dc.DrawRectangle(x_c-r, y_c-r, r2, r2)
            elif target == 3:
                dc.DrawCircle(x_c, y_c, r)

    def process_dc(self, dc):
        self.target_dc(dc)

    def target_img(self, img):
        # TODO: process opencv image
        return img

    def process_img(self, img):
        return self.target_img(img)


# wx.Window ------------------------------------------------------------------

class ImageWindow(wx.Window):
    ''' Basic wx.Window for painting images '''

    def __init__(self, parent, image=None, size=SZ_IMAGE, **kwargs):
        super().__init__(parent, size=size, **kwargs)
        self.image = image
        self.SetBackgroundColour(CLR_BG)
        self.SetMinClientSize(size)
        self.Bind(wx.EVT_PAINT, self.OnPaint)

    def OnPaint(self, event):
        ''' Draw image to GUI '''
        if self.image is not None:
            dc = wx.PaintDC(self)
            dc.DrawBitmap(
                wx.Bitmap.FromBuffer(*self.GetSize(), self.image), 0, 0)


class VideoWindow(ImageWindow):
    ''' Subclass of ImageWindow for rapidly painting images '''

    def __init__(self, parent, img_queue, dc_processes=[], size=SZ_IMAGE,
                 **kwargs):
        super().__init__(parent, size=size, **kwargs)
        self.dc_processes = dc_processes
        self.img_queue = img_queue

    def OnPaint(self, event):
        ''' Get image from queue and draw '''
        try:
            img = self.img_queue.get(timeout=0.1)
        except queue.Empty:
            return
        # Skip frame if not resized properly (window recently changed size)
        size = self.GetSize()
        if size == img.shape[:2][::-1]:
            # Draw image and update
            dc = wx.PaintDC(self)
            dc.DrawBitmap(wx.Bitmap.FromBuffer(*size, img), 0, 0)
            for process in self.dc_processes:
                process(dc)


# wx.Frame -------------------------------------------------------------------

class FullscreenFrame(wx.Frame):
    ''' Frame that simulates fullscreen on Show() '''

    def __init__(self, parent, img_queue, dc_processes=[], style=0, **kwargs):
        super().__init__(parent, style=style, **kwargs)
        self.img_window = VideoWindow(self, img_queue, dc_processes)
        self.img_window.Bind(wx.EVT_KEY_DOWN, self.OnKey)

    def OnKey(self, event):
        ''' Exit fullscreen on ESC and inform parent frame '''
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.GetParent().full_btn = False   # HACK: EVT_SET_FOCUS broken?
            self.Hide()

    def Show(self, show=True):
        if show:
            self.Maximize()
        super().Show(show)


class GuiFrame(wx.Frame):
    ''' Simple three-section GUI with image, left sidebar, and bottom bar. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Image control
        self.frames = 0
        self.img_show = threading.Event()
        self.img_queue = queue.Queue(1)
        self.img_processes = {
            'full': [],
            'resized': [],
            'dc': []
            }
        self.display_queue = queue.Queue(1)

        # GUI elements
        self.image = np.zeros(SZ_IMAGE, dtype=np.uint8)
        self.img_window = VideoWindow(
            self, self.display_queue, self.img_processes['dc'])
        self.view_panel = ViewPanel(self, self.display_queue)
        # TODO: Panel requests
        # self.panel_requests = {'sensor': 'all', 'stage': 'all'}
        self.layout = {
            'left': [],
            'right': [self.img_window],
            'bottom': [self.view_panel]
            }

        # Start display thread
        self.img_thread = threading.Thread(target=self.__display_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

    def __display_loop(self):
        ''' Run method for image display thread '''

        # Caching (avoids extra lookups, probably useless)
        BGR2RGB = cv2.COLOR_BGR2RGB
        GRAY2RGB = cv2.COLOR_GRAY2RGB
        cvtColor = cv2.cvtColor
        resize = cv2.resize
        display_queue = self.display_queue
        img_window = self.img_window
        img_processes = self.img_processes
        img_get = self.img_queue.get
        wait = self.img_show.wait
        view_panel = self.view_panel
        full_window = view_panel.full_frame.img_window

        while True:
            wait()                      # Wait for GUI "start"
            sensor_img = img_get()      # Wait for available image
            if sensor_img is None:      # Skip image errors
                print("Debug: 'None' found in image queue, skipped ")
                continue
            # Process full-frame image
            self.image = sensor_img     # Make image available to panels
            for process in img_processes['full']:
                sensor_img = process(sensor_img)
            # Resize to target window
            if view_panel.full_btn:
                window = full_window
            else:
                window = img_window
            display_img = resize(sensor_img, tuple(window.GetSize()))
            # Process resized image
            for process in img_processes['resized']:
                display_img = process(display_img)
            # Convert to RGB and send to wx
            if is_color(display_img):   # from BGR (OpenCV native format)
                cvt_method = BGR2RGB
            else:                       # from grayscale
                cvt_method = GRAY2RGB
            window.Refresh()
            display_queue.put(cvtColor(display_img, cvt_method))
            view_panel.frames += 1

    def Assemble(self):

        def add_module(parent, module, padding=PX_PAD):
            ''' Add module (panel or sizer) to parent sizer with padding '''
            parent.Add(module)
            parent.AddSpacer(padding)

        def construct_panel(orientation, modules, padding=PX_PAD):
            ''' Build sizer from modules with given orientation and padding '''
            sizer = wx.BoxSizer(orientation)
            if len(modules) > 0:
                if orientation == wx.VERTICAL:
                    sizer.AddSpacer(PX_PAD_OUTER)
                for module in modules[:-1]:
                    add_module(sizer, module, padding)
                add_module(sizer, modules[-1], PX_PAD_OUTER)
            return sizer

        # Assemble GUI elements
        layout = self.layout
        gui_sizer = wx.BoxSizer(wx.HORIZONTAL)
        left_szr = construct_panel(wx.VERTICAL, layout['left'])
        bot_szr = construct_panel(wx.HORIZONTAL, layout['bottom'])
        layout['right'].append(bot_szr)
        right_szr = construct_panel(wx.VERTICAL, layout['right'], PX_PAD_OUTER)
        layout['right'].pop()   # allow bot_szr to be deleted on Assemble()

        # Assemble GUI
        gui_sizer.AddSpacer(PX_PAD_OUTER)
        add_module(gui_sizer, left_szr, PX_PAD_OUTER)
        add_module(gui_sizer, right_szr, PX_PAD_OUTER)
        self.SetSizerAndFit(gui_sizer, deleteOld=True)
        self.Layout()   # HACK: Sometimes doesn't trigger in SetSizerAndFit?
        self.Show()
