import cv2
import numpy as np
import threading
import wx
import wx.lib.newevent
from queue import Queue
from time import sleep


# Constants -------------------------------------------------------------------

PX_PAD = 25
PX_PAD_INNER = 3
PX_PAD_OUTER = 10
SZ_IMAGE = (1280, 800)
SZ_THUMB = (128, 86)
SZ_BTN = (2*PX_PAD, 2*PX_PAD)
SZ1 = (2*PX_PAD, PX_PAD)
HT1 = (-1, PX_PAD)
WD2 = (3*PX_PAD, -1)
SZ2 = (3*PX_PAD, PX_PAD)
SZ3 = (4*PX_PAD, PX_PAD)
SP1 = wx.GBSpan(1, 1)
SP2 = wx.GBSpan(1, 2)
SP3 = wx.GBSpan(1, 3)
ALIGN_CENTER_RIGHT = wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
CLR_BG = wx.Colour(0, 0, 0).MakeDisabled()


# Helper functions ------------------------------------------------------------

# TODO: make actual debug function
def debug(msg):
    print(msg)


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
        obj.SetValue(str(func(val)))

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


def validate(v, mn=0, mx=255):
    ''' Limit a number to given range '''
    return max(min(v, mx), mn)


# Fake devices ----------------------------------------------------------------

def test_image(shape=SZ_IMAGE[::-1]):
    ''' Generate random uint8 image of given shape '''
    return np.random.randint(0, 256, shape, np.uint8)


class NullDevice(object):
    def __init__(self, queue=None):
        super().__init__()

    def make_panels(self, parent):
        return []

    def start(self):
        pass

    def close(self):
        pass


class TestSensor(NullDevice):
    def __init__(self, queue):
        super().__init__()
        self.img_queue = queue
        self.img_thread = None
        self.running = False
        self.start()

    def start(self):

        def img_loop():
            while self.running:
                self.img_queue.put(test_image())
                sleep(0.03)

        self.running = True
        self.img_thread = threading.Thread(target=img_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

    def close(self):
        self.running = False
        if self.img_thread:
            self.img_thread = None


# wx.Object (misc stuff) ------------------------------------------------------

class GuiSizer(wx.GridBagSizer):
    ''' wx GridBagSizer that accepts list of elements to build from '''

    def __init__(self, *items, hpad=None, vpad=None):
        super().__init__(hpad or PX_PAD_INNER, vpad or PX_PAD_INNER)
        for item in items:
            self.Add(*item)

    def AddList(sizer, *items):
        for item in items:
            sizer.Add(*item)


class ImageWindow(wx.Window):
    ''' Basic wx Window for painting images on '''

    def __init__(self, *args, size=SZ_IMAGE, **kwargs):
        super().__init__(*args, size=size, **kwargs)
        self.SetMinClientSize(size)
        self.SetBackgroundColour(CLR_BG)


# wx.Dialog -------------------------------------------------------------------

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


# wx.Panel --------------------------------------------------------------------

class GuiPanel(wx.Panel):
    ''' Panel containing GUI elements that can be read/set like attributes
        Also can be passed a device object for GUI to interact with. '''

    def __init__(self, *args, device=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.controls = []
        self.device = device

    def __getattribute__(self, name):
        ''' Retrieve value of GUI elements as properties '''
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
        ''' Set value of GUI elements as properties '''
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
        ''' Bypass custom __getattribute__ to return a wx object '''
        return object.__getattribute__(self, name)

    def MakeLabel(self):
        return wx.StaticText(self, label=self.GetName())

    def MakeSizerAndFit(self, *items):
        ''' Similar to SetSizerAndFit, but creates a GuiSizer first '''
        self.SetSizerAndFit(GuiSizer(*items))

    def reset(self, event=None):
        for control in self.controls:
            if isinstance(control, wx.TextCtrl):
                control.SetValue('')
            elif isinstance(control, wx.ToggleButton):
                control.SetValue(False)
            elif isinstance(control, wx.ItemContainerImmutable):
                control.SetSelection(0)

    def update(self, event=None):
        self.reset()
        for control in self.controls:
            wx.PostEvent(control, wx.EVT_COMMAND)


class ViewPanel(GuiPanel):
    ''' View options
        Unlike other panels, this panel is tightly integrated with BasicGui.
        Many functions use GetParent() to manipulate BasicGui directly. '''

    def __init__(self, *args, name='View', **kwargs):
        super().__init__(*args, name=name, **kwargs)
        self.parent = self.GetParent()

        # Background attributes
        self.device_panels = []
        self.frames = 0
        self.full_window = FullscreenFrame(self)
        self.video_writer = None

        # Make GUI elements
        source = wx.Choice(self, size=WD2)
        play_btn = wx.ToggleButton(self, label='Play', size=SZ1)
        full_btn = wx.ToggleButton(self, label='Full', size=SZ1)
        save_img_btn = wx.Button(self, label='Save', size=SZ1)
        save_vid_btn = wx.ToggleButton(self, label='Record', size=SZ1)
        fps_lbl = wx.StaticText(self, label='FPS ')
        fps = wx.StaticText(self, label='-')

        # Assemble GUI elements
        self.MakeSizerAndFit(
            (self.MakeLabel(), wx.GBPosition(0, 0), SP2),
            (source, wx.GBPosition(1, 0), SP2, wx.EXPAND),
            (play_btn, wx.GBPosition(2, 0), SP1, wx.EXPAND),
            (full_btn, wx.GBPosition(2, 1), SP1, wx.EXPAND),
            (save_img_btn, wx.GBPosition(3, 0), SP1, wx.EXPAND),
            (save_vid_btn, wx.GBPosition(3, 1), SP1, wx.EXPAND),
            (fps_lbl, wx.GBPosition(4, 0), SP1, ALIGN_CENTER_RIGHT),
            (fps, wx.GBPosition(4, 1)))

        # Expose GUI elements
        self.source = source
        self.play_btn = play_btn
        self.full_btn = full_btn
        self.save_img_btn = save_img_btn
        self.save_vid_btn = save_vid_btn
        self.fps = fps

        # Bind GUI elements to functions
        play_btn.Bind(wx.EVT_TOGGLEBUTTON, self.play)
        full_btn.Bind(wx.EVT_TOGGLEBUTTON, self.fullscreen)
        save_img_btn.Bind(wx.EVT_BUTTON, self.save_img)
        save_vid_btn.Bind(wx.EVT_TOGGLEBUTTON, self.save_vid)
        source.Bind(wx.EVT_CHOICE, self.select_source)

        # Finish init
        self.add_source('none', NullDevice)
        source.SetSelection(0)
        self.GetParent().img_processes['full'].append(self.save_frame)

        # FPS (frames per second) counter
        def fps_loop():
            def update(f):
                fps.SetLabel(f)

            wait = self.parent.img_start.wait
            while True:
                wait()
                f0 = self.frames
                sleep(1)
                wx.CallAfter(update, str(self.frames - f0))

        fps_thread = threading.Thread(target=fps_loop)
        fps_thread.daemon = True
        fps_thread.start()

    def add_source(self, name, obj):
        # Append name to GUI, obj to ClientData
        self.GetElement('source').Append(name, obj)

    def add_sources(self, sources):
        if isinstance(sources, list):   # Add each from the list
            for s in sources:
                self.add_source(*s)
        else:
            self.add_source(sources)    # If not actually a list

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
        while not img_queue.empty():        # Purge any remaining frames
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

    def fullscreen(self, event=None):
        self.full_window.Show(self.full_btn)

    def play(self, event=None):
        flag = self.parent.img_start
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
        flag = self.GetParent().img_start
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
            sleep(0.5)  # Wait for any frames in the pipeline (unnecessary?)
            if self.video_writer:
                self.video_writer.release()
            self.video_writer = None
        flag.set()      # Continue capture

    def update(self, event=None):
        for panel in self.device_panels:
            panel.update()


# Sensor templates

class SettingsPanel(GuiPanel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, event=None):
        print("Got update!")


class RoiPanel(SettingsPanel):
    ''' ROI (Region Of Interest) control '''

    def __init__(self, *args, name='ROI', **kwargs):
        super().__init__(*args, name=name, **kwargs)

        offset_lbl = wx.StaticText(self, label='Offset')
        size_lbl = wx.StaticText(self, label='Size')
        x_lbl = wx.StaticText(self, label='x')
        x = wx.TextCtrl(self, value='0.0', size=SZ1, style=wx.TE_PROCESS_ENTER)
        w = wx.TextCtrl(self, value='1.0', size=SZ1, style=wx.TE_PROCESS_ENTER)
        y_lbl = wx.StaticText(self, label='y')
        y = wx.TextCtrl(self, value='0.0', size=SZ1, style=wx.TE_PROCESS_ENTER)
        h = wx.TextCtrl(self, value='1.0', size=SZ1, style=wx.TE_PROCESS_ENTER)
        apply = wx.Button(self, label='Set', size=SZ1)
        load = wx.Button(self, label='Load', size=SZ1)

        self.MakeSizerAndFit(
            (self.MakeLabel(), wx.GBPosition(0, 0), SP3),
            (offset_lbl, wx.GBPosition(1, 1), SP1,
                wx.ALIGN_CENTER_HORIZONTAL),
            (size_lbl, wx.GBPosition(1, 2), SP1, wx.ALIGN_CENTER_HORIZONTAL),
            (x_lbl, wx.GBPosition(2, 0), SP1, ALIGN_CENTER_RIGHT),
            (x, wx.GBPosition(2, 1), SP1),
            (w, wx.GBPosition(2, 2), SP1),
            (y_lbl, wx.GBPosition(3, 0), SP1, ALIGN_CENTER_RIGHT),
            (y, wx.GBPosition(3, 1), SP1),
            (h, wx.GBPosition(3, 2), SP1),
            (apply, wx.GBPosition(4, 1), SP1),
            (load, wx.GBPosition(4, 2), SP1))

        self.apply = apply
        self.load = load
        self.x = x
        self.w = w
        self.y = y
        self.h = h
        self.controls = [apply, load, x, w, y, h]

        def roi(event=None):
            if not self.device:
                return

            self.x = validate(self.x, mx=1)
            self.y = validate(self.y, mx=1)
            self.w = validate(self.w, mn=self.x, mx=1)
            self.h = validate(self.h, mn=self.y, mx=1)

            self.x, self.y, self.w, self.h = self.device.roi(
                (self.x, self.y, self.w, self.h))

        x.Bind(wx.EVT_TEXT_ENTER, roi)
        y.Bind(wx.EVT_TEXT_ENTER, roi)
        w.Bind(wx.EVT_TEXT_ENTER, roi)
        h.Bind(wx.EVT_TEXT_ENTER, roi)
        apply.Bind(wx.EVT_BUTTON, roi)
        # load.Bind(wx.EVT_BUTTON, self.set_roi)
        load.Disable()


class TextSettingsPanel(SettingsPanel):
    ''' Sensor settings panel
        Provides build_settings as a helper method to create control panels
        from a list of settings. '''

    def build_textctrls(self, textctrls, start=(0, 0)):
        ''' Build column of functional wx.TextCtrls from a list of parameters.
            textctrls: List of parameter tuples for which to build controls:
                (label, units, function)
            start: (row, column) tuple of first element
            Sets panel attributes, binds functions, and returns GUI elements:
                [(StaticText label, TextCtrl value, StaticText units)...] '''

        if not isinstance(textctrls, list):
            raise TypeError("SettingsPanel.build_column() requires a list")

        i, j = start
        elements, controls = [], []
        for param, units, func in textctrls:
            # Create GUI elements
            label = wx.StaticText(self, label=param)
            field = wx.TextCtrl(
                self, size=SZ2, value='', style=wx.TE_PROCESS_ENTER)
            units = wx.StaticText(self, label=units)
            # Add GUI layout
            elements.extend([
                (label, wx.GBPosition(i, j), SP1, ALIGN_CENTER_RIGHT),
                (field, wx.GBPosition(i, j+1), SP1, wx.EXPAND),
                (units, wx.GBPosition(i, j+2), SP1,
                    wx.ALIGN_CENTER_VERTICAL)])
            # Bind function to ctrl
            field.Bind(wx.EVT_TEXT_ENTER, make_binding(field, func))
            # Expose ctrl as panel attribute
            self.__setattr__(param.lower().replace(' ', '_'), field)
            controls.append(field)
            i += 1
        self.controls = controls
        return elements


class MetricsPanel(GuiPanel):
    ''' Metrics readout panel
        Update values (not display!) by editing dict 'values'
        Update display with most recent values with update()
        Update list of values to be displayed with build()
        Start regular updates by passing an Event flag to start()
        Stop regular updates with stop() '''

    def __init__(self, *args, name='Metrics', **kwargs):
        if 'values' in kwargs:
            self.values = kwargs.pop('values')
        else:
            self.values = {}
        super().__init__(*args, name=name, **kwargs)
        self.build()
        self.updating = False

    def build(self):
        self.display = {}
        new_items = [(self.MakeLabel(), wx.GBPosition(0, 0), SP2)]
        for name in self.values:
            # Replace 'None' with '-' just to keep it clean
            v = self.values[name]
            if v is None:
                v = '-'
            else:
                v = str(v)
            # Build display
            i = len(new_items)
            label = wx.StaticText(self, label=name + ': ')
            value = wx.StaticText(self, label=v)
            new_items.extend([
                (label, wx.GBPosition(i, 0), SP1, ALIGN_CENTER_RIGHT),
                (value, wx.GBPosition(i, 1))])
            self.display[name] = value
        self.MakeSizerAndFit(*new_items)

    def update(self):
        for name in self.values:
            if name in self.display:
                self.display[name].SetValue(str(self.values[name]))

    def start(self, update_flag):
        def __update_loop(self):
            while True:
                update_flag.wait()
                self.update()
                update_flag.clear()

        self.updating = threading.Thread(
            target=self.__update_loop, args=(update_flag, ))
        self.updating.daemon = True
        self.updating.start()

    def stop(self):
        if self.updating:
            self.updating.terminate()
        self.updating = False


# Image processing

class ColorPanel(GuiPanel):
    ''' Color processing '''

    def __init__(self, *args, name='Color', **kwargs):
        super().__init__(*args, name=name, **kwargs)

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

        self.MakeSizerAndFit(
            (self.MakeLabel(), wx.GBPosition(0, 0), SP2),
            (colormap, wx.GBPosition(1, 0), SP2, wx.EXPAND),
            (range_btn, wx.GBPosition(2, 0), SP1, wx.EXPAND),
            (range_val, wx.GBPosition(2, 1), SP1, wx.EXPAND),
            (gamma_btn, wx.GBPosition(3, 0), SP1, wx.EXPAND),
            (gamma_val, wx.GBPosition(3, 1), SP1, wx.EXPAND),
            (sat_btn, wx.GBPosition(4, 0), SP1, wx.EXPAND),
            (sat_val, wx.GBPosition(4, 1), SP1, wx.EXPAND))

        self.colormap = colormap
        self.range_btn = range_btn
        self.range_val = range_val
        self.gamma_btn = gamma_btn
        self.gamma_val = gamma_val
        self.sat_btn = sat_btn
        self.sat_val = sat_val
        self.controls = [colormap, range_btn, range_val, gamma_btn, gamma_val,
            sat_btn, sat_val]

        self.set_gamma()
        self.GetParent().img_processes['resized'].append(self.process_img)

    def set_range(self, event=None):
        ''' Validate dynamic range value '''
        if self.range_btn:
            try:
                v = validate(int(self.range_val))
            except ValueError:
                v = 255
            self.range_val = v

    def set_gamma(self, event=None):
        ''' Validate gamma value and create look-up table (LUT) '''
        if self.gamma_btn:
            try:
                # Validate
                gamma = validate(self.gamma_val, 0.0, 10.0)
                # Create look-up table (LUT)
                self.gamma_lut = np.array(
                    np.arange(0, 1, 1/256) ** (1/gamma) * 255 + 0.5, np.uint8)
            except ValueError:
                gamma = 2.2
            # Update GUI
            self.gamma_val = gamma

    def set_sat(self, event=None):
        ''' Validate dynamic range value '''
        if self.sat_btn:
            try:
                v = validate(int(self.sat_val))
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
            f = self.range_val / top_px(img, 20)
            img = np.uint8(np.where(img < 255 / f, img * f, 255))
        return img

    def gamma_img(self, img):
        ''' Apply gamma curve using lookup table '''
        if self.gamma_btn:
            img = cv2.LUT(img, self.gamma_lut)
        return img

    def find_sat_img(self, img):
        ''' Find and save locations of pixels above given threshold '''
        if self.sat_btn:
            if is_color(img):
                self.saturated = np.logical_or.reduce(img >= self.sat_val, 2)
            else:
                self.saturated = img >= self.sat_val
        return img

    def apply_sat_img(self, img):
        ''' Make previously-saved pixels red '''
        if self.sat_btn and hasattr(self, 'saturated'):
            if not is_color(img):
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            img[self.saturated] = (0, 0, 255)   # red
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
        super().__init__(*args, name=name, **kwargs)

        self.ff = None  # Flat frame

        thumb = ImageWindow(self, size=SZ_THUMB)
        save = wx.Button(self, label='Update', size=SZ2)
        apply = wx.ToggleButton(self, label='Apply', size=SZ2)

        save.Bind(wx.EVT_BUTTON, self.save)
        apply.Bind(wx.EVT_TOGGLEBUTTON, self.validate)

        self.MakeSizerAndFit(
            (self.MakeLabel(), wx.GBPosition(0, 0), SP2),
            (thumb, wx.GBPosition(1, 0), SP2, wx.ALIGN_CENTER),
            (save, wx.GBPosition(2, 0), SP1),
            (apply, wx.GBPosition(2, 1), SP1))

        self.save = save
        self.apply = apply
        self.thumb = thumb
        self.controls = [save, apply, thumb]

        self.GetParent().img_processes['full'].append(self.process_img)

    def save(self, event=None):
        ''' Update flat field and thumbnail '''
        # Save camera image
        self.ff = self.GetParent().image.copy()

        # Update thumbnail on gui
        thumb = cv2.resize(self.ff, SZ_THUMB)
        if is_color(thumb):
            thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        else:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2RGB)
        dc = wx.ClientDC(self.thumb)
        dc.DrawBitmap(wx.Bitmap.FromBuffer(*SZ_THUMB, thumb), 0, 0)
        self.thumb.Update()

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

        self.targets = ('no target', 'crosshair', 'box', 'circle')
        target = wx.Choice(self, choices=self.targets)
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

        self.MakeSizerAndFit(
            (self.MakeLabel(), wx.GBPosition(0, 0), SP3),
            (target, wx.GBPosition(1, 0), SP3, wx.EXPAND),
            (size_lbl, wx.GBPosition(2, 0), SP1, ALIGN_CENTER_RIGHT),
            (size, wx.GBPosition(2, 1), SP1, wx.EXPAND),
            (reset_btn, wx.GBPosition(2, 2), SP1, wx.EXPAND),
            (orig_lbl, wx.GBPosition(3, 0), SP1, ALIGN_CENTER_RIGHT),
            (x, wx.GBPosition(3, 1), SP1, wx.EXPAND),
            (y, wx.GBPosition(3, 2), SP1, wx.EXPAND),
            (px_lbl, wx.GBPosition(4, 0), SP1, ALIGN_CENTER_RIGHT),
            (px_x, wx.GBPosition(4, 1), SP1, ALIGN_CENTER_RIGHT | wx.EXPAND),
            (px_y, wx.GBPosition(4, 2), SP1, ALIGN_CENTER_RIGHT | wx.EXPAND))

        self.target = target
        self.size = size
        self.x = x
        self.y = y
        self.px_x = px_x
        self.px_y = px_y
        self.reset_btn = reset_btn
        self.controls = [target, size, x, y, px_x, px_y, reset_btn]

        self.reset()

        self.GetParent().img_processes['dc'].append(self.process_dc)

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


# wx.Frame -------------------------------------------------------------------

class FullscreenFrame(wx.Frame):
    ''' Frame that simulates fullscreen on Show() '''

    def __init__(self, *args, style=0, **kwargs):
        super().__init__(*args, style=style, **kwargs)

        def on_key(event):
            ''' Exit fullscreen on ESC and inform parent frame '''
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.GetParent().full_btn = False
                self.Hide()

        window = wx.Window(self)    # Required to process EVT_KEY_DOWN
        window.Bind(wx.EVT_KEY_DOWN, on_key)

    def Show(self, show=True):
        super().Show(show)
        if show:
            self.Maximize()


class GuiFrame(wx.Frame):
    ''' Simple three-section GUI with image, left sidebar, and bottom bar. '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Image control
        self.frames = 0
        self.img_start = threading.Event()
        self.img_queue = Queue(1)
        self.img_processes = {
            'full': [],
            'resized': [],
            'dc': []
            }

        # GUI elements
        self.image = np.zeros(SZ_IMAGE, dtype=np.uint8)
        self.image_window = ImageWindow(self)
        self.view_panel = ViewPanel(self)
        # self.panel_requests = {'sensor': 'all', 'stage': 'all'}
        self.layout = {
            'left': [],
            'right': [self.image_window],
            'bottom': [self.view_panel]
            }

        # Start display thread
        def display_loop():
            ''' Run method for image display thread '''

            # Caching (avoids extra lookups, probably useless)
            BGR2RGB = cv2.COLOR_BGR2RGB
            GRAY2RGB = cv2.COLOR_GRAY2RGB
            cvtColor = cv2.cvtColor
            resize = cv2.resize
            Bitmap = wx.Bitmap.FromBuffer
            CallAfter = wx.CallAfter
            ClientDC = wx.ClientDC
            gui_window = self.image_window
            img_processes = self.img_processes
            img_get = self.img_queue.get
            wait = self.img_start.wait
            view_panel = self.view_panel
            full_window = view_panel.full_window

            display_queue = Queue(1)
            display_get = display_queue.get
            display_put = display_queue.put

            def display(window):
                ''' Get image and draw to wx window '''
                sz, img = window.GetSize(), display_get()
                # Skip frame if resized incorrectly for current window
                if sz == img.shape[:2][::-1]:
                    # Draw display window and update
                    dc = ClientDC(window)
                    dc.DrawBitmap(Bitmap(*sz, img), 0, 0)
                    for process in img_processes['dc']:
                        process(dc)
                    window.Update()
                    view_panel.frames += 1

            while True:
                wait()                      # Wait for GUI "start"
                sensor_img = img_get()      # Wait for available image
                if sensor_img is None:      # Skip image errors
                    print("Debug: Image queue skipped 'None'")
                    continue

                # Full-frame image processing
                self.image = sensor_img     # Make image available to panels
                for process in img_processes['full']:
                    sensor_img = process(sensor_img)

                # Resize to target window
                if view_panel.full_btn:
                    window = full_window
                else:
                    window = gui_window
                display_img = resize(sensor_img, tuple(window.GetSize()))

                # Resized-frame image processing
                for process in img_processes['resized']:
                    display_img = process(display_img)

                # Convert to RGB and send to wx
                if is_color(display_img):   # from BGR (OpenCV native format)
                    cvt_method = BGR2RGB
                else:                       # from grayscale
                    cvt_method = GRAY2RGB
                display_put(cvtColor(display_img, cvt_method))
                CallAfter(display, window)  # thread-safe

        self.img_thread = threading.Thread(target=display_loop)
        self.img_thread.daemon = True
        self.img_thread.start()

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
